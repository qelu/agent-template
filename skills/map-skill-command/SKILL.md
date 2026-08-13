---
name: map-skill-command
description: Create a project-level slash-command alias for an installed generated-harness skill. Use when a user asks to map, bind, alias, or expose a command such as /review to an existing skill, or wants a shorter command name for a skill.
---

# Map a skill command

1. Locate the generated harness root containing `.agent-harness/installation.yaml` and
   `config/capabilities.yaml`.
2. Identify the installed target skill and the requested command name. Normalize a leading `/`
   away, but do not otherwise guess or rename the command.
3. Confirm the command name, target skill, and intended purpose. Refuse built-in command names,
   an existing capability ID, an existing command path, or aliases that target themselves.
4. Read the `map-skill-command` entry in `config/capabilities.yaml`, resolve its registered
   `path` against the harness root, and run the bundled helper by absolute path:

   ```bash
   uv run python "/path/to/harness/<registered-skill-path>/scripts/map_command.py" \
     --root /path/to/harness \
     --command review \
     --skill evidence-gathering \
     --description "Review the requested change using direct evidence."
   ```

   Do not shorten this to `/path/to/harness/scripts/map_command.py`; that project-level file does
   not exist.

5. Run `uv run python scripts/validate_harness.py` from the harness root.
6. Report the created command and invocation syntax. The host exposes enabled skills in its
   command picker; Codex also supports explicit `$command-name` invocation.

The helper creates a small alias skill in the selected host's native skill directory and adds it
to `config/capabilities.yaml`. The alias loads the target skill instead of copying its instructions,
so later changes to the target remain authoritative. Mapping a command never grants additional
tool authority or bypasses `config/policies.yaml` and native host permissions.
