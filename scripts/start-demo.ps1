param(
    [switch]$Build
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Ensure-Path {
    param(
        [string]$Path,
        [string]$Message
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw $Message
    }
}

function Test-Url {
    param(
        [string]$Url,
        [int]$TimeoutSec = 3
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        return $false
    }
}

function Wait-ForUrl {
    param(
        [string]$Url,
        [int]$Attempts = 30,
        [int]$DelayMs = 1000
    )

    for ($index = 0; $index -lt $Attempts; $index += 1) {
        if (Test-Url -Url $Url) {
            return $true
        }
        Start-Sleep -Milliseconds $DelayMs
    }

    return $false
}

function Convert-ToWslPath {
    param([string]$Path)

    $ResolvedPath = [System.IO.Path]::GetFullPath($Path)
    $DriveLetter = $ResolvedPath.Substring(0, 1).ToLowerInvariant()
    $Rest = $ResolvedPath.Substring(2).Replace("\", "/")
    return "/mnt/$DriveLetter$Rest"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$RuntimeDir = Join-Path $RepoRoot "runtime"
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$WorkflowRuntime = if ($env:APP_WORKFLOW_RUNTIME) { $env:APP_WORKFLOW_RUNTIME } else { "openclaw" }
$OpenClawThinking = if ($env:APP_OPENCLAW_THINKING) { $env:APP_OPENCLAW_THINKING } else { "off" }
$OpenClawTimeoutSeconds = if ($env:APP_OPENCLAW_TIMEOUT_SECONDS) { $env:APP_OPENCLAW_TIMEOUT_SECONDS } else { "180" }
$AgentMonitorEnabled = if ($env:APP_AGENT_MONITOR_ENABLED) { $env:APP_AGENT_MONITOR_ENABLED } else { "true" }
$AgentMonitorIntervalSeconds = if ($env:APP_AGENT_MONITOR_INTERVAL_SECONDS) { $env:APP_AGENT_MONITOR_INTERVAL_SECONDS } else { "20" }

$BackendHealthUrl = "http://127.0.0.1:8000/health"
$FrontendUrl = "http://127.0.0.1:4173"

$BackendPidPath = Join-Path $RuntimeDir "backend.pid"
$BackendLogPath = Join-Path $RuntimeDir "backend.log"
$FrontendPidPath = Join-Path $RuntimeDir "frontend.pid"
$FrontendStdoutPath = Join-Path $RuntimeDir "frontend.stdout.log"
$FrontendStderrPath = Join-Path $RuntimeDir "frontend.stderr.log"

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

Ensure-Path -Path (Join-Path $BackendDir ".venv") -Message "Missing backend/.venv. Install backend dependencies first."
Ensure-Path -Path (Join-Path $FrontendDir "node_modules") -Message "Missing frontend/node_modules. Install frontend dependencies first."

Write-Step "Syncing OpenClaw workflow agents"
& (Join-Path $ScriptDir "sync-openclaw-workflow-agents.ps1")

if ($Build -or -not (Test-Path -LiteralPath (Join-Path $FrontendDir "dist\\index.html"))) {
    Write-Step "Building frontend assets"
    Push-Location $FrontendDir
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed."
        }
    }
    finally {
        Pop-Location
    }
}

if (Test-Url -Url $BackendHealthUrl) {
    Write-Step "Backend already running, skip start"
}
else {
    Write-Step "Starting backend API"
    $BackendWslDir = Convert-ToWslPath -Path $BackendDir
    $BackendLogWsl = Convert-ToWslPath -Path $BackendLogPath
    $BackendPidWsl = Convert-ToWslPath -Path $BackendPidPath
    $BackendCommand = "set -euo pipefail; rm -f '{1}' '{2}'; cd '{0}'; export APP_WORKFLOW_RUNTIME='{3}'; export APP_OPENCLAW_THINKING='{4}'; export APP_OPENCLAW_TIMEOUT_SECONDS='{5}'; export APP_AGENT_MONITOR_ENABLED='{6}'; export APP_AGENT_MONITOR_INTERVAL_SECONDS='{7}'; . .venv/bin/activate; nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 > '{1}' 2>&1 < /dev/null & backend_pid=`$!; echo `$backend_pid > '{2}'; sleep 2"
    $BackendCommand = $BackendCommand -f $BackendWslDir, $BackendLogWsl, $BackendPidWsl, $WorkflowRuntime, $OpenClawThinking, $OpenClawTimeoutSeconds, $AgentMonitorEnabled, $AgentMonitorIntervalSeconds
    & wsl -e bash -lc $BackendCommand | Out-Null

    if (-not (Wait-ForUrl -Url $BackendHealthUrl)) {
        throw "Backend start failed. Check runtime/backend.log."
    }
}

if (Test-Url -Url $FrontendUrl) {
    Write-Step "Frontend preview already running, skip start"
}
else {
    Write-Step "Starting frontend preview"

    if (Test-Path -LiteralPath $FrontendPidPath) {
        Remove-Item -LiteralPath $FrontendPidPath -Force -ErrorAction SilentlyContinue
    }

    $FrontendProcess = Start-Process `
        -FilePath "npm.cmd" `
        -ArgumentList "run", "preview", "--", "--host", "127.0.0.1", "--port", "4173" `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendStdoutPath `
        -RedirectStandardError $FrontendStderrPath `
        -PassThru

    Set-Content -Path $FrontendPidPath -Value $FrontendProcess.Id -Encoding ascii

    if (-not (Wait-ForUrl -Url $FrontendUrl)) {
        throw "Frontend preview failed to start. Check runtime/frontend.stdout.log and runtime/frontend.stderr.log."
    }
}

Write-Host ""
Write-Host "Demo environment is ready." -ForegroundColor Green
Write-Host "Frontend: $FrontendUrl"
Write-Host "Backend docs: http://127.0.0.1:8000/docs"
Write-Host "Stop command: powershell -ExecutionPolicy Bypass -File .\\scripts\\stop-demo.ps1"
