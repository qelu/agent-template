#!/usr/bin/env python3
"""Create and provision a governed agent harness through a terminal wizard or CLI."""

from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.initializer import (  # noqa: E402
    BASELINE_PREREQUISITES,
    DEFAULT_DOCUMENTATION_PROVIDER,
    DOCUMENTATION_PROVIDERS,
    GOOGLE_WORKSPACE_DEFAULT_SERVICES,
    GOOGLE_WORKSPACE_SERVICES,
    HOSTS,
    InitializationSpec,
    InstallationPlan,
    InitializerError,
    antigravity_rovo_runtime,
    capability_choices,
    destination_error,
    execute_plan,
    google_workspace_client_error,
    integration_choices,
    load_initializer_config,
    resolve_plan,
    slug,
)

ASCII_ART = r"""
    ___                    __     __  __
   /   | ____ ____  ____  / /_   / / / /___ __________  ___  __________
  / /| |/ __ `/ _ \/ __ \/ __/  / /_/ / __ `/ ___/ __ \/ _ \/ ___/ ___/
 / ___ / /_/ /  __/ / / / /_   / __  / /_/ / /  / / / /  __(__  |__  )
/_/  |_\__, /\___/_/ /_/\__/  /_/ /_/\__,_/_/  /_/ /_/\___/____/____/
      /____/                    I N I T I A L I Z E R
"""

HOST_LABELS = {
    "portable": "Portable — shared files only; configure a host later",
    "codex": "Codex — AGENTS.md, Codex sandbox settings, hooks, and skills",
    "claude-code": "Claude Code — CLAUDE.md, permissions, hooks, and skills",
    "antigravity": "Antigravity — AGENTS.md, GEMINI.md, hooks, and skills",
}

DOCUMENTATION_PROVIDER_LABELS = {
    "none": "None — do not add an official documentation integration",
    "openai": "OpenAI — connect the official OpenAI developer-docs MCP server",
    "anthropic": "Anthropic — add a skill for current official Claude documentation",
    "gemini": "Gemini — connect the official Gemini documentation MCP server",
}

HOST_CLI_NAMES = {
    "codex": "Codex",
    "claude-code": "Claude Code",
    "antigravity": "Antigravity",
}

ATLASSIAN_ROVO_ENDPOINT = "https://mcp.atlassian.com/v1/mcp/authv2"
MINIMUM_PYTHON = (3, 11)


def require_initializer_prerequisites() -> None:
    """Fail before the wizard when mandatory local tooling is unavailable."""
    problems: list[str] = []
    if sys.version_info[:2] < MINIMUM_PYTHON:
        problems.append(
            f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer "
            f"(running {sys.version_info.major}.{sys.version_info.minor})"
        )
    missing_commands = [
        command for command in BASELINE_PREREQUISITES if shutil.which(command) is None
    ]
    if missing_commands:
        problems.append("commands on PATH: " + ", ".join(missing_commands))
    if problems:
        raise InitializerError(
            "Missing required initializer prerequisites: "
            + "; ".join(problems)
            + ". Install every prerequisite listed in README.md, then retry."
        )


def host_cli_unavailable_message(host: str, binary: str) -> str:
    message = (
        f"{HOST_CLI_NAMES[host]} CLI command (`{binary}`) is not available on this shell's PATH."
    )
    if host == "codex":
        message += (
            " This checks the terminal CLI only; the Codex desktop app may still be installed."
        )
    return message


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--wizard", action="store_true", help="force the interactive wizard")
    result.add_argument("--destination", type=Path)
    result.add_argument("--name")
    result.add_argument("--id", dest="agent_id")
    result.add_argument("--goal")
    result.add_argument("--role")
    result.add_argument("--tone")
    result.add_argument("--language", default="en-US")
    result.add_argument("--host", choices=(*HOSTS, "gemini-cli"), default="portable")
    result.add_argument("--docs-provider", choices=DOCUMENTATION_PROVIDERS)
    result.add_argument(
        "--capability",
        action="append",
        dest="capabilities",
        help="include a capability; repeat as needed (required capabilities are automatic)",
    )
    result.add_argument(
        "--integration",
        action="append",
        dest="integrations",
        help="configure an optional integration; repeat as needed",
    )
    result.add_argument(
        "--bundle",
        action="append",
        dest="bundles",
        help="include a named capability and integration bundle; repeat as needed",
    )
    result.add_argument("--python", dest="python_version", default="3.13")
    result.add_argument("--install", action="store_true", help="create the project environment")
    result.add_argument(
        "--dev-tools",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="include and validate development tools",
    )
    result.add_argument("--security-tools", action="store_true", help="validate with Gitleaks")
    result.add_argument(
        "--install-host-tool",
        action="store_true",
        help="install a missing selected host CLI after plan approval",
    )
    result.add_argument(
        "--google-workspace-client",
        type=Path,
        help="existing Google Desktop or Web OAuth client JSON for the community Workspace MCP",
    )
    result.add_argument(
        "--google-workspace-service",
        action="append",
        choices=GOOGLE_WORKSPACE_SERVICES,
        help="Google Workspace service to authorize; repeat as needed",
    )
    result.add_argument(
        "--google-workspace-readonly",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="limit selected Google Workspace services to read-only scopes",
    )
    result.add_argument("--dry-run", action="store_true", help="resolve and print without changes")
    result.add_argument(
        "--yes",
        action="store_true",
        help="approve external installation commands in non-interactive mode",
    )
    result.add_argument("--no-color", action="store_true")
    return result


