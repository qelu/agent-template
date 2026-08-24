[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") {
    throw "This installer supports Windows only."
}
if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
    throw "WinGet is required. Install or update Microsoft App Installer, then retry."
}

$packages = @(
    "Git.Git",
    "Python.Python.3.13",
    "astral-sh.uv",
    "Gitleaks.Gitleaks",
    "OpenJS.NodeJS.LTS"
)

foreach ($package in $packages) {
    $installed = (& winget.exe list --exact --id $package --source winget `
        --accept-source-agreements | Out-String) -match [regex]::Escape($package)
    if ($installed) {
        Write-Host "$package is already installed."
        continue
    }
    Write-Host "Installing $package..."
    & winget.exe install --exact --id $package --source winget --silent `
        --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "WinGet could not install $package (exit code $LASTEXITCODE)."
    }
}

$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

$commands = @("git", "py", "uv", "gitleaks", "node", "npx")
foreach ($command in $commands) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command is unavailable on PATH after installation. Open a new PowerShell window and retry verification."
    }
}

& git --version
& py -3.13 --version
& uv --version
& gitleaks version
& node --version
& npx --version
Write-Host "Agent Template prerequisites are ready on Windows." -ForegroundColor Green
