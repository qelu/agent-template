# Prerequisite installation

The initializer requires Git, Python 3.11 or newer, `uv`, Gitleaks, Node.js, and
`npx`. The repository includes rerunnable installers for its three supported
operator platforms. Review a script before running it because package installation
changes system or user-level state and downloads software from external sources.

## macOS

The macOS installer uses Homebrew. If Homebrew is missing, the script stops unless
`--yes` explicitly permits downloading and running Homebrew's official installer.

```bash
./scripts/install_prerequisites_macos.sh
```

On a new Mac without Homebrew, review [Homebrew](https://brew.sh) and run:

```bash
./scripts/install_prerequisites_macos.sh --yes
```

## Ubuntu 24.04

The Ubuntu installer uses `apt` for system packages, the verified OpenJS Node.js
Snap on the Node 24 LTS channel, `pipx` for `uv`, and a checksum-verified official
Gitleaks release archive. It supports `amd64` and `arm64`.

```bash
./scripts/install_prerequisites_ubuntu.sh
```

The script intentionally rejects other Ubuntu releases rather than assuming their
package and Python versions are compatible.

## Windows

Run PowerShell normally; WinGet will request elevation if an installer needs it.
WinGet is supplied by Microsoft's App Installer on supported Windows versions.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_prerequisites_windows.ps1
```

The Windows script installs any missing exact WinGet packages for Git, Python
3.13, `uv`, Gitleaks, and Node.js LTS, then refreshes the current process's `PATH`.

## Verification

Every script finishes by verifying all required commands. You can repeat the checks
manually:

```text
git --version
python --version       # use python3 on Ubuntu or python3.13 on macOS
uv --version
gitleaks version
node --version
npx --version
```
