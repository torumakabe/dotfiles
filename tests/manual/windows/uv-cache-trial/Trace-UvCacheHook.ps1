# Evidence adapter only: forwards the original hook result unchanged.
[CmdletBinding()]
param(
    [Parameter(ValueFromPipeline)] [AllowNull()] [object] $HookInput,
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
    $transport = if ($inputs.Count) { 'pipeline' } else { 'stdin' }
    $raw = if ($inputs.Count) { $inputs -join "`n" } else { [Console]::In.ReadToEnd() }
    if ([string]::IsNullOrWhiteSpace($raw)) { throw 'Hook evidence adapter received empty input.' }
    $payload = $raw | ConvertFrom-Json -AsHashtable
    if ($payload -isnot [Collections.IDictionary]) { throw 'Hook input must be a JSON object.' }
    $command = ''
    if ($payload['toolName'] -in @('bash', 'powershell')) {
        $argsObject = $payload['toolArgs']
        if ($argsObject -is [string]) { $argsObject = $argsObject | ConvertFrom-Json -AsHashtable }
        if ($argsObject -isnot [Collections.IDictionary]) { throw 'Shell toolArgs must be a JSON object.' }
        if ($null -ne $argsObject['command']) {
            if ($argsObject['command'] -isnot [string]) { throw 'Shell command must be a string.' }
            $command = $argsObject['command']
        }
    }
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
        toolName = $payload['toolName']; inputTransport = $transport
        commandSHA256 = $commandHash; scriptSHA256 = (Get-FileHash -LiteralPath $scriptPath).Hash
        permissionDecision = $(if ($null -ne $permission) { $permission.Value } else { $null })
        modifiedArgs = $modified
        cachePrefixPresent = $rewritten.Contains('COPILOT_DOTFILES_UV_CACHE_DIR')
        exitCode = $code
    } | ConvertTo-Json -Compress | Add-Content -LiteralPath $EvidencePath -Encoding utf8
    if ($output.Trim()) { Write-Output $output }
    exit $code
}
