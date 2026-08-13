---
name: manage-project-scope
description: Add an existing project folder to or inspect a generated agent harness's configured read or read-write scope in config/policies.yaml. Use when the user asks to add, attach, include, authorize, or make a folder or repository available to the harness, or asks why the harness cannot access a project path.
---

# Manage project scope

1. Locate the harness root containing `config/policies.yaml` and resolve the requested folder to
   its canonical absolute path.
2. Verify that the target exists and is a directory. Never add `/`, the user's home directory,
   the harness root again, a credential directory, or a path broader than the requested project.
3. Determine the minimum access needed:
   - use `read` for inspection, search, review, or reference material;
   - use `read-write` only when the user wants the agent to modify the project;
   - ask which one is intended when the request does not establish it.
4. Present the exact path and access level before changing policy. Treat this edit as a scope
   expansion that requires the host's normal write approval.
5. Change to this skill directory and run its bundled helper:

   ```bash
   python3 scripts/update_scope.py --root /path/to/harness --path /path/to/project --access read
   ```

   Use `--access read-write` when write access was explicitly established.
6. Validate the result with `python3 scripts/validate_harness.py`. If project dependencies are
   available only through uv, use `uv run python scripts/validate_harness.py` instead.
7. Report the resulting read and write scope and remind the user that `denied_paths` still wins.

`config/policies.yaml` controls the portable harness guardrail only. It cannot grant filesystem
access that the selected host's sandbox or workspace configuration denies. If native access is
still blocked, explain that separate boundary and ask before changing host configuration or
relaunching from a broader workspace. Never weaken native protections automatically.
