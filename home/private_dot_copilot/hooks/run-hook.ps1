# Copilot CLI hook launcher (Windows)
#
# Copilot CLI 1.0.90-6 以降、command hook は session sandbox 内で実行される。
# ProcessContainer 内では mise が config、lockfile、state、downloads を読み書き
# できず、shim 解決に失敗する。そのため hook は mise も uv も起動せず、
# chezmoi apply 時に記録した uv managed interpreter を絶対パスで直接実行する。
# 撤去条件は docs/troubleshooting.md を参照する。
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true, Position = 0)]
  [string] $ScriptName,

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]] $HookArguments
)

$ErrorActionPreference = 'Stop'

function Exit-HookLauncher {
  param([Parameter(Mandatory = $true)] [string] $Message)

  [Console]::Error.WriteLine("copilot hook launcher: $Message")
  exit 1
}

function Get-NormalizedPathKey {
  param([Parameter(Mandatory = $true)] [string] $Path)

  return (($Path -replace '/', '\').TrimEnd('\')).ToLowerInvariant()
}

$hooksDir = Split-Path -Parent $PSCommandPath
$runtimeFile = Join-Path $hooksDir 'python-runtime.env'

if ($ScriptName -match '[\\/]' -or $ScriptName -match '\.\.') {
  Exit-HookLauncher "script name must be a bare file name: $ScriptName"
}
$scriptPath = Join-Path (Join-Path $hooksDir 'scripts') $ScriptName
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
  Exit-HookLauncher "hook script not found: $scriptPath"
}

if (-not (Test-Path -LiteralPath $runtimeFile -PathType Leaf)) {
  Exit-HookLauncher "missing $runtimeFile; run chezmoi apply"
}

$pythonRoot = $null
$pythonPath = $null
foreach ($line in [System.IO.File]::ReadAllLines($runtimeFile)) {
  $separator = $line.IndexOf('=')
  if ($separator -lt 1) { continue }
  $key = $line.Substring(0, $separator)
  $value = $line.Substring($separator + 1)
  if ($key -eq 'python_root') { $pythonRoot = $value }
  elseif ($key -eq 'python') { $pythonPath = $value }
}

if ([string]::IsNullOrWhiteSpace($pythonRoot)) {
  Exit-HookLauncher "$runtimeFile has no python_root; run chezmoi apply"
}
if ([string]::IsNullOrWhiteSpace($pythonPath)) {
  Exit-HookLauncher "$runtimeFile has no python; run chezmoi apply"
}
if (-not [System.IO.Path]::IsPathFullyQualified($pythonRoot)) {
  Exit-HookLauncher "python_root must be absolute: $pythonRoot"
}
if (-not (Get-NormalizedPathKey -Path $pythonPath).StartsWith(
    (Get-NormalizedPathKey -Path $pythonRoot) + '\',
    [System.StringComparison]::Ordinal)) {
  Exit-HookLauncher "python must live under ${pythonRoot}: $pythonPath"
}
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
  Exit-HookLauncher "recorded interpreter is not a regular file: $pythonPath"
}

& $pythonPath $scriptPath @HookArguments
exit $LASTEXITCODE
