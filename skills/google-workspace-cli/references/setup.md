# gws setup and support boundary

- Authoritative project: https://github.com/googleworkspace/cli
- Version installed by this template when `gws` is missing: `0.22.5`
- Template install command: `npm install --global @googleworkspace/cli@0.22.5`
- The repository is maintained in the Google Workspace organization but explicitly
  states that `gws` is not an officially supported Google product and is pre-1.0.
- The `gws mcp` command was removed in version 0.8.0. Use the CLI and its skill; do not
  configure a nonexistent current MCP server.

## Authentication

The official project documents these interactive flows:

1. `gws auth setup` when `gcloud` is installed and the user authorizes Cloud project
   creation, API enablement, and login.
2. `gws auth login -s drive,gmail,calendar` or a narrower service list when the project
   is already configured.
3. Manual Desktop OAuth client setup when automated setup is inappropriate.

Review requested scopes before consent. Unverified OAuth applications can have scope
limits, so select only the services required. Do not export credentials into the
project, commit them, or place them in a tracked `.env` file.

## Smoke test

Use a bounded read against non-sensitive data, such as a small Drive file listing or
calendar listing, then inspect the returned account and resource. Test a write only when
the user explicitly authorizes that external change; use `--dry-run` where supported.

## Removal

Remove the CLI using the same package manager that installed it, revoke the application's
Google Account grant, and clear provider-designated local authorization through the
current official instructions. Do not delete broad configuration directories without
resolving the exact files and confirming ownership.
