---
name: import-template-skills
description: Manually discover, audit, and import only new skills added to a tagged agent-template release after a harness was generated. Use when the user explicitly asks to check a stable template release for new skills or import newly available template skills. Never update or compare an installed skill, and never run automatically or on a schedule.
---

# Import Template Skills

Use this skill only when the user explicitly requests a check or import. It never runs in the
background.

1. Locate this skill, `import-external-skill`, and `skill-auditor` through
   `config/capabilities.yaml`.
2. Run the bundled helper against the harness root:

   ```bash
   python3 /path/to/import-template-skills/scripts/import_from_release.py \
     --root /path/to/harness --release latest
   ```

3. Use only stable tagged releases. Pass an exact tag to `--release` when requested. Never import
   from `main` or another branch.
4. Import each active upstream skill whose capability ID and destination directory are both absent
   locally. Audit every candidate before installation and validate the harness after each import.
5. Preserve every existing ID or destination without comparing contents or proposing an update.
6. Report the release tag and commit, imported skills, preserved skills, rejected candidates, and
   final validation state.

Checking and importing are separate user intents: use `--check` for discovery only. An explicit
import request needs no second confirmation.