def required(value: str | None, label: str) -> str:
    if value and value.strip():
        return value.strip()
    raise InitializerError(f"Missing --{label} in non-interactive mode")


def cli_spec(args: argparse.Namespace) -> InitializationSpec:
    if args.destination is None:
        raise InitializerError("Missing --destination in non-interactive mode")
    name = required(args.name, "name")
    return InitializationSpec(
        destination=args.destination,
        name=name,
        agent_id=args.agent_id or name,
        goal=required(args.goal, "goal"),
        role=required(args.role, "role"),
        tone=required(args.tone, "tone"),
        language=args.language,
        host=args.host,
        documentation_provider=args.docs_provider,
        capabilities=None if args.capabilities is None else tuple(args.capabilities),
        integrations=tuple(args.integrations or ()),
        bundles=tuple(args.bundles or ()),
        python_version=args.python_version,
        install_dependencies=args.install,
        development_tools=args.dev_tools,
        security_tools=args.security_tools,
        install_host_tool=args.install_host_tool,
        google_workspace_client=args.google_workspace_client,
        google_workspace_services=tuple(
            args.google_workspace_service or GOOGLE_WORKSPACE_DEFAULT_SERVICES
        ),
        google_workspace_readonly=args.google_workspace_readonly,
    )


def wizard_spec(source: Path, *, no_color: bool) -> InitializationSpec:
    try:
        import questionary
        from questionary import Choice
        from rich.console import Console
        from rich.panel import Panel
    except ImportError as exc:
        raise InitializerError(
            "The terminal wizard requires project dependencies; run `uv sync` first"
        ) from exc

    console = Console(no_color=no_color)
    console.print(Panel.fit(ASCII_ART, border_style="cyan", subtitle="Governed by construction"))
    console.print("Build a portable, least-authority agent harness.\n", style="dim")
    initializer = load_initializer_config(source)
    defaults = initializer["defaults"]

    console.print("[bold cyan]Project location[/bold cyan]")
    console.print(
        "Choose a new folder or an existing empty folder. Non-empty folders are never overwritten.",
        style="dim",
    )
    destination = _ask(
        questionary.path(
            "Destination folder",
            default="../my-agent",
            validate=lambda value: destination_error(source, Path(value)) or True,
        )
    )

    console.print("\n[bold cyan]Identity and persona[/bold cyan]")
    console.print(
        "These answers become config/persona.yaml: who the agent is, what it should accomplish, "
        "and how it should communicate.",
        style="dim",
    )
    name = _ask(questionary.text("Display name — shown in generated documentation"))
    agent_id = _ask(questionary.text("Agent ID — stable lowercase identifier", default=slug(name)))
    console.print(
        'Primary goal example: "Review pull requests and identify security or correctness '
        'issues before merge."',
        style="dim",
    )
    goal = _ask(questionary.text("Primary goal — what should this agent achieve?"))
    role = _ask(
        questionary.text(
            "Persona role — identity, expertise, and working stance", default="assistant"
        )
    )
    tone = _ask(
        questionary.text(
            "Communication tone — preferred response style", default="clear and concise"
        )
    )
    language = _ask(questionary.text("Language/locale — for example en-US", default="en-US"))

    console.print("\n[bold cyan]Host and documentation[/bold cyan]")
    console.print(
        "The host runs the agent. The documentation integration gives it current, official "
        "provider references.",
        style="dim",
    )
    host = _ask(
        questionary.select(
            "Host",
            choices=[Choice(HOST_LABELS[value], value=value) for value in HOSTS],
            default=defaults["host"],
        )
    )
    docs_default = DEFAULT_DOCUMENTATION_PROVIDER[host]
    documentation_provider = _ask(
        questionary.select(
            "Official documentation integration",
            choices=[
                Choice(DOCUMENTATION_PROVIDER_LABELS[value], value=value)
                for value in DOCUMENTATION_PROVIDERS
            ],
            default=docs_default,
        )
    )
    selected_bundles: list[str] = []
    supported_integration_ids = {
        choice.integration_id for choice in integration_choices(source, host)
    }
    compatible_bundles = {
        bundle_id: bundle
        for bundle_id, bundle in initializer["bundles"].items()
        if set(bundle["integrations"]).issubset(supported_integration_ids)
    }
    incompatible_bundles = {
        bundle_id: bundle
        for bundle_id, bundle in initializer["bundles"].items()
        if bundle_id not in compatible_bundles
    }
    if compatible_bundles:
        console.print("\n[bold cyan]Optional bundles[/bold cyan]")
        selected_bundles = _ask(
            questionary.checkbox(
                "Bundles — transparent shortcuts for related optional features",
                choices=[
                    Choice(
                        f"{bundle_id} — {bundle['description']}",
                        value=bundle_id,
                        checked=False,
                    )
                    for bundle_id, bundle in compatible_bundles.items()
                ],
            )
        )
    for bundle_id, bundle in incompatible_bundles.items():
        console.print(
            f"  [yellow]–[/yellow] {bundle_id} [dim](unavailable for {host}) — "
            f"{bundle['description']}[/dim]"
        )
    bundled_capabilities = {
        capability
        for bundle_id in selected_bundles
        for capability in initializer["bundles"][bundle_id]["capabilities"]
    }
    bundled_integrations = {
        integration
        for bundle_id in selected_bundles
        for integration in initializer["bundles"][bundle_id]["integrations"]
    }
    choices = capability_choices(source)
    required_choices = [choice for choice in choices if choice.required]
    optional_choices = [choice for choice in choices if not choice.required]
    console.print("\nRequired capabilities", style="bold cyan")
    for choice in required_choices:
        console.print(
            f"  [green]✓[/green] {choice.capability_id} [dim](locked) — {choice.description}[/dim]"
        )
    selected_optional: list[str] = []
    for capability_type in sorted({choice.capability_type for choice in optional_choices}):
        typed_choices = [
            choice for choice in optional_choices if choice.capability_type == capability_type
        ]
        bundled_choices = [
            choice for choice in typed_choices if choice.capability_id in bundled_capabilities
        ]
        selectable_choices = [
            choice for choice in typed_choices if choice.capability_id not in bundled_capabilities
        ]
        if bundled_choices:
            console.print(
                f"\nOptional {capability_type.replace('-', ' ').title()} capabilities",
                style="bold cyan",
            )
            for choice in bundled_choices:
                console.print(
                    f"  [green]✓[/green] {choice.capability_id} "
                    f"[dim](included by selected bundle) — {choice.description}[/dim]"
                )
        if not selectable_choices:
            continue
        selected_optional.extend(
            _ask(
                questionary.checkbox(
                    f"Optional {capability_type.replace('-', ' ').title()} capabilities",
                    choices=[
                        Choice(
                            f"{choice.capability_id} — {choice.description}",
                            value=choice.capability_id,
                            checked=choice.selected_by_default,
                        )
                        for choice in selectable_choices
                    ],
                )
            )
        )
    selected_capability_ids = {
        *(choice.capability_id for choice in required_choices),
        *bundled_capabilities,
        *selected_optional,
    }
    selected = tuple(
        choice.capability_id
        for choice in choices
        if choice.capability_id in selected_capability_ids
    )
    integrations = integration_choices(source, host)
    selected_integrations: tuple[str, ...] = ()
    if integrations:
        console.print("\n[bold cyan]External integrations[/bold cyan]")
        console.print(
            "Credentials are never stored in the project. Authentication happens after creation.",
            style="dim",
        )
        bundled_integration_choices = [
            choice for choice in integrations if choice.integration_id in bundled_integrations
        ]
        selectable_integration_choices = [
            choice for choice in integrations if choice.integration_id not in bundled_integrations
        ]
        for integration_choice in bundled_integration_choices:
            console.print(
                f"  [green]✓[/green] {integration_choice.integration_id} "
                f"({integration_choice.kind}) [dim](included by selected bundle) — "
                f"{integration_choice.description}[/dim]"
            )
        selected_integration_ids = set(bundled_integrations)
        if selectable_integration_choices:
            selected_integration_ids.update(
                _ask(
                    questionary.checkbox(
                        "Optional integrations",
                        choices=[
                            Choice(
                                f"{choice.integration_id} ({choice.kind}) — {choice.description}",
                                value=choice.integration_id,
                            )
                            for choice in selectable_integration_choices
                        ],
                    )
                )
            )
        selected_integrations = tuple(
            choice.integration_id
            for choice in integrations
            if choice.integration_id in selected_integration_ids
        )
    google_workspace_client: Path | None = None
    google_workspace_services = GOOGLE_WORKSPACE_DEFAULT_SERVICES
    google_workspace_readonly = True
    if "google-workspace" in selected_integrations:
        console.print("\n[bold cyan]Google Workspace authentication[/bold cyan]")
        console.print(
            "Provide a Google Desktop OAuth client, or a Web OAuth client containing the exact "
            "redirect URI http://localhost:8000/oauth2callback. It is copied to a user-only "
            "configuration directory and never into the generated project.",
            style="dim",
        )
        google_workspace_client = Path(
            _ask(
                questionary.path(
                    "Google OAuth client JSON",
                    validate=lambda value: google_workspace_client_error(Path(value)) or True,
                )
            )
        )
        google_workspace_services = tuple(
            _ask(
                questionary.checkbox(
                    "Google Workspace services to authorize",
                    choices=[
                        Choice(
                            service,
                            value=service,
                            checked=service in GOOGLE_WORKSPACE_DEFAULT_SERVICES,
                        )
                        for service in GOOGLE_WORKSPACE_SERVICES
                    ],
                    validate=lambda selected: (
                        bool(selected) or "Select at least one Google Workspace service"
                    ),
                )
            )
        )
        google_workspace_readonly = bool(
            _ask(
                questionary.confirm(
                    "Limit Google Workspace to read-only operations?",
                    default=True,
                )
            )
        )
    console.print("\n[bold cyan]Environment and validation[/bold cyan]")
    console.print(
        "Provisioning creates a project-local .venv; it never replaces system Python.",
        style="dim",
    )
    python_version = _ask(
        questionary.select(
            "Python version for the generated .venv",
            choices=[
                Choice("3.14 — newest supported version", value="3.14"),
                Choice("3.13 — default compatibility option", value="3.13"),
                Choice("3.12 — compatibility option", value="3.12"),
                Choice("3.11 — oldest supported version", value="3.11"),
            ],
            default=defaults["python"],
        )
    )
    install_dependencies = _ask(
        questionary.confirm(
            "Create the .venv, install selected packages, and validate the harness?", default=True
        )
    )
    development_tools = _ask(
        questionary.confirm(
            "Include development tools (formatting, tests, type checks, and pre-commit hooks)?",
            default=defaults["development_tools"],
        )
    )
    security_tools = _ask(
        questionary.confirm(
            "Scan the generated files for committed secrets with Gitleaks?",
            default=defaults["security_tools"],
        )
    )
    install_host_tool = False
    host_binary = {"codex": "codex", "claude-code": "claude", "antigravity": "agy"}.get(host)
    if host_binary:
        if not shutil.which(host_binary):
            console.print(host_cli_unavailable_message(host, host_binary), style="yellow")
            if host == "antigravity":
                console.print(
                    "Use Google's official installer before running the generated harness.",
                    style="yellow",
                )
            elif shutil.which("npm"):
                install_host_tool = _ask(
                    questionary.confirm(
                        f"Install the {HOST_CLI_NAMES[host]} CLI globally with npm as part of "
                        "this plan?",
                        default=False,
                    )
                )
            elif host == "codex":
                console.print(
                    "npm is also unavailable. Install the Codex CLI using the official guide: "
                    "https://developers.openai.com/codex/cli/",
                    style="yellow",
                )
            else:
                console.print(
                    "npm is also unavailable. Install the CLI with its official installer "
                    "before launching the generated harness.",
                    style="yellow",
                )
    return InitializationSpec(
        destination=Path(destination),
        name=name,
        agent_id=agent_id,
        goal=goal,
        role=role,
        tone=tone,
        language=language,
        host=host,
        documentation_provider=documentation_provider,
        capabilities=selected,
        integrations=selected_integrations,
        bundles=tuple(selected_bundles),
        python_version=python_version,
        install_dependencies=install_dependencies,
        development_tools=development_tools,
        security_tools=security_tools,
        install_host_tool=install_host_tool,
        google_workspace_client=google_workspace_client,
        google_workspace_services=google_workspace_services,
        google_workspace_readonly=google_workspace_readonly,
    )


