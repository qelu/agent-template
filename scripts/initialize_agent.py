#!/usr/bin/env python3
"""Create and provision a governed agent harness through a terminal wizard or CLI."""

from __future__ import annotations

import argparse
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from harness.initializer import (  # noqa: E402
    DEFAULT_DOCUMENTATION_PROVIDER,
    DOCUMENTATION_PROVIDERS,
    HOSTS,
    InitializationSpec,
    InstallationPlan,
    InitializerError,
    capability_choices,
    execute_plan,
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
    "portable": "Portable — no host-specific entry point",
    "codex": "Codex",
    "claude-code": "Claude Code",
    "antigravity": "Antigravity CLI / Gemini CLI",
}


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
        python_version=args.python_version,
        install_dependencies=args.install,
        development_tools=args.dev_tools,
        security_tools=args.security_tools,
        install_host_tool=args.install_host_tool,
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
    defaults = load_initializer_config(source)["defaults"]

    destination = _ask(questionary.text("Destination", default="../my-agent"))
    name = _ask(questionary.text("Agent name"))
    agent_id = _ask(questionary.text("Agent ID", default=slug(name)))
    goal = _ask(questionary.text("Primary goal"))
    role = _ask(questionary.text("Agent role", default="assistant"))
    tone = _ask(questionary.text("Communication tone", default="clear and concise"))
    language = _ask(questionary.text("Language", default="en-US"))
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
                Choice(value.replace("-", " ").title(), value=value)
                for value in DOCUMENTATION_PROVIDERS
            ],
            default=docs_default,
        )
    )
    choices = capability_choices(source)
    required_choices = [choice for choice in choices if choice.required]
    optional_choices = [choice for choice in choices if not choice.required]
    console.print("\nRequired capabilities", style="bold cyan")
    for choice in required_choices:
        console.print(f"  [green]✓[/green] {choice.capability_id} [dim](locked)[/dim]")
    selected_optional: list[str] = []
    for capability_type in sorted({choice.capability_type for choice in optional_choices}):
        typed_choices = [
            choice for choice in optional_choices if choice.capability_type == capability_type
        ]
        selected_optional.extend(
            _ask(
                questionary.checkbox(
                    f"Optional {capability_type.replace('-', ' ').title()} capabilities",
                    choices=[
                        Choice(
                            f"{choice.capability_id} — {choice.description}",
                            value=choice.capability_id,
                            checked=True,
                        )
                        for choice in typed_choices
                    ],
                )
            )
        )
    selected = tuple([choice.capability_id for choice in required_choices] + selected_optional)
    python_version = _ask(
        questionary.select("Python", choices=["3.13", "3.12", "3.11"], default=defaults["python"])
    )
    install_dependencies = _ask(
        questionary.confirm("Create the uv environment and validate everything?", default=True)
    )
    development_tools = _ask(
        questionary.confirm(
            "Install Ruff, pytest, mypy, and pre-commit?",
            default=defaults["development_tools"],
        )
    )
    security_tools = _ask(
        questionary.confirm("Run Gitleaks validation?", default=defaults["security_tools"])
    )
    install_host_tool = False
    host_binary = {"codex": "codex", "claude-code": "claude", "antigravity": "agy"}.get(host)
    if host_binary:
        if not shutil.which(host_binary):
            if host == "antigravity":
                console.print(
                    "Antigravity CLI (`agy`) is not installed. Use Google's official installer "
                    "before running the generated harness.",
                    style="yellow",
                )
            else:
                install_host_tool = _ask(
                    questionary.confirm(
                        f"{host_binary} is not installed. Include its official global installation?",
                        default=False,
                    )
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
        python_version=python_version,
        install_dependencies=install_dependencies,
        development_tools=development_tools,
        security_tools=security_tools,
        install_host_tool=install_host_tool,
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
    if plan.external_commands:
        console.print(
            "The commands under external_commands modify tools outside the destination.",
            style="yellow",
        )
    return bool(_ask(questionary.confirm("Create this harness?", default=False)))


def show_success(plan: InstallationPlan, *, no_color: bool) -> None:
    try:
        from rich.console import Console
        from rich.panel import Panel
    except ImportError:
        print(f"Created agent harness at {plan.spec.destination}")
        return
    console = Console(no_color=no_color)
    next_steps = [f"cd {shlex.quote(str(plan.spec.destination))}"]
    if not plan.spec.install_dependencies:
        next_steps.extend(("uv sync --extra dev", "uv run python scripts/validate_harness.py"))
    if plan.launch_command:
        if shutil.which(plan.launch_command):
            next_steps.append(f"{plan.launch_command}  # authenticate on first launch if needed")
        else:
            next_steps.append(
                f"# Install and authenticate {HOST_LABELS[plan.spec.host]}, then run {plan.launch_command}"
            )
    console.print(
        Panel(
            "Harness created successfully.\n\n" + "\n".join(f"  {step}" for step in next_steps),
            title="Ready",
            border_style="green",
        )
    )


def main() -> int:
    args = parser().parse_args()
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
    if plan.external_commands and not interactive and not args.yes:
        raise InitializerError("External installation commands require --yes")
    execute_plan(ROOT, plan)
    show_success(plan, no_color=args.no_color)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InitializerError, KeyboardInterrupt) as exc:
        message = str(exc).strip() or "Initialization cancelled"
        print(f"ERROR: {message}", file=sys.stderr)
        raise SystemExit(1) from exc
