#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/install_prerequisites_macos.sh [--yes]

Install and verify the prerequisites required by the Agent Template initializer.
When Homebrew is absent, --yes permits bootstrapping it with Homebrew's official
installer. Without --yes, the script stops before changing package-manager state.
EOF
}

approve_homebrew=false
case "${1:-}" in
  "") ;;
  --yes) approve_homebrew=true ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This installer supports macOS only." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  if [[ "$approve_homebrew" != true ]]; then
    echo "ERROR: Homebrew is required but is not installed." >&2
    echo "Review https://brew.sh and rerun this script with --yes to use its official installer." >&2
    exit 1
  fi
  temporary_installer="$(mktemp)"
  trap 'rm -f "$temporary_installer"' EXIT
  curl --proto '=https' --tlsv1.2 -fsSL \
    https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh \
    -o "$temporary_installer"
  NONINTERACTIVE=1 /bin/bash "$temporary_installer"
fi

if [[ -x /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -x /usr/local/bin/brew ]]; then
  eval "$(/usr/local/bin/brew shellenv)"
fi

brew install git python@3.13 uv gitleaks node

for command in git python3.13 uv gitleaks node npx; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: $command is unavailable on PATH after installation." >&2
    exit 1
  fi
done

git --version
python3.13 --version
uv --version
gitleaks version
node --version
npx --version
echo "Agent Template prerequisites are ready on macOS."
