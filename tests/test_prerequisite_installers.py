from __future__ import annotations

import os
import shutil
import stat
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "scripts" / "install_prerequisites_macos.sh"
UBUNTU = ROOT / "scripts" / "install_prerequisites_ubuntu.sh"
WINDOWS = ROOT / "scripts" / "install_prerequisites_windows.ps1"


class PrerequisiteInstallerTests(unittest.TestCase):
    def test_installers_cover_every_initializer_prerequisite(self) -> None:
        expected = ("git", "python", "uv", "gitleaks", "node", "npx")
        for installer in (MACOS, UBUNTU, WINDOWS):
            content = installer.read_text(encoding="utf-8").lower()
            with self.subTest(installer=installer.name):
                for command in expected:
                    self.assertIn(command, content)

    def test_posix_installers_are_executable(self) -> None:
        for installer in (MACOS, UBUNTU):
            with self.subTest(installer=installer.name):
                self.assertTrue(installer.stat().st_mode & stat.S_IXUSR)

    def test_ubuntu_uses_current_gitleaks_asset_names_and_checksums(self) -> None:
        content = UBUNTU.read_text(encoding="utf-8")
        self.assertIn('GITLEAKS_VERSION="8.30.1"', content)
        self.assertIn('amd64) gitleaks_arch="x64"', content)
        self.assertIn('arm64) gitleaks_arch="arm64"', content)
        self.assertIn("sha256sum --check --strict", content)

    def test_windows_uses_exact_winget_packages(self) -> None:
        content = WINDOWS.read_text(encoding="utf-8")
        for package in (
            "Git.Git",
            "Python.Python.3.13",
            "astral-sh.uv",
            "Gitleaks.Gitleaks",
            "OpenJS.NodeJS.LTS",
        ):
            self.assertIn(package, content)

    @unittest.skipUnless(shutil.which("bash"), "Bash is required for syntax validation")
    def test_posix_installers_have_valid_bash_syntax(self) -> None:
        for installer in (MACOS, UBUNTU):
            with self.subTest(installer=installer.name):
                subprocess.run(["bash", "-n", str(installer)], check=True)

    @unittest.skipUnless(os.name == "nt", "PowerShell parser validation runs on Windows")
    def test_windows_installer_has_valid_powershell_syntax(self) -> None:
        command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{WINDOWS}', [ref]$tokens, [ref]$errors) > $null; "
            "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True)

    def test_documentation_links_all_installers(self) -> None:
        documentation = (ROOT / "docs" / "prerequisites.md").read_text(encoding="utf-8")
        for installer in (MACOS, UBUNTU, WINDOWS):
            self.assertIn(installer.name, documentation)


if __name__ == "__main__":
    unittest.main()
