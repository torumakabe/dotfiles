# === Environment variables ===
$env:EDITOR = 'edit'

# === Functions ===

# Copilot CLI workaround: edit.exe を新コンソールで開く短縮コマンド
function Open-EditInNewConsole {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Path
    )

    $escapedPath = $Path | ForEach-Object {
        '"' + ($_ -replace '"', '\"') + '"'
    }
    $command = if ($escapedPath) {
        'start "" edit ' + ($escapedPath -join ' ')
    }
    else {
        'start "" edit'
    }

    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $command | Out-Null
}

function zi { cdi @args }

# ghq + fzf: fuzzy-search git repositories and cd into selection
function ghcd {
    $dir = ghq list -p | fzf
    if ($dir) { Set-Location $dir }
}

# === Aliases ===
Set-Alias -Name e -Value Open-EditInNewConsole
Set-Alias -Name k -Value kubectl

# === Completers and tool setup ===

# https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-windows?tabs=azure-cli#enable-tab-completion-in-powershell
Register-ArgumentCompleter -Native -CommandName az -ScriptBlock {
    param($commandName, $wordToComplete, $cursorPosition)
    $completion_file = New-TemporaryFile
    $env:ARGCOMPLETE_USE_TEMPFILES = 1
    $env:_ARGCOMPLETE_STDOUT_FILENAME = $completion_file
    $env:COMP_LINE = $wordToComplete
    $env:COMP_POINT = $cursorPosition
    $env:_ARGCOMPLETE = 1
    $env:_ARGCOMPLETE_SUPPRESS_SPACE = 0
    $env:_ARGCOMPLETE_IFS = "`n"
    $env:_ARGCOMPLETE_SHELL = 'powershell'
    az 2>&1 | Out-Null
    Get-Content $completion_file | Sort-Object | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, "ParameterValue", $_)
    }
    Remove-Item $completion_file, Env:\_ARGCOMPLETE_STDOUT_FILENAME, Env:\ARGCOMPLETE_USE_TEMPFILES, Env:\COMP_LINE, Env:\COMP_POINT, Env:\_ARGCOMPLETE, Env:\_ARGCOMPLETE_SUPPRESS_SPACE, Env:\_ARGCOMPLETE_IFS, Env:\_ARGCOMPLETE_SHELL
}

kubectl completion powershell | Out-String | Invoke-Expression
Register-ArgumentCompleter -CommandName k -ScriptBlock $__kubectlCompleterBlock

# zoxide (smarter cd)
Invoke-Expression (& { (zoxide init powershell --cmd cd | Out-String) })
Set-Alias -Name z -Value cd
