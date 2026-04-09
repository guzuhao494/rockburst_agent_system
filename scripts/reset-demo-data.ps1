Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Url {
    param(
        [string]$Url,
        [int]$TimeoutSec = 2
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$StopScript = Join-Path $ScriptDir "stop-demo.ps1"
$DataDir = Join-Path $RepoRoot "backend\data"
$UploadsDir = Join-Path $DataDir "uploads"
$RuntimeDir = Join-Path $RepoRoot "runtime"
$DbBase = Join-Path $DataDir "rockburst.db"
$DbCandidates = @(
    $DbBase,
    "$DbBase-shm",
    "$DbBase-wal"
)

if (
    (Test-Path -LiteralPath (Join-Path $RuntimeDir "backend.pid")) -or
    (Test-Path -LiteralPath (Join-Path $RuntimeDir "frontend.pid"))
) {
    Write-Step "Found PID files from demo scripts, stopping tracked services first"
    & powershell -ExecutionPolicy Bypass -File $StopScript
    Start-Sleep -Seconds 1
}

if (Test-Url -Url "http://127.0.0.1:8000/health") {
    throw "Backend is still running on http://127.0.0.1:8000. Stop it before resetting demo data."
}

Write-Step "Removing SQLite database files"
foreach ($Path in $DbCandidates) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
}

Write-Step "Clearing uploaded files"
if (Test-Path -LiteralPath $UploadsDir) {
    Get-ChildItem -LiteralPath $UploadsDir -Force | Remove-Item -Recurse -Force
}
else {
    New-Item -ItemType Directory -Path $UploadsDir -Force | Out-Null
}

Write-Step "Clearing runtime logs and PID files"
if (Test-Path -LiteralPath $RuntimeDir) {
    Get-ChildItem -LiteralPath $RuntimeDir -Force | Remove-Item -Recurse -Force
}

Write-Host ""
Write-Host "Demo data reset complete." -ForegroundColor Green
Write-Host "Next step: powershell -ExecutionPolicy Bypass -File .\\scripts\\start-demo.ps1"
