# Security policy

## Supported versions

Security fixes are applied to the latest release line. Before version 1.0,
interfaces may change between minor releases.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Earlier | No |

## Reporting a vulnerability

Please use GitHub's **Report a vulnerability** flow in the repository Security
tab. Do not open a public issue for an undisclosed vulnerability.

Include the affected version, a minimal reproduction, the impact, and any known
mitigation. You should receive an acknowledgement within three business days and
an initial assessment within seven business days. Timelines may vary because the
project is maintained on a best-effort basis.

Security reports may cover the host integration boundary, native hook and
permission configuration, initializer behavior, capability governance, or the
release supply chain.

## Security model

This project adds project-level instructions, native host settings, pre-tool
denials, and validation; it is not a model runtime or operating-system sandbox.
Deployments must still rely on the selected host for authentication, sandboxing,
and tool authorization, isolate credentials, review host permissions, and treat
model output and fetched content as untrusted input. Semantic plan approval is a
behavioral contract unless the host exposes a trustworthy approval event.
