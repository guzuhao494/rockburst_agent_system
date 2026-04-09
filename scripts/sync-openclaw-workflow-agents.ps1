Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Target,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [object]$Value
    )

    $property = $Target.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $Target | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
    else {
        $property.Value = $Value
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$OpenClawConfigPath = Join-Path $env:USERPROFILE ".openclaw\openclaw.json"

if (-not (Test-Path -LiteralPath $OpenClawConfigPath)) {
    throw "OpenClaw config not found: $OpenClawConfigPath"
}

$config = Get-Content -LiteralPath $OpenClawConfigPath -Raw | ConvertFrom-Json
if ($null -eq $config.agents) {
    throw "Invalid OpenClaw config: missing agents block."
}
if ($null -eq $config.agents.list) {
    throw "Invalid OpenClaw config: missing agents.list block."
}

$defaultModel = $config.agents.defaults.model.primary
if (-not $defaultModel) {
    $defaultModel = "openai-codex/gpt-5.4"
}

$agentSpecs = @(
    [pscustomobject]@{ Id = "rockburst-supervisor"; Name = "rockburst-supervisor"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\supervisor") },
    [pscustomobject]@{ Id = "rockburst-ingest-intake"; Name = "rockburst-ingest-intake"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\ingest-intake") },
    [pscustomobject]@{ Id = "rockburst-data-quality"; Name = "rockburst-data-quality"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\data-quality") },
    [pscustomobject]@{ Id = "rockburst-risk-assessment"; Name = "rockburst-risk-assessment"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\risk-assessment") },
    [pscustomobject]@{ Id = "rockburst-alert-explanation"; Name = "rockburst-alert-explanation"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\alert-explanation") },
    [pscustomobject]@{ Id = "rockburst-action-planning"; Name = "rockburst-action-planning"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\action-planning") },
    [pscustomobject]@{ Id = "rockburst-work-order-coordination"; Name = "rockburst-work-order-coordination"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\work-order-coordination") },
    [pscustomobject]@{ Id = "rockburst-effectiveness-verification"; Name = "rockburst-effectiveness-verification"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\effectiveness-verification") },
    [pscustomobject]@{ Id = "rockburst-supervisor-finalize"; Name = "rockburst-supervisor-finalize"; Workspace = (Join-Path $RepoRoot "openclaw\workflow-agents\supervisor-finalize") }
)

$agentList = New-Object System.Collections.ArrayList
foreach ($entry in $config.agents.list) {
    [void]$agentList.Add($entry)
}

foreach ($spec in $agentSpecs) {
    $agentsFile = Join-Path $spec.Workspace "AGENTS.md"
    if (-not (Test-Path -LiteralPath $agentsFile)) {
        throw "Missing workflow agent workspace file: $agentsFile"
    }

    $existing = $null
    foreach ($entry in $agentList) {
        if ($entry.id -eq $spec.Id) {
            $existing = $entry
            break
        }
    }

    if ($null -eq $existing) {
        $existing = [pscustomobject]@{
            id = $spec.Id
            name = $spec.Name
            workspace = $spec.Workspace
            model = $defaultModel
        }
        [void]$agentList.Add($existing)
    }
    else {
        Set-ObjectProperty -Target $existing -Name "name" -Value $spec.Name
        Set-ObjectProperty -Target $existing -Name "workspace" -Value $spec.Workspace
        Set-ObjectProperty -Target $existing -Name "model" -Value $defaultModel
    }
}

$config.agents.list = @($agentList)
$config.meta.lastTouchedAt = [DateTime]::UtcNow.ToString("o")

$json = $config | ConvertTo-Json -Depth 100
Set-Content -LiteralPath $OpenClawConfigPath -Value $json -Encoding utf8

Write-Host "OpenClaw workflow agents synced." -ForegroundColor Green
foreach ($spec in $agentSpecs) {
    Write-Host ("- {0}" -f $spec.Id)
}
