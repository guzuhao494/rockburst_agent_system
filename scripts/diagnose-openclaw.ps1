Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
}

function Get-OpenClawCommand {
    $cli = Get-Command openclaw -ErrorAction SilentlyContinue
    if ($cli) {
        return @($cli.Source)
    }

    $nodePath = "C:\developtool\node.exe"
    $entryPath = "C:\developtool\node_global\node_modules\openclaw\openclaw.mjs"
    if ((Test-Path -LiteralPath $nodePath) -and (Test-Path -LiteralPath $entryPath)) {
        return @($nodePath, $entryPath)
    }

    throw "OpenClaw CLI not found. Install it or add it to PATH first."
}

function Invoke-OpenClaw {
    param([string[]]$Arguments)

    $command = Get-OpenClawCommand
    if ($command.Count -eq 1) {
        return & $command[0] @Arguments
    }

    return & $command[0] $command[1] @Arguments
}

function Get-NodeExecutablePath {
    $command = Get-OpenClawCommand
    if ($command.Count -ge 2) {
        return $command[0]
    }

    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) {
        return $node.Source
    }

    return $null
}

function Test-SpecialUseIp {
    param([string]$IpAddress)

    if ($IpAddress -match ':') {
        return $IpAddress -match '^(?i:fc|fd)' -or $IpAddress -eq '::1'
    }

    $bytes = $IpAddress.Split('.')
    if ($bytes.Count -ne 4) {
        return $false
    }

    $first = [int]$bytes[0]
    $second = [int]$bytes[1]

    if ($first -eq 10 -or $first -eq 127) {
        return $true
    }
    if ($first -eq 172 -and $second -ge 16 -and $second -le 31) {
        return $true
    }
    if ($first -eq 192 -and $second -eq 168) {
        return $true
    }

    return $false
}

function Normalize-ProxyUrl {
    param([string]$Value)

    if (-not $Value) {
        return $null
    }

    $trimmed = $Value.Trim()
    if (-not $trimmed) {
        return $null
    }

    if ($trimmed -notmatch '^[a-zA-Z][a-zA-Z0-9+.-]*://') {
        $trimmed = "http://$trimmed"
    }

    try {
        return ([uri]$trimmed).AbsoluteUri.TrimEnd('/')
    } catch {
        return $null
    }
}

function Get-ProxyUrlsFromSetting {
    param([string]$ProxyServer)

    $values = New-Object System.Collections.Generic.List[string]
    if (-not $ProxyServer) {
        return @()
    }

    foreach ($segment in ($ProxyServer -split ';')) {
        $candidate = $segment.Trim()
        if (-not $candidate) {
            continue
        }
        if ($candidate.Contains('=')) {
            $candidate = ($candidate -split '=', 2)[1]
        }

        $normalized = Normalize-ProxyUrl -Value $candidate
        if ($normalized -and -not $values.Contains($normalized)) {
            $values.Add($normalized)
        }
    }

    return $values.ToArray()
}

function Get-CurrentProxyEnvironment {
    $proxyVars = [ordered]@{}
    foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NODE_USE_ENV_PROXY")) {
        $proxyVars[$name] = [Environment]::GetEnvironmentVariable($name)
    }
    return [pscustomobject]$proxyVars
}

function Get-OptionalPropertyValue {
    param(
        [object]$InputObject,
        [string]$Name
    )

    if (-not $InputObject) {
        return $null
    }

    $property = $InputObject.PSObject.Properties[$Name]
    if ($property) {
        return $property.Value
    }

    return $null
}