def _ask(question: Any) -> Any:
    answer = question.ask()
    if answer is None:
        raise KeyboardInterrupt
    if isinstance(answer, str) and not answer.strip():
        raise InitializerError("Every requested value is required")
    return answer


def plan_payload(plan: InstallationPlan) -> dict[str, object]:
    return {
        "destination": str(plan.spec.destination),
        "host": plan.spec.host,
        "execution": "host-native",
        "run_identity": "host-session",
        "documentation_provider": plan.documentation_provider,
        "capabilities": list(plan.capabilities),
        "bundles": list(plan.bundles),
        "integrations": list(plan.integrations),
        "environment": {
            "python": plan.spec.python_version,
            "install_dependencies": plan.spec.install_dependencies,
            "development_tools": plan.spec.development_tools,
            "security_tools": plan.spec.security_tools,
        },
        "detected_tools": {
            status.command: "detected" if status.available else "missing" for status in plan.tools
        },
        "external_commands": [shlex.join(command) for command in plan.external_commands],
        "integration_setup": (
            {
                "google_workspace_client_target": str(plan.google_workspace_client_target),
                "google_workspace_services": list(plan.spec.google_workspace_services),
                "google_workspace_readonly": plan.spec.google_workspace_readonly,
                "google_workspace_authentication": f"pending in {plan.spec.host}",
            }
            if plan.google_workspace_client_target is not None
            else {}
        ),
    }


