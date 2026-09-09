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
  public static extern SafeFileHandle CreateFileW(string path, uint access, uint share,
    IntPtr security, uint disposition, uint flags, IntPtr template);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
  public static extern bool MoveFileExW(string source, string destination, uint flags);
  public static int ReplaceJournal(string source, string destination) {
   if (MoveFileExW(source, destination, 9)) return 0;
   return Marshal.GetLastWin32Error();
  }
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
        $item = $null
        try { $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop }
        catch [System.Management.Automation.ItemNotFoundException] {
            if (-not ($first -and $Absent)) { throw }
        }
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
function Get-ObjectInfo([string]$Path) {
    # FILE_READ_ATTRIBUTESとBACKUP_SEMANTICSで、監査権限なしにディレクトリのIDも読む。
    $handle = [N4Uv.FileInfo]::CreateFileW($Path,0x80,7,[IntPtr]::Zero,3,0x02000000,[IntPtr]::Zero)
    try {
        $info = [N4Uv.FileInfo+Info]::new()
        if ($handle.IsInvalid -or -not [N4Uv.FileInfo]::GetFileInformationByHandle($handle,[ref]$info)) {
            throw "Cannot read object identity: $Path"
        }
        return $info
    } finally { $handle.Dispose() }
}
function Get-Identity($Info) { '{0:X8}:{1:X8}{2:X8}' -f $Info.Volume,$Info.IndexHigh,$Info.IndexLow }
function Invoke-JournalRename([string]$Source, [string]$Destination) {
    return [N4Uv.FileInfo]::ReplaceJournal($Source,$Destination)
}
function Get-ObservedTree($Tree) {
    $copy = Get-Json $Tree | ConvertFrom-Json -AsHashtable
    foreach ($node in $copy.nodes) {
        $null = $node.Remove('identity')
        # 新規コピーのACL設定でWindowsが付けるDACLのAIだけを比較から除く。元の記録は変更しない。
        $node.sddl = [regex]::Replace($node.sddl, '^([^()]*)D:((?:P|AR|AI)*)(?=\(|S:|$)', {
            param($match)
            $match.Groups[1].Value + 'D:' + $match.Groups[2].Value.Replace('AI','')
        })
    }
    return $copy
}
function Assert-Observed($Left, $Right, [string]$Message) {
    $actual = Get-ObservedTree $Left
    $expected = Get-ObservedTree $Right
    if ((Get-Json $actual) -ceq (Get-Json $expected)) { return }
    $fields = [Collections.Generic.List[string]]::new()
    foreach ($key in @(@($actual.Keys) + @($expected.Keys) | Sort-Object -Unique)) {
        if ($key -ne 'nodes' -and (Get-Json $actual[$key]) -cne (Get-Json $expected[$key])) {
            $fields.Add($key)
        }
    }
    if ($actual.nodes.Count -ne $expected.nodes.Count) { $fields.Add('nodes.Count') }
    for ($i = 0; $i -lt [Math]::Min($actual.nodes.Count,$expected.nodes.Count); $i++) {
        $a = $actual.nodes[$i]; $b = $expected.nodes[$i]
        foreach ($key in @(@($a.Keys) + @($b.Keys) | Sort-Object -Unique)) {
            if ((Get-Json $a[$key]) -cne (Get-Json $b[$key])) { $fields.Add("nodes[$i].$key") }
        }
    }
    throw "$Message (different fields: $($fields -join ', '))"
}
function Read-Node([string]$Path, [string]$Relative) {
    $item = Get-Item -LiteralPath $Path -Force
    $allowed = [IO.FileAttributes]::Directory -bor [IO.FileAttributes]::Hidden -bor
        [IO.FileAttributes]::Archive -bor [IO.FileAttributes]::Normal -bor [IO.FileAttributes]::NotContentIndexed
    if (([int]$item.Attributes -band (-bnot [int]$allowed)) -ne 0) {
        throw "Unsupported attributes (readonly/reparse/compressed/encrypted/sparse): $Path"
    }
    $acl = Get-Acl -LiteralPath $Path
    $objectInfo = Get-ObjectInfo $Path
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
            Assert-Equal (Get-Identity $info) (Get-Identity $objectInfo) "Object replaced during read: $Path"
            $hash = [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($handle))
        } finally { $handle.Dispose() }
    }
    @{
        relative = $Relative; kind = $(if ($item.PSIsContainer) { 'directory' } else { 'file' })
        hash = $hash; attributes = [int]$item.Attributes
        sddl = $acl.GetSecurityDescriptorSddlForm($script:Sections)
        sacl = 'unobserved'; identity = Get-Identity $objectInfo
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
function Get-SddlParts([string]$Sddl) {
    if ($Sddl -cnotmatch '^O:([A-Za-z0-9-]+)G:([A-Za-z0-9-]+)D:((?:P|AR|AI)*)(.*)$') {
        throw 'Unsupported owner/group/DACL descriptor; no ACL approximation is allowed'
    }
    @{ owner=$Matches[1]; group=$Matches[2]; flags=$Matches[3]; aces=$Matches[4] }
}
function Get-InheritedSddl([string]$ParentSddl, [string]$CreatorSddl, [string]$Kind) {
    $parent = Get-SddlParts $ParentSddl
    $creator = Get-SddlParts $CreatorSddl
    $inherited = [Collections.Generic.List[string]]::new()
    $aces = [regex]::Matches($parent.aces, '\([^()]*\)')
    if (($aces.Value -join '') -cne $parent.aces) { throw 'Unsupported parent DACL syntax' }
    foreach ($ace in $aces) {
        $fields = $ace.Value.Trim('(',')').Split(';')
        if ($fields.Count -ne 6 -or $fields[0] -cnotin @('A','D') -or
            $fields[1] -cnotmatch '^(OI|CI|NP|IO|ID)*$' -or $fields[3] -or $fields[4] -or
            $fields[5] -cin @('CO','CG','S-1-3-0','S-1-3-1','S-1-3-2','S-1-3-3') -or
            $fields[2] -cmatch 'G[ARWX]') {
            throw 'Unsupported parent ACE (only ordinary allow/deny, non-generic, non-creator ACEs are supported)'
        }
        if ($fields[2] -match '^0x' -and ([Convert]::ToUInt32($fields[2].Substring(2),16) -band 0xf0000000L)) {
            throw 'Generic parent access mask is unsupported'
        }
        $flags = $fields[1]
        $oi = $flags.Contains('OI'); $ci = $flags.Contains('CI'); $np = $flags.Contains('NP')
        if ($Kind -eq 'file') {
            if (-not $oi) { continue }
            $fields[1] = 'ID'
        } elseif ($Kind -eq 'directory') {
            if (-not $ci -and (-not $oi -or $np)) { continue }
            $fields[1] = $(if (-not $np) { $(if ($oi) {'OI'}) + $(if ($ci) {'CI'}) }) +
                $(if (-not $ci) {'IO'}) + 'ID'
        } else { throw 'Invalid inheritance child kind' }
        $inherited.Add('(' + ($fields -join ';') + ')')
    }
    # 空DACLとNULL DACLの取り違え、および既定DACLへのフォールバックを許可しない。
    if (-not $inherited.Count) { throw 'Parent has no supported inheritable ACEs' }
    return "O:$($creator.owner)G:$($creator.group)D:AI$($inherited -join '')"
}
function Read-Parent([string]$Path) {
    Assert-Path $Path
    $node = Read-Node $Path ''
    if ($node.kind -ne 'directory') { throw 'Expected existing publication/private parent directory' }
    # 子の作成とrenameで変わる日時以外は、親のIDと権限も封印する。
    $null = $node.Remove('created'); $null = $node.Remove('written')
    return $node
}
function Get-CopyRequirements($Tree, $Parent, $Baseline, [switch]$Publication) {
    $desired = Get-Json $Tree | ConvertFrom-Json -AsHashtable
    $parents = @{''=$Parent}
    foreach ($node in $desired.nodes) {
        $relative = $node.relative.Replace('/','\')
        $parentRelative = if ($relative.Contains('\')) { $relative.Substring(0,$relative.LastIndexOf('\')) } else { '' }
        $parentNode = if (-not $relative) { $Parent } else { $parents[$parentRelative] }
        if ($null -eq $parentNode) { throw 'Missing parent in candidate tree' }
        $old = @($Baseline.nodes | Where-Object { $_.relative -ceq $node.relative -and $_.kind -eq $node.kind })
        $creator = if ($old.Count -eq 1) { $old[0].sddl }
            elseif ($Publication) { $node.sddl } else { $Parent.sddl }
        $node.sddl = if ($Publication -and $old.Count -eq 1) { $old[0].sddl }
            else { Get-InheritedSddl $parentNode.sddl $creator $node.kind }
        $null = $node.Remove('identity')
        if ($node.kind -eq 'directory') { $parents[$relative]=$node }
    }
    return $desired
}
function Set-Node([string]$Path, $Node, [switch]$KeepDacl) {
    $acl = if ($Node.kind -eq 'directory') { [Security.AccessControl.DirectorySecurity]::new() }
        else { [Security.AccessControl.FileSecurity]::new() }
    $sections = if ($KeepDacl) {
        [Security.AccessControl.AccessControlSections]::Owner -bor [Security.AccessControl.AccessControlSections]::Group
    } else { $script:Sections }
    $acl.SetSecurityDescriptorSddlForm($Node.sddl, $sections)
    Set-Acl -LiteralPath $Path -AclObject $acl
    [IO.File]::SetAttributes($Path, [IO.FileAttributes]$Node.attributes)
    $item = Get-Item -LiteralPath $Path -Force
    $item.CreationTimeUtc = [datetime]::new([long]$Node.created, [DateTimeKind]::Utc)
    $item.LastWriteTimeUtc = [datetime]::new([long]$Node.written, [DateTimeKind]::Utc)
}
function Copy-Tree([string]$Source, [string]$Destination, $Expected, $Publication = $null) {
    Assert-Equal (Read-Tree $Source) $Expected "Source changed: $Source"
    Assert-Path $Destination -Absent
    if (Test-Path -LiteralPath $Destination) { throw "Destination exists: $Destination" }
    if ($Expected.kind -eq 'absent') { return }
    $parentPath = Split-Path $Destination
    $parent = Read-Parent $parentPath
    $desired = if ($null -ne $Publication) { $Publication }
        else { Get-CopyRequirements $Expected $parent $Expected }
    # 内容と通常メタデータを別の候補へ差し替えることは許可しない。
    $contentCheck = Get-Json $desired | ConvertFrom-Json -AsHashtable
    for ($i=0; $i -lt $contentCheck.nodes.Count; $i++) { $contentCheck.nodes[$i].sddl=$Expected.nodes[$i].sddl }
    Assert-Observed $contentCheck $Expected 'Copy requirements changed non-ACL metadata'
    foreach ($node in $Expected.nodes) {
        $dest = if ($node.relative) { Join-Path $Destination $node.relative } else { $Destination }
        $src = if ($node.relative) { Join-Path $Source $node.relative } else { $Source }
        if ($node.kind -eq 'directory') { New-ExclusiveDirectory $dest }
        else {
            # 新規作成してバイト列だけを転送し、SACLは作成先の継承規則に従わせる。
            $input = [IO.FileStream]::new($src,'Open','Read','Read')
            try {
                $output = [IO.FileStream]::new($dest,'CreateNew','Write','None')
                try { $input.CopyTo($output); $output.Flush($true) } finally { $output.Dispose() }
            } finally { $input.Dispose() }
        }
        $metadata = @($desired.nodes | Where-Object { $_.relative -ceq $node.relative })[0]
        # 公開候補の親ACLを先に設定してから子を作り、実際のWindows継承を照合する。
        Set-Node $dest $metadata -KeepDacl:($null -eq $Publication)
    }
    # Children are created first so that copying does not disturb directory timestamps.
    foreach ($node in @($desired.nodes | Sort-Object { $_.relative.Length } -Descending)) {
        Set-Node $(if ($node.relative) { Join-Path $Destination $node.relative } else { $Destination }) $node -KeepDacl
    }
    Assert-Observed (Read-Tree $Destination) $desired "Copy does not meet destination ACL/metadata requirements: $Destination"
    Assert-Equal (Read-Parent $parentPath) $parent 'Copy parent changed'
    Assert-Equal (Read-Tree $Source) $Expected "Source changed during copy: $Source"
}
function Move-Tree([string]$Source, [string]$Destination, $Expected) {
    Assert-Equal (Read-Tree $Source) $Expected "Concurrent change: $Source"
    Assert-Path $Destination -Absent
    if (Test-Path -LiteralPath $Destination) { throw "Move destination exists: $Destination" }
    if ($Expected.kind -eq 'absent') { throw 'Cannot rename an absent object' }
    $sourceInfo = Get-ObjectInfo $Source
    $parentInfo = Get-ObjectInfo (Split-Path $Destination)
    if ($sourceInfo.Volume -ne $parentInfo.Volume -or
        [IO.Path]::GetPathRoot($Source) -ine [IO.Path]::GetPathRoot($Destination)) {
        throw 'Rename requires the same local NTFS volume'
    }
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($Source))
    if ($drive.DriveFormat -ne 'NTFS' -or $drive.DriveType -ne 'Fixed') { throw 'Local fixed NTFS required' }
    # flags=0で、上書きとCOPY_ALLOWEDによるコピーへの切り替えを禁止する。
    if (-not [N4Uv.FileInfo]::MoveFileExW($Source,$Destination,0)) {
        throw "Rename failed (Win32 $([Runtime.InteropServices.Marshal]::GetLastWin32Error())): $Source"
    }
    Assert-Equal (Read-Tree $Destination) $Expected "Renamed object changed: $Destination"
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
      (Join-Path $Data 'installs\uv\0.12.10'), (Join-Path $Data 'installs\.mise-installs.toml'),
      (Join-Path $Cache 'uv'), (Join-Path $Data 'downloads\uv')) +
      @('uv','uvx','uv.exe','uvx.exe','uv.cmd','uvx.cmd','uv.ps1','uvx.ps1' |
        ForEach-Object { Join-Path $Data "shims\$_" })
}