function Invoke-NodeFetchProbe {
    param(
        [string]$NodePath,
        [string]$Url,
        [hashtable]$EnvironmentOverrides = @{}
    )

    if (-not $NodePath) {
        return [pscustomobject]@{
            ok = $false
            skipped = $true
            reason = "Node executable not found."
        }
    }

    $previousValues = @{}
    foreach ($name in $EnvironmentOverrides.Keys) {
        $previousValues[$name] = [Environment]::GetEnvironmentVariable($name)
        [Environment]::SetEnvironmentVariable($name, $EnvironmentOverrides[$name])
    }

    try {
        $probeScript = @'
const url = process.argv[2];
try {
  const res = await fetch(url, { method: 'GET', signal: AbortSignal.timeout(8000) });
  console.log(JSON.stringify({ ok: res.ok, status: res.status, statusText: res.statusText }));
} catch (error) {
  console.log(JSON.stringify({
    ok: false,
    error: String(error),
    name: error?.name,
    message: error?.message,
    cause: error?.cause ? {
      code: error.cause.code,
      message: error.cause.message,
      errno: error.cause.errno,
      syscall: error.cause.syscall,
      address: error.cause.address,
      port: error.cause.port,
      hostname: error.cause.hostname
    } : null
  }));
  process.exitCode = 1;
}
'@
        $rawOutput = ($probeScript | & $NodePath - $Url) | Out-String
        $jsonStart = $rawOutput.IndexOf('{')
        if ($jsonStart -lt 0) {
            return [pscustomobject]@{
                ok = $false
                parseError = $true
                raw = $rawOutput.Trim()
            }
        }
        return ($rawOutput.Substring($jsonStart) | ConvertFrom-Json)
    }
    finally {
        foreach ($name in $EnvironmentOverrides.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previousValues[$name])
        }
    }
}

