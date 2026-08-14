# Runbook: External integration lifecycle

## Purpose

Connect, verify, operate, troubleshoot, and revoke an optional external integration
without storing credentials in the project or silently broadening authority.

## Scope and risk

Applies to official remote MCP servers, provider CLIs, and host plugins selected by the
initializer. Integrations can expose confidential data or externally visible writes.

## Prerequisites and approvals

- Identify the service owner, tenant or site, official setup source, and supported host.
- Review requested scopes, data classes, write-capable tools, retention, and revoke path.
- Obtain authorization for account connection and any write test.
- Keep tokens in the host or provider credential store, never repository files.

## Procedure

1. Confirm the integration entry and official endpoint still match current provider docs.
2. Generate or inspect the host-native configuration and confirm startup is optional.
3. Authenticate through the host or provider using the narrowest suitable account and
   scopes.
4. Run a bounded read-only operation against a known non-sensitive record.
5. Inspect available tools and confirm write-capable operations use the documented
   approval behavior. Perform no write solely for setup unless explicitly authorized.
6. Record the operator, date, tenant, tested read, approval behavior, and authentication
   status without credential material.

## Validation

- The host starts when the integration is unavailable.
- The bounded read returns the expected tenant and record.
- A write-capable tool prompts according to policy before any external change.
- Project scans find no tokens, authorization headers, or private credential files.

## Rollback

Disable or remove the host-native entry, revoke the grant in the provider, remove local
cached authorization through the host, and rerun the no-credential scan. Preserve only
redacted operational evidence required by policy.

## Troubleshooting

Check endpoint freshness, tenant selection, account permissions, OAuth scopes, host logs,
network policy, and provider status. Do not paste tokens into config as a workaround.

## References

Use the integration's `official_source` from `config/integrations.yaml`.
