#requires -Version 7.6
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Sections = [Security.AccessControl.AccessControlSections]::Access -bor
    [Security.AccessControl.AccessControlSections]::Owner -bor
    [Security.AccessControl.AccessControlSections]::Group

function Get-Hash([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }
function ConvertTo-Stable($Value) {
    if ($Value -is [Collections.IDictionary]) {
        $out = [ordered]@{}
        foreach ($key in @($Value.Keys | Sort-Object -CaseSensitive)) { $out[$key] = ConvertTo-Stable $Value[$key] }
        return $out
    }
    if ($Value -is [array]) { return ,@($Value | ForEach-Object { ConvertTo-Stable $_ }) }
    return $Value
}
function Get-Json($Value) { ConvertTo-Json -InputObject (ConvertTo-Stable $Value) -Depth 100 -Compress }
function Assert-Equal($Left, $Right, [string]$Message) {
    if ((Get-Json $Left) -cne (Get-Json $Right)) { throw $Message }
}
function Write-NewJson([string]$Path, $Value) {
    $bytes = [Text.Encoding]::UTF8.GetBytes((Get-Json $Value))
    $stream = [IO.FileStream]::new($Path, 'CreateNew', 'Write', 'None')
    try { $stream.Write($bytes); $stream.Flush($true) } finally { $stream.Dispose() }
}
function Read-Json([string]$Path) { Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json -AsHashtable }
function Assert-Native {
    if (-not $IsWindows) { throw 'unsupported_os_not_executed: Windows native only' }
    if (-not ('N4Uv.FileInfo' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
namespace N4Uv {
 public static class FileInfo {
  [StructLayout(LayoutKind.Sequential)]
  public struct Info {
   public uint Attr; public System.Runtime.InteropServices.ComTypes.FILETIME Created,Accessed,Written;
   public uint Volume,SizeHigh,SizeLow,Links,IndexHigh,IndexLow;
  }
  [DllImport("kernel32.dll", SetLastError=true)]
  public static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
  public static extern bool CreateDirectoryW(string path, IntPtr securityAttributes);
 }
}
'@
    }
}
function Assert-Path([string]$Path, [switch]$Absent) {
    if ($Path -notmatch '^[A-Za-z]:\\' -or $Path.Substring(2).Contains(':') -or
        $Path.Substring(3) -match '(^|\\)(\.{1,2}|[^\\]*[. ])(\\|$)|[<>"/|?*]' -or
        $Path -match '(?i)(^|\\)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|\\|$)') {
        throw "Unsupported local absolute path: $Path"
    }
    $cursor = $Path
    $first = $true
    while ($cursor) {
        $item = Get-Item -LiteralPath $cursor -Force -ErrorAction SilentlyContinue
        if ($null -eq $item) {
            if (-not ($first -and $Absent)) { throw "Missing ancestor: $cursor" }
        } elseif ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Unsupported reparse point: $cursor"
        } elseif (-not $first -and -not $item.PSIsContainer) { throw "Not a directory: $cursor" }
        $first = $false
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
function Assert-Beneath([string]$Path, [string]$Root) {
    if (-not $Path.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Outside approved root: $Path"
    }
}
function New-ExclusiveDirectory([string]$Path) {
    Assert-Path $Path -Absent
    if (-not [N4Uv.FileInfo]::CreateDirectoryW($Path,[IntPtr]::Zero)) {
        throw "Cannot exclusively create directory (Win32 $([Runtime.InteropServices.Marshal]::GetLastWin32Error())): $Path"
    }
}
function Read-Node([string]$Path, [string]$Relative) {
    $item = Get-Item -LiteralPath $Path -Force
    $allowed = [IO.FileAttributes]::Directory -bor [IO.FileAttributes]::Hidden -bor
        [IO.FileAttributes]::Archive -bor [IO.FileAttributes]::Normal -bor [IO.FileAttributes]::NotContentIndexed
    if (([int]$item.Attributes -band (-bnot [int]$allowed)) -ne 0) {
        throw "Unsupported attributes (readonly/reparse/compressed/encrypted/sparse): $Path"
    }
    # Failure to read audit information is also unsupported; never elevate or drop it.
    $audit = Get-Acl -LiteralPath $Path -Audit
    if (@($audit.Audit).Count -ne 0 -or $audit.GetSecurityDescriptorSddlForm(
            [Security.AccessControl.AccessControlSections]::Audit) -match 'S:') {
        throw "SACL is unsupported: $Path"
    }
    $streams = @(Get-Item -LiteralPath $Path -Stream * -ErrorAction Stop)
    if (@($streams | Where-Object { $_.Stream -ne ':$DATA' }).Count) { throw "ADS unsupported: $Path" }
    $hash = $null
    if (-not $item.PSIsContainer) {
        $handle = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
        try {
            $info = [N4Uv.FileInfo+Info]::new()
            if (-not [N4Uv.FileInfo]::GetFileInformationByHandle($handle.SafeFileHandle, [ref]$info)) {
                throw "Cannot inspect hardlinks: $Path"
            }
            if ($info.Links -ne 1) { throw "Hardlink unsupported: $Path" }
            $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($handle))
        } finally { $handle.Dispose() }
    }
    @{
        relative = $Relative; kind = $(if ($item.PSIsContainer) { 'directory' } else { 'file' })
        hash = $hash; attributes = [int]$item.Attributes
        sddl = $audit.GetSecurityDescriptorSddlForm($script:Sections)
        created = $item.CreationTimeUtc.Ticks; written = $item.LastWriteTimeUtc.Ticks
    }
}
function Read-Tree([string]$Path) {
    Assert-Path $Path -Absent
    if (-not (Test-Path -LiteralPath $Path)) { return @{ kind = 'absent'; nodes = @() } }
    $nodes = [Collections.Generic.List[object]]::new()
    $queue = [Collections.Generic.Queue[string]]::new()
    $queue.Enqueue($Path)
    while ($queue.Count) {
        $current = $queue.Dequeue()
        $relative = if ($current -eq $Path) { '' } else { $current.Substring($Path.Length + 1) }
        $node = Read-Node $current $relative
        $nodes.Add($node)
        if ($node.kind -eq 'directory') {
            foreach ($child in @(Get-ChildItem -LiteralPath $current -Force | Sort-Object Name)) {
                $queue.Enqueue($child.FullName)
            }
        }
    }
    @{ kind = $nodes[0].kind; nodes = @($nodes.ToArray()) }
}
function Set-Node([string]$Path, $Node) {
    $acl = if ($Node.kind -eq 'directory') { [Security.AccessControl.DirectorySecurity]::new() }
        else { [Security.AccessControl.FileSecurity]::new() }
    $acl.SetSecurityDescriptorSddlForm($Node.sddl, $script:Sections)
    Set-Acl -LiteralPath $Path -AclObject $acl
    [IO.File]::SetAttributes($Path, [IO.FileAttributes]$Node.attributes)
    $item = Get-Item -LiteralPath $Path -Force
    $item.CreationTimeUtc = [datetime]::new([long]$Node.created, [DateTimeKind]::Utc)
    $item.LastWriteTimeUtc = [datetime]::new([long]$Node.written, [DateTimeKind]::Utc)
}
function Copy-Tree([string]$Source, [string]$Destination, $Expected) {
    Assert-Equal (Read-Tree $Source) $Expected "Source changed: $Source"
    Assert-Path $Destination -Absent
    if (Test-Path -LiteralPath $Destination) { throw "Destination exists: $Destination" }
    if ($Expected.kind -eq 'absent') { return }
    foreach ($node in $Expected.nodes) {
        $dest = if ($node.relative) { Join-Path $Destination $node.relative } else { $Destination }
        $src = if ($node.relative) { Join-Path $Source $node.relative } else { $Source }
        if ($node.kind -eq 'directory') { New-ExclusiveDirectory $dest }
        else { [IO.File]::Copy($src, $dest, $false) }
    }
    # Children are created first so that copying does not disturb directory timestamps.
    foreach ($node in @($Expected.nodes | Sort-Object { $_.relative.Length } -Descending)) {
        Set-Node $(if ($node.relative) { Join-Path $Destination $node.relative } else { $Destination }) $node
    }
    Assert-Equal (Read-Tree $Destination) $Expected "ACL/attribute/tree copy not reproducible: $Destination"
    Assert-Equal (Read-Tree $Source) $Expected "Source changed during copy: $Source"
}
function Move-Tree([string]$Source, [string]$Destination, $Expected) {
    Assert-Equal (Read-Tree $Source) $Expected "Concurrent change: $Source"
    Assert-Path $Destination -Absent
    if (Test-Path -LiteralPath $Destination) { throw "Move destination exists: $Destination" }
    if ($Expected.kind -eq 'directory') { [IO.Directory]::Move($Source, $Destination) }
    elseif ($Expected.kind -eq 'file') { [IO.File]::Move($Source, $Destination, $false) }
}
function Assert-Known($Current, $Original, $After) {
    if ((Get-Json $Current) -ceq (Get-Json $Original)) { return 'original' }
    if ((Get-Json $Current) -ceq (Get-Json $After)) { return 'after' }
    throw 'Unknown/concurrent state; refusing overwrite'
}
function Invoke-Captured([string]$Exe, [string[]]$Arguments, [string]$Directory,
        [hashtable]$Environment = @{}, [string]$InputText = '', [switch]$AllowFailure) {
    $psi = [Diagnostics.ProcessStartInfo]::new($Exe)
    $psi.WorkingDirectory = $Directory
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    foreach ($arg in $Arguments) { $psi.ArgumentList.Add($arg) }
    foreach ($key in @($psi.Environment.Keys)) {
        if ($key -like 'MISE_*' -or $key -in @('GH_TOKEN','GITHUB_TOKEN')) { $null=$psi.Environment.Remove($key) }
    }
    foreach ($key in $Environment.Keys) { $psi.Environment[$key] = $Environment[$key] }
    $p = [Diagnostics.Process]::Start($psi)
    try {
        $stdout = $p.StandardOutput.ReadToEndAsync()
        $stderr = $p.StandardError.ReadToEndAsync()
        $p.StandardInput.Write($InputText); $p.StandardInput.Close()
        $p.WaitForExit()
        $result = @{ exitCode = $p.ExitCode; stdout = $stdout.GetAwaiter().GetResult()
            stderr = $stderr.GetAwaiter().GetResult() }
        # Never persist arbitrary command output: errors can include credentials or config values.
        if ($p.ExitCode -ne 0 -and -not $AllowFailure) { throw "Child failed (exit $($p.ExitCode)); output withheld: $([IO.Path]::GetFileName($Exe))" }
        return $result
    } finally { $p.Dispose(); $psi.Environment.Remove('GITHUB_TOKEN') | Out-Null }
}
function ConvertFrom-Toml([string]$Text, [string]$Chezmoi, [string]$Work) {
    $expression = '{{ ' + (ConvertTo-Json -InputObject $Text -Compress) + ' | fromToml | toJson }}'
    $result = Invoke-Captured $Chezmoi @('--config','NUL','--config-format','toml',
        '--source',$Work,'execute-template','--stdinisatty=false') $Work @{} $expression
    $result.stdout | ConvertFrom-Json -AsHashtable
}
function Get-WithoutUv($Value) {
    $copy = (Get-Json $Value) | ConvertFrom-Json -AsHashtable
    $null = $copy.Remove('uv')
    return $copy
}
function Get-Targets([string]$Config, [string]$Data, [string]$Cache) {
    @($Config, (Join-Path (Split-Path $Config) 'mise.lock'),
      (Join-Path $Data 'installs\uv'), (Join-Path $Data 'installs\.mise-installs.toml'),
      (Join-Path $Cache 'uv'), (Join-Path $Data 'downloads\uv')) +
      @('uv','uvx','uv.exe','uvx.exe','uv.cmd','uvx.cmd','uv.ps1','uvx.ps1' |
        ForEach-Object { Join-Path $Data "shims\$_" })
}
