$ErrorActionPreference = "Stop"

try {
    # fail-open 緩和: エラー時は catch ブロックで deny を返し、exit 0 で正常終了させる
    # （非ゼロ終了すると Hooks の fail-open ポリシーにより deny が無視される）

    # stdin を UTF-8 として読み取り
    # Copilot CLI は UTF-8 で JSON を送信するが、Windows の PowerShell は
    # Console.InputEncoding (既定: CP932 等) で読み取るため、日本語等の
    # マルチバイト文字が文字化けし、0x5C (\) バイトが消費されて JSON が壊れる
    $reader = [System.IO.StreamReader]::new(
        [Console]::OpenStandardInput(),
        [System.Text.Encoding]::UTF8)
    $rawInput = $reader.ReadToEnd()
    $reader.Close()

    # BOM 除去 & 前後空白除去
    $rawInput = $rawInput.TrimStart([char]0xFEFF, [char]0xFFFE).Trim()

    $inputJson = $rawInput | ConvertFrom-Json
    $toolName = $inputJson.toolName
    $toolArgsRaw = $inputJson.toolArgs

    # toolArgs は JSON 文字列の場合があるため再パース
    $parsedArgs = $null
    if ($toolArgsRaw -is [string]) {
      try { $parsedArgs = $toolArgsRaw | ConvertFrom-Json } catch { }
    } elseif ($toolArgsRaw -is [PSCustomObject]) {
        $parsedArgs = $toolArgsRaw
    }

    $scriptDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
    $blockedFile = Join-Path $scriptDir "blocked-files.txt"
    $allowedUrlsFile = Join-Path $scriptDir "allowed-urls.txt"

    if (-not (Test-Path $blockedFile)) {
        @{
            permissionDecision       = "deny"
            permissionDecisionReason = "blocked-files.txt not found - fail-safe deny"
        } | ConvertTo-Json -Compress
        exit 0
    }

    $blockedPatterns = Get-Content $blockedFile |
        Where-Object { $_ -and $_ -notmatch '^\s*#' } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
    # --- ツール引数の分類 ---
    # コンテンツ系プロパティはスキップ（コード断片がブロックパターンに誤一致するのを防止）
    $contentProps = @('file_text', 'old_str', 'new_str', 'input',
                      'description', 'prompt', 'query', 'view_range', 'pattern')
    $pathProps = @('path', 'file', 'uri', 'glob')

    $pathTargets = @()
    $commandTargets = @()

    if ($parsedArgs) {
        foreach ($prop in $parsedArgs.PSObject.Properties) {
            if ($prop.Value -is [string]) {
                if ($contentProps -contains $prop.Name) { continue }
                if ($pathProps -contains $prop.Name) {
                    $pathTargets += $prop.Value
                } else {
                    $commandTargets += $prop.Value
                }
            }
        }
    } elseif ($toolArgsRaw -is [string]) {
        $commandTargets = @($toolArgsRaw)
    }

    # --- ブロックファイルパターン検査 ---
    foreach ($pattern in $blockedPatterns) {
        $short = $pattern -replace '^\*+[\\/]?', '' -replace '[\\/]?\*+$', ''
        if (-not $short) { continue }

        # パス系プロパティ: 厳密な部分文字列マッチ
        foreach ($text in $pathTargets) {
            if (-not $text) { continue }
            if ($text -like "*$short*") {
                @{
                    permissionDecision       = "deny"
                    permissionDecisionReason = "Blocked pattern: $pattern"
                } | ConvertTo-Json -Compress
                exit 0
            }
        }

        # コマンド/その他プロパティ: 境界考慮マッチ
        # パス区切り/空白/引用符/シェルメタ文字/代入演算子/文字列先頭を境界として
        # パターンの出現を検査する。os.environ のようなコード内の部分一致による誤検知を防ぐ。
        $shortClean = $short -replace '[*?]', ''
        if (-not $shortClean) { continue }
        $escaped = [regex]::Escape($shortClean)
        $b = '[\\/\s"' + "'" + ';|&()$`=]'
        $re = '(?:' + $b + '|^)' + $escaped
        foreach ($text in $commandTargets) {
            if (-not $text) { continue }
            if ($text -match $re) {
                @{
                    permissionDecision       = "deny"
                    permissionDecisionReason = "Blocked pattern: $pattern"
                } | ConvertTo-Json -Compress
                exit 0
            }
        }
    }

    # ⚠️ 迂回手法の脅威モデル:
    # - Base64 エンコード、変数間接参照、グロブ展開、サブシェル、シンボリックリンク、パスエンコード等
    #   により、パターン検査は迂回される可能性がある。
    # - Hooks は「正直なエージェント」に対するガードレールであり、侵害されたエージェントには耐性がない。
    # - 多層防御の一層として位置づけ、サンドボックス環境や --deny-tool による補完を前提とする。
    # --- URL 許可リスト検査 ---
    $allowedDomains = @()
    if (Test-Path $allowedUrlsFile) {
        $allowedDomains = Get-Content $allowedUrlsFile |
            Where-Object { $_ -and $_ -notmatch '^\s*#' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    }

    function Test-UrlAllowed {
        param([string]$Url)
        if (-not $Url -or $allowedDomains.Count -eq 0) { return $true }
        if ($Url -notmatch 'https?://([^/:]+)') { return $true }
        $urlHost = $Matches[1]
        foreach ($domain in $allowedDomains) {
            if ($urlHost -eq $domain -or $urlHost.EndsWith(".$domain")) {
                return $true
            }
        }
        return $false
    }

    if ($allowedDomains.Count -gt 0) {
        # コマンド内の URL を検査
        foreach ($text in $commandTargets) {
            if (-not $text) { continue }
            $urlMatches = [regex]::Matches($text, 'https?://[^\s"'']+')
            foreach ($m in $urlMatches) {
                if (-not (Test-UrlAllowed $m.Value)) {
                    @{
                        permissionDecision       = "deny"
                        permissionDecisionReason = "URL not in allowlist: $($m.Value)"
                    } | ConvertTo-Json -Compress
                    exit 0
                }
            }
        }

        # web_fetch ツール: URL 引数を検査
        if ($toolName -eq "web_fetch" -and $parsedArgs -and $parsedArgs.url) {
            if (-not (Test-UrlAllowed $parsedArgs.url)) {
                @{
                    permissionDecision       = "deny"
                    permissionDecisionReason = "URL not in allowlist: $($parsedArgs.url)"
                } | ConvertTo-Json -Compress
                exit 0
            }
        }
    }

    # デフォルト: 通過
    exit 0
}
catch {
    # fail-safe: エラー時は deny を返して fail-open を防止
    @{
        permissionDecision       = "deny"
        permissionDecisionReason = "Hook script error (fail-safe deny): $($_.Exception.Message)"
    } | ConvertTo-Json -Compress
    exit 0
}