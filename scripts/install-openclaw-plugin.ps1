Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$PluginDir = Join-Path $RepoRoot "plugins\\openclaw-rockburst-ops"

if (-not (Get-Command openclaw -ErrorAction SilentlyContinue)) {
    throw "OpenClaw CLI is not installed or not in PATH. Install OpenClaw first, then rerun this script."
}

if (-not (Test-Path -LiteralPath $PluginDir)) {
    throw "Plugin directory not found: $PluginDir"
}

Write-Step "Installing plugin dependencies"
Push-Location $PluginDir
try {
    & npm.cmd install
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed in $PluginDir"
    }
}
finally {
    Pop-Location
}

Write-Step "Installing local OpenClaw plugin"
& openclaw plugins install $PluginDir
if ($LASTEXITCODE -ne 0) {
    throw "openclaw plugins install failed."
}

Write-Step "Enabling plugin"
& openclaw plugins enable rockburst-ops
if ($LASTEXITCODE -ne 0) {
    throw "openclaw plugins enable failed."
}

Write-Step "Restarting gateway"
& openclaw gateway restart
if ($LASTEXITCODE -ne 0) {
    throw "openclaw gateway restart failed."
}

Write-Host ""
Write-Host "OpenClaw plugin is ready." -ForegroundColor Green
Write-Host "Plugin dir: $PluginDir"
Write-Host "Suggested config example: $RepoRoot\\openclaw\\openclaw.example.json5"