def show_plan(plan: InstallationPlan, *, interactive: bool, no_color: bool) -> bool:
    payload = plan_payload(plan)
    if not interactive:
        print(yaml.safe_dump(payload, sort_keys=False).rstrip())
        return True
    import questionary
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax

    console = Console(no_color=no_color)
    rendered = yaml.safe_dump(payload, sort_keys=False).rstrip()
    console.print(Panel(Syntax(rendered, "yaml"), title="Installation plan", border_style="cyan"))
    if plan.external_commands or plan.google_workspace_client_target is not None:
        console.print(
            "External commands and integration setup may modify user-level configuration "
            "outside the destination.",
            style="yellow",
        )
    return bool(_ask(questionary.confirm("Create this harness?", default=False)))


def show_success(plan: InstallationPlan, *, no_color: bool) -> None:
    capabilities = "\n".join(
        (
            "Examples of what this harness can do (not a complete list):",
            "  • Follow the configured identity, goal, role, language, and tone.",
            "  • Plan and execute work through explicit allow / ask / deny boundaries.",
            "  • Use selected skills and official documentation integrations.",
            "  • Protect denied paths and record redacted audit metadata.",
            "  • Add project folders through the manage-project-scope skill.",
            "  • Map short slash commands to installed skills with map-skill-command.",
            "  • Audit skills and import only genuinely new skills from trusted sources.",
        )
    )
    try:
        from rich.console import Console
        from rich.panel import Panel
    except ImportError:
        print(f"Created agent harness at {plan.spec.destination}\n\n{capabilities}")
        print(
            "\nHere are some things you can try:"
            '\n  "Add /path/to/project to this harness with read-write access."'
        )
        print('  "Map /scope to the manage-project-scope skill."')
        print('  "Audit this skill ZIP before importing it."')
        print('  "Import new skills from the latest stable agent-template release."')
        print("These are examples, not required next steps or the limit of the harness.")
        return
    console = Console(no_color=no_color)
    next_steps = [f"cd {shlex.quote(str(plan.spec.destination))}"]
    if not plan.spec.install_dependencies:
        sync = f"uv sync --python {plan.spec.python_version}"
        if plan.spec.development_tools:
            sync += " --extra dev"
        next_steps.extend((sync, "uv run python scripts/validate_harness.py"))
    if plan.launch_command:
        if shutil.which(plan.launch_command):
            next_steps.append(f"{plan.launch_command}  # authenticate on first launch if needed")
        else:
            next_steps.append(
                f"# Install and authenticate {HOST_LABELS[plan.spec.host]}, then run {plan.launch_command}"
            )
    if plan.integrations:
        next_steps.append("# Complete integration setup in docs/integrations.md")
    if "google-workspace" in plan.integrations:
        services = ", ".join(plan.spec.google_workspace_services)
        next_steps.append(
            "# Call a Google Workspace read tool and complete browser authentication: " + services
        )
    console.print(
        Panel(
            "Harness created successfully.\n\n"
            + capabilities
            + "\n\nRequired setup / launch steps:\n"
            + "\n".join(f"  {step}" for step in next_steps)
            + '\n\nHere are some things you can try:\n  "Add '
            '/path/to/project to this harness with read-write access."\n  "Map /scope to '
            'the manage-project-scope skill."\n  "Audit this skill ZIP before importing it."'
            '\n  "Import new skills from the latest stable agent-template release."'
            "\n\nThese illustrate a few of many capabilities; "
            "they are not required next steps. The harness can also plan, edit, review, "
            "validate, and document work within its configured skills and policies.",
            title="Ready",
            border_style="green",
        )
    )


