---
name: import-external-skill
description: Safely audit and import a genuinely new skill into a generated harness from a local folder, local ZIP, checksum-pinned archive URL, or Git repository pinned to a commit or tag. Use when the user explicitly asks to install or import a skill from outside the agent template. Never update, merge, replace, or delete an existing local skill.
---

# Import External Skill

Use this skill only after an explicit import request. The request authorizes installation of the
named new skill, so do not add a redundant confirmation prompt.

1. Locate this skill and `skill-auditor` through `config/capabilities.yaml`.
2. Select exactly one immutable source:
   - `--source /path/to/skill` for a local folder;
   - `--source /path/to/skill.zip` for a local ZIP;
   - `--source https://example/skill.zip --sha256 <digest>` for a remote ZIP;
   - `--git-url <repository> --git-ref <40-char-commit-or-tag:name>` for Git.
3. Add `--skill <id>` when the source contains multiple skill folders.
4. Run the bundled importer, using the harness root containing `config/capabilities.yaml`:

   ```bash
   python3 /path/to/import-external-skill/scripts/import_skill.py \
     --root /path/to/harness --source /path/to/skill.zip
   ```

5. Report the immutable source identity, audit verdict, imported ID, validation result, and any
   preserved collision.

If the capability ID or destination directory already exists, preserve it without comparing,
updating, merging, or overwriting anything. Updating an existing skill is a separate workflow.
Remote archives require an expected SHA-256. Git branches are mutable and therefore rejected;
use a full commit or `tag:<name>`.
