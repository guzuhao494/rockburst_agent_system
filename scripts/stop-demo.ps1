Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "==> $Message" -ForegroundColor Cyan
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
$BackendPidPath = Join-Path $RuntimeDir "backend.pid"
$FrontendPidPath = Join-Path $RuntimeDir "frontend.pid"

if (Test-Path -LiteralPath $FrontendPidPath) {
    $FrontendPid = (Get-Content -LiteralPath $FrontendPidPath -Raw).Trim()
    if ($FrontendPid) {
        Write-Step "Stopping frontend preview"
        Stop-Process -Id ([int]$FrontendPid) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $FrontendPidPath -Force -ErrorAction SilentlyContinue
}
else {
    Write-Step "No frontend preview PID file found"
}

if (Test-Path -LiteralPath $BackendPidPath) {
    Write-Step "Stopping backend API"
    $BackendPidWsl = Convert-ToWslPath -Path $BackendPidPath
    $StopCommand = @'
if [ -f '{0}' ]; then kill $(cat '{0}') 2>/dev/null || true; rm -f '{0}'; fi
'@
    $StopCommand = $StopCommand -f $BackendPidWsl
    & wsl -e bash -lc $StopCommand | Out-Null
}
else {
    Write-Step "No backend PID file found"
}

Write-Host ""
Write-Host "Demo environment stopped." -ForegroundColor Green
