#!/usr/bin/env bash

set -euo pipefail

GITLEAKS_VERSION="8.30.1"
NODE_CHANNEL="24/stable"

if [[ ! -r /etc/os-release ]]; then
  echo "ERROR: Cannot identify this operating system." >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "ERROR: This installer supports Ubuntu 24.04 only." >&2
  exit 1
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl git pipx python3 python3-venv snapd tar

if snap list node >/dev/null 2>&1; then
  sudo snap refresh node --channel="$NODE_CHANNEL"
else
  sudo snap install node --classic --channel="$NODE_CHANNEL"
fi
export PATH="$HOME/.local/bin:/snap/bin:$PATH"

if pipx list --short 2>/dev/null | grep -Eq '^uv([[:space:]]|$)'; then
  pipx upgrade uv
else
  pipx install uv
fi

case "$(dpkg --print-architecture)" in
  amd64) gitleaks_arch="x64" ;;
  arm64) gitleaks_arch="arm64" ;;
  *)
    echo "ERROR: Gitleaks is not packaged by this script for $(dpkg --print-architecture)." >&2
    exit 1
    ;;
esac

gitleaks_archive="gitleaks_${GITLEAKS_VERSION}_linux_${gitleaks_arch}.tar.gz"
gitleaks_base="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}"
temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT

curl --proto '=https' --tlsv1.2 -fsSL \
  "$gitleaks_base/$gitleaks_archive" \
  -o "$temporary_directory/$gitleaks_archive"
curl --proto '=https' --tlsv1.2 -fsSL \
  "$gitleaks_base/gitleaks_${GITLEAKS_VERSION}_checksums.txt" \
  -o "$temporary_directory/checksums.txt"
(
  cd "$temporary_directory"
  grep "  ${gitleaks_archive}$" checksums.txt | sha256sum --check --strict
  tar -xzf "$gitleaks_archive"
)
sudo install -m 0755 "$temporary_directory/gitleaks" /usr/local/bin/gitleaks

for command in git python3 uv gitleaks node npx; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: $command is unavailable on PATH after installation." >&2
    exit 1
  fi
done

git --version
python3 --version
uv --version
gitleaks version
node --version
npx --version
echo "Agent Template prerequisites are ready on Ubuntu 24.04."
