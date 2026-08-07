# Reusable AI Agent Template

This repository creates minimal, governed agent harnesses. The default output contains one agent contract, one canonical capability registry, executable configuration validation, four concise skills, extension scaffolding, and tests. Optional operational examples are kept in this source repository and are not copied into new agents.

## Create an agent

```bash
python3 scripts/initialize_agent.py --destination ../research-agent
```

The initializer prompts for name, identifier, mission, role, tone, and language. Every value can also be provided as a flag:

```bash
python3 scripts/initialize_agent.py \
  --destination ../research-agent \
  --name "Axiom" \
  --id axiom \
  --goal "Research technical questions and produce cited, reproducible answers." \
  --role "research and analysis partner" \
  --tone "clear, skeptical, and concise" \
  --language en-US
```

Validate the generated agent:

```bash
cd ../research-agent
python3 scripts/validate_repository.py
python3 -m unittest discover -s tests -v
```

## Minimal generated structure

```text
agent/
├── AGENT.md
└── config.yaml
config/
├── capabilities.yaml
├── context-routes.yaml
├── persona.yaml
├── policies.yaml
└── schemas/capability.schema.json
harness/
├── configuration.py
├── policy.py
└── registry.py
knowledge/
└── decisions/
scripts/
├── create_extension.py
├── initialize_agent.py
└── validate_repository.py
skills/
├── documentation-maintenance/
├── evidence-gathering/
├── safe-tool-use/
└── task-planning/
templates/
├── skill/
├── workflow/
├── adr-template.md
└── runbook-template.md
tests/
```

## Canonical configuration

- `agent/AGENT.md` is the always-loaded behavioral contract.
- `config/persona.yaml` is the only persona source.
- `config/policies.yaml` is the only authorization-policy source.
- `config/capabilities.yaml` is the only activation source.
- `config/schemas/capability.schema.json` is enforced by repository validation.

Every active or tested capability must have a real path and evaluation suite. New capabilities are scaffolded as `proposed` and cannot activate themselves.

## Create an extension

```bash
python3 scripts/create_extension.py --type skill --id summarize-evidence --name "Summarize Evidence"
python3 scripts/create_extension.py --type workflow --id weekly-review --name "Weekly Review"
python3 scripts/create_extension.py --type runbook --id restore-service --name "Restore Service"
```

Skills and workflows are registered as proposed capabilities. Runbooks are human-operable documents and are not capabilities.

## Optional examples

The source template includes `examples/mcp/` and `examples/runbooks/`. They are references only and are never copied by the initializer. Adopt them deliberately when a generated agent has a demonstrated need.

## Design rules

1. Keep one authoritative source for each setting.
2. Load only task-relevant skills and references.
3. Keep secrets and generated runtime data outside the repository.
4. Keep optional integrations disabled until a runtime can enforce their permissions.
5. Validate every machine-consumed contract.
6. Require human review before promoting proposed capabilities.