function Get-ProxyListenerStatus {
    param([string[]]$ProxyUrls)

    foreach ($proxyUrl in $ProxyUrls) {
        try {
            $proxyUri = [uri]$proxyUrl
        } catch {
            continue
        }

        $isLoopback =
            $proxyUri.Host -eq "127.0.0.1" -or
            $proxyUri.Host -eq "localhost" -or
            $proxyUri.Host -eq "::1"

        if (-not $isLoopback) {
            continue
        }

        $listener = Get-NetTCPConnection -State Listen -LocalPort $proxyUri.Port -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -in @("127.0.0.1", "0.0.0.0", "::1", "::") } |
            Select-Object -First 1

        if ($listener) {
            $processName = $null
            try {
                $processName = (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName
            } catch {
            }

            return [pscustomobject]@{
                url = $proxyUrl
                listening = $true
                owningProcess = $listener.OwningProcess
                processName = $processName
            }
        }

        return [pscustomobject]@{
            url = $proxyUrl
            listening = $false
            owningProcess = $null
            processName = $null
        }
    }

    return $null
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backendHealthUrl = "http://127.0.0.1:8000/health"
$nodePath = Get-NodeExecutablePath
$currentProxyEnv = Get-CurrentProxyEnvironment
$internetSettings = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction SilentlyContinue
$envProxyUrls = New-Object System.Collections.Generic.List[string]
foreach ($value in @($currentProxyEnv.HTTP_PROXY, $currentProxyEnv.HTTPS_PROXY, $currentProxyEnv.ALL_PROXY)) {
    $normalized = Normalize-ProxyUrl -Value $value
    if ($normalized -and -not $envProxyUrls.Contains($normalized)) {
        $envProxyUrls.Add($normalized)
    }
}
$registryProxyUrls = @()
if ($internetSettings -and $internetSettings.ProxyServer) {
    $registryProxyUrls = @(Get-ProxyUrlsFromSetting -ProxyServer $internetSettings.ProxyServer)
}
$allKnownProxyUrls = New-Object System.Collections.Generic.List[string]
foreach ($url in @($envProxyUrls.ToArray() + $registryProxyUrls)) {
    if ($url -and -not $allKnownProxyUrls.Contains($url)) {
        $allKnownProxyUrls.Add($url)
    }
}

Write-Section "OpenClaw CLI"
$versionOutput = Invoke-OpenClaw @("--version")
Write-Host $versionOutput

Write-Section "Configured Model"
$configuredModel = (Invoke-OpenClaw @("config", "get", "agents.defaults.model.primary") | Out-String).Trim()
if ($configuredModel) {
    Write-Host "agents.defaults.model.primary = $configuredModel"
} else {
    Write-Warning "No default model is configured."
}

Write-Section "Available Models"
$modelsRaw = Invoke-OpenClaw @("models", "list", "--json") | Out-String
$jsonStart = $modelsRaw.IndexOf('{')
if ($jsonStart -lt 0) {
    throw "Could not find JSON output in `openclaw models list --json`."
}
$modelsJson = $modelsRaw.Substring($jsonStart)
$models = $modelsJson | ConvertFrom-Json
Write-Host "Available model count: $($models.count)"
foreach ($model in $models.models) {
    $tags = if ($model.tags) { ($model.tags -join ", ") } else { "-" }
    Write-Host "- $($model.key) | available=$($model.available) | missing=$($model.missing) | tags=$tags"
}

Write-Section "Credential Sanity"
$openAiKey = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY")
$dashscopeKey = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY")
$openAiKeyUser = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY", "User")
$dashscopeKeyUser = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY", "User")
Write-Host "OPENAI_API_KEY set (process): $([bool]$openAiKey)"
Write-Host "OPENAI_API_KEY set (user): $([bool]$openAiKeyUser)"
Write-Host "DASHSCOPE_API_KEY set (process): $([bool]$dashscopeKey)"
Write-Host "DASHSCOPE_API_KEY set (user): $([bool]$dashscopeKeyUser)"
if ($openAiKey -and $dashscopeKey -and $openAiKey -eq $dashscopeKey) {
    Write-Warning "OPENAI_API_KEY and DASHSCOPE_API_KEY are identical. Do not reuse a DashScope token as an OpenAI key."
}
if ($openAiKey -and -not $openAiKeyUser) {
    Write-Warning "Current process still inherited OPENAI_API_KEY, but the user-level value is already cleared. New terminals should no longer receive it."
}

Write-Section "Proxy Check"
Write-Host "Current process proxy vars:"
foreach ($name in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NODE_USE_ENV_PROXY")) {
    $value = $currentProxyEnv.$name
    if ($value) {
        Write-Host "- $name = $value"
    } else {
        Write-Host "- $name = <not set>"
    }
}

if ($internetSettings) {
    $proxyEnable = Get-OptionalPropertyValue -InputObject $internetSettings -Name "ProxyEnable"
    $proxyServer = Get-OptionalPropertyValue -InputObject $internetSettings -Name "ProxyServer"
    $autoConfigUrl = Get-OptionalPropertyValue -InputObject $internetSettings -Name "AutoConfigURL"
    $autoDetect = Get-OptionalPropertyValue -InputObject $internetSettings -Name "AutoDetect"

    Write-Host "WinINET settings:"
    Write-Host "- ProxyEnable = $(if ($null -ne $proxyEnable) { $proxyEnable } else { '<not set>' })"
    Write-Host "- ProxyServer = $(if ($proxyServer) { $proxyServer } else { '<not set>' })"
    Write-Host "- AutoConfigURL = $(if ($autoConfigUrl) { $autoConfigUrl } else { '<not set>' })"
    Write-Host "- AutoDetect = $(if ($null -ne $autoDetect) { $autoDetect } else { '<not set>' })"
}

$proxyListener = Get-ProxyListenerStatus -ProxyUrls $allKnownProxyUrls.ToArray()
if ($proxyListener) {
    Write-Host "Detected local proxy listener:"
    Write-Host "- url = $($proxyListener.url)"
    Write-Host "- listening = $($proxyListener.listening)"
    if ($proxyListener.listening) {
        Write-Host "- process = $($proxyListener.processName) [$($proxyListener.owningProcess)]"
    }
} else {
    Write-Host "Detected local proxy listener: none"
}

Write-Section "Node Egress Probe"
$currentNodeProbe = Invoke-NodeFetchProbe -NodePath $nodePath -Url "https://chatgpt.com/"
$currentNodeProbeSkipped = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "skipped"
$currentNodeProbeOk = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "ok"
$currentNodeProbeReason = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "reason"
$currentNodeProbeStatus = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "status"
$currentNodeProbeStatusText = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "statusText"
$currentNodeProbeCause = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "cause"
$currentNodeProbeMessage = Get-OptionalPropertyValue -InputObject $currentNodeProbe -Name "message"
$currentNodeProbeReachedEndpoint = $null -ne $currentNodeProbeStatus
if ($currentNodeProbeSkipped) {
    Write-Warning $currentNodeProbeReason
} elseif ($currentNodeProbeReachedEndpoint) {
    Write-Host "Current env Node fetch reached remote endpoint: status=$currentNodeProbeStatus $currentNodeProbeStatusText"
} else {
    $currentCause = if ($currentNodeProbeCause) { Get-OptionalPropertyValue -InputObject $currentNodeProbeCause -Name "message" } else { $currentNodeProbeMessage }
    Write-Warning "Current env Node fetch failed: $currentCause"
}

$hasProxyEnv = [bool]($currentProxyEnv.HTTP_PROXY -or $currentProxyEnv.HTTPS_PROXY -or $currentProxyEnv.ALL_PROXY)
$suggestedProxy = $null
if (-not $hasProxyEnv -and @($registryProxyUrls).Count -gt 0) {
    $suggestedProxy = $registryProxyUrls[0]
}

if ($suggestedProxy) {
    $proxyProbe = Invoke-NodeFetchProbe -NodePath $nodePath -Url "https://chatgpt.com/" -EnvironmentOverrides @{
        HTTP_PROXY = $suggestedProxy
        HTTPS_PROXY = $suggestedProxy
        ALL_PROXY = $suggestedProxy
        NODE_USE_ENV_PROXY = "1"
    }

    $proxyProbeOk = Get-OptionalPropertyValue -InputObject $proxyProbe -Name "ok"
    $proxyProbeStatus = Get-OptionalPropertyValue -InputObject $proxyProbe -Name "status"
    $proxyProbeStatusText = Get-OptionalPropertyValue -InputObject $proxyProbe -Name "statusText"
    $proxyProbeCause = Get-OptionalPropertyValue -InputObject $proxyProbe -Name "cause"
    $proxyProbeMessage = Get-OptionalPropertyValue -InputObject $proxyProbe -Name "message"
    $proxyProbeReachedEndpoint = $null -ne $proxyProbeStatus

    if ($proxyProbeReachedEndpoint) {
        Write-Host "Detected proxy Node fetch reached remote endpoint: status=$proxyProbeStatus $proxyProbeStatusText via $suggestedProxy"
    } else {
        $proxyCause = if ($proxyProbeCause) { Get-OptionalPropertyValue -InputObject $proxyProbeCause -Name "message" } else { $proxyProbeMessage }
        Write-Warning "Detected proxy Node fetch still failed via $suggestedProxy : $proxyCause"
    }
}

Write-Section "DNS Check"
$dnsRecords = Resolve-DnsName api.openai.com -ErrorAction Stop | Where-Object { $_.IPAddress }
$hasSpecialUseRecord = $false
foreach ($record in $dnsRecords) {
    $isSpecialUse = Test-SpecialUseIp -IpAddress $record.IPAddress
    if ($isSpecialUse) {
        $hasSpecialUseRecord = $true
    }
    Write-Host "- $($record.Type) $($record.IPAddress) specialUse=$isSpecialUse"
}
if ($hasSpecialUseRecord) {
    Write-Warning "api.openai.com resolves to a private/special-use IP on this machine. OpenClaw will block direct OpenAI requests."
}
if ($hasSpecialUseRecord -and -not $hasProxyEnv -and @($registryProxyUrls).Count -gt 0) {
    Write-Warning "Windows has proxy metadata, but Node/OpenClaw in this shell is not using proxy env vars. Use scripts/openclaw-with-proxy.ps1 or set HTTP_PROXY/HTTPS_PROXY/ALL_PROXY plus NODE_USE_ENV_PROXY=1."
}

Write-Section "Backend Health"
try {
    $backendHealth = Invoke-RestMethod -Uri $backendHealthUrl -Method Get -TimeoutSec 5
    Write-Host "Backend health: $($backendHealth.status)"
} catch {
    Write-Warning "Backend health check failed: $($_.Exception.Message)"
}

Write-Section "Hints"
Write-Host "- If every prompt times out, first run a no-tool prompt such as 'Reply with exactly: hi' via OpenClaw."
Write-Host "- If the DNS check above shows special-use IPs for api.openai.com, do not use openai/gpt-5.4 until DNS/proxy is fixed."
Write-Host "- If Node fetch fails but the detected-proxy probe reaches a remote endpoint, run OpenClaw through scripts/openclaw-with-proxy.ps1."
Write-Host "- A 403 from chatgpt.com in the Node probe is acceptable here; it still proves outbound connectivity."
Write-Host "- The gateway wrapper at $HOME\.openclaw\gateway.cmd now injects proxy env vars for the gateway process."
Write-Host "- The project batch config no longer overwrites your model. Set a reachable model yourself after plugin setup."
Write-Host "- Repo root: $repoRoot"
