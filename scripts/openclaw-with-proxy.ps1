param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$OpenClawArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:HTTP_PROXY = "http://127.0.0.1:7897"
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
$env:ALL_PROXY = "http://127.0.0.1:7897"
$env:NODE_USE_ENV_PROXY = "1"

$openAiKey = [Environment]::GetEnvironmentVariable("OPENAI_API_KEY")
$dashscopeKey = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY")
if ($openAiKey -and $dashscopeKey -and $openAiKey -eq $dashscopeKey) {
    [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $null, "Process")
}

$CliPath = "C:\developtool\node_global\node_modules\openclaw\openclaw.mjs"
$NodePath = "C:\developtool\node.exe"
$WrapperPath = Join-Path $PSScriptRoot "openclaw-cli-wrapper.mjs"

if (-not (Test-Path -LiteralPath $NodePath)) {
    throw "Node executable not found: $NodePath"
}
if (-not (Test-Path -LiteralPath $CliPath)) {
    throw "OpenClaw CLI entry not found: $CliPath"
}
if (-not (Test-Path -LiteralPath $WrapperPath)) {
    throw "OpenClaw wrapper entry not found: $WrapperPath"
}

$ResolvedArgs = New-Object System.Collections.Generic.List[string]
for ($index = 0; $index -lt $OpenClawArgs.Count; $index += 1) {
    $current = $OpenClawArgs[$index]
    if ($current -eq "--message-b64") {
        if ($index + 1 -ge $OpenClawArgs.Count) {
            throw "--message-b64 requires a base64 payload"
        }
        $index += 1
        $env:OPENCLAW_MESSAGE_B64 = $OpenClawArgs[$index]
        $ResolvedArgs.Add("--message-from-env") | Out-Null
        continue
    }
    $ResolvedArgs.Add($current) | Out-Null
}

$env:OPENCLAW_CLI_PATH = $CliPath
& $NodePath $WrapperPath @ResolvedArgs
exit $LASTEXITCODE
