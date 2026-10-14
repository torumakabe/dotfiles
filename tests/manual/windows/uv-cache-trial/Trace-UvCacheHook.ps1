# Evidence adapter only: forwards the original hook result unchanged.
[CmdletBinding()]
param(
    [Parameter(ValueFromPipeline)] [object] $HookInput,
    [Parameter(Mandatory)] [string] $Launcher,
    [Parameter(Mandatory)] [string] $ScriptName,
    [Parameter(Mandatory)] [string] $EvidencePath
)
begin {
    $ErrorActionPreference = 'Stop'
    $inputs = [Collections.Generic.List[string]]::new()
}
process {
    if ($null -ne $HookInput) { $inputs.Add([string]$HookInput) }
}
end {
    $raw = $inputs -join "`n"
    $payload = $raw | ConvertFrom-Json
    $argsObject = $payload.toolArgs
    if ($argsObject -is [string]) { $argsObject = $argsObject | ConvertFrom-Json }
    $command = [string]$argsObject.command
    $bytes = [Text.Encoding]::UTF8.GetBytes($command)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $commandHash = [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '') }
    finally { $sha.Dispose() }
    $step = if ($command -match '(?i)-Step\s+([12])\b') { [int]$Matches[1] } else { 0 }
    $global:LASTEXITCODE = 0
    $lines = @($raw | & $Launcher $ScriptName)
    $code = $LASTEXITCODE
    $output = $lines -join "`n"
    $decision = if ($output.Trim()) { $output | ConvertFrom-Json } else { [pscustomobject]@{} }
    $modified = $null -ne $decision.PSObject.Properties['modifiedArgs']
    $rewritten = if ($modified) { [string]$decision.modifiedArgs.command } else { '' }
    $permission = $decision.PSObject.Properties['permissionDecision']
    $scriptPath = Join-Path (Split-Path -Parent $Launcher) "scripts\$ScriptName"
    [ordered]@{
        time = [DateTime]::UtcNow.ToString('o'); script = $ScriptName; step = $step
        commandSHA256 = $commandHash; scriptSHA256 = (Get-FileHash -LiteralPath $scriptPath).Hash
        permissionDecision = $(if ($null -ne $permission) { $permission.Value } else { $null })
        modifiedArgs = $modified
        cachePrefixPresent = $rewritten.Contains('COPILOT_DOTFILES_UV_CACHE_DIR')
        exitCode = $code
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath $EvidencePath -Encoding utf8
    if ($output.Trim()) { Write-Output $output }
    exit $code
}