def bootstrap_atlassian_rovo(plan: InstallationPlan, *, interactive: bool, no_color: bool) -> bool:
    """Offer Antigravity users a one-time Rovo OAuth bootstrap after generation."""
    if (
        not interactive
        or plan.spec.host != "antigravity"
        or "atlassian-rovo" not in plan.integrations
    ):
        return False

    import questionary
    from rich.console import Console

    console = Console(no_color=no_color)
    console.print("\n[bold cyan]Atlassian Rovo authentication[/bold cyan]")
    console.print(
        "Antigravity needs a one-time localhost OAuth bootstrap before it can use Jira or "
        "Confluence. Your browser will open so you can review and approve access.",
        style="dim",
    )
    if not _ask(questionary.confirm("Authenticate Atlassian Rovo now?", default=True)):
        console.print(
            "Authentication remains pending. Follow docs/integrations.md before using Rovo.",
            style="yellow",
        )
        return False
    try:
        _, npx_command = antigravity_rovo_runtime()
        command = [
            *npx_command,
            "-p",
            "mcp-remote@latest",
            "mcp-remote-client",
            ATLASSIAN_ROVO_ENDPOINT,
        ]
        subprocess.run(command, cwd=plan.spec.destination, check=True)
    except (InitializerError, OSError, subprocess.CalledProcessError) as exc:
        console.print(
            "The harness was created, but Atlassian authentication did not complete. "
            f"Retry the command documented in docs/integrations.md. ({exc})",
            style="yellow",
        )
        return False

    receipt_path = plan.spec.destination / ".agent-harness" / "installation.yaml"
    receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    for integration in receipt.get("integrations", []):
        if integration.get("id") == "atlassian-rovo":
            integration["authentication"] = "verified"
    receipt_path.write_text(yaml.safe_dump(receipt, sort_keys=False), encoding="utf-8")
    console.print("Atlassian Rovo authentication completed.", style="green")
    return True


def main() -> int:
    args = parser().parse_args()
    require_initializer_prerequisites()
    interactive = args.wizard or args.destination is None
    if interactive and not sys.stdin.isatty():
        raise InitializerError("The wizard requires an interactive terminal")
    spec = wizard_spec(ROOT, no_color=args.no_color) if interactive else cli_spec(args)
    plan = resolve_plan(ROOT, spec)
    approved = show_plan(plan, interactive=interactive, no_color=args.no_color)
    if not approved:
        print("Initialization cancelled. No destination was created.")
        return 0
    if args.dry_run:
        print("Dry run complete. No changes were made.")
        return 0
    if (
        (plan.external_commands or plan.google_workspace_client_target is not None)
        and not interactive
        and not args.yes
    ):
        raise InitializerError("External commands or user-level integration setup require --yes")
    execute_plan(ROOT, plan)
    bootstrap_atlassian_rovo(plan, interactive=interactive, no_color=args.no_color)
    show_success(plan, no_color=args.no_color)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InitializerError, KeyboardInterrupt) as exc:
        message = str(exc).strip() or "Initialization cancelled"
        print(f"ERROR: {message}", file=sys.stderr)
        raise SystemExit(1) from exc
