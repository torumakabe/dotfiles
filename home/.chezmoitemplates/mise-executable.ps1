$miseExe = Join-Path $HOME '.local\bin\mise.exe'
if (-not (Test-Path -LiteralPath $miseExe -PathType Leaf)) {
  $miseExe = (Get-Command -CommandType Application -Name 'mise.exe' -ErrorAction SilentlyContinue |
    Select-Object -First 1).Source
}
