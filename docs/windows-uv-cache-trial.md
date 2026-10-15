# Windows uv cache 回避策の比較検証

この試験では、Windows Copilot の PowerShell tool が通常の `uv` 解決を保ったまま、uv cache へ書き込み、同じ cache を別 tool call から再利用し、atomic rename を実行できるかを測る。control は現行設定、candidate は uv cache workaround の撤去候補である。Python / pip の直接実行を拒否する Guard と uv enforcer、登録済み hook と launcher、元の `allowBypass` を両条件で維持する。

試験を実行するのは Windows 利用者である。通常 PowerShell terminal で準備し、生成された実値入りプロンプトを隔離 Copilot CLI へ貼り付ける。Copilot shell tool から準備スクリプトを実行しない。この試験は Windows 実機では未確認であり、Windows 上での成功を事前に保証しない。

## 試験が比較するもの

最初に通常 terminal の `uv` と Copilot PowerShell tool 内の `uv` を、コマンド種別、実行ファイルの絶対パス、版で比較する。異なる場合や tool 内の `uv --version` が失敗した場合は、cache 測定へ進まない。絶対パス指定、PATH の変更、mise の修理による自動回避はしない。

一致した場合だけ、隔離 workspace で `uv run` を直接実行する。Step 1 は online、Step 2 は別の PowerShell tool call から offline で実行し、cache path、marker の永続性、rename、`idna==3.10` の実行を測る。`--no-python-downloads` により Python の自動 download を止めるが、Python の選択は通常の uv discovery に任せる。package が既に cache に存在する可能性があるため、cold cache の測定とは扱わない。

条件間で変えるのは次の3点だけである。

| 設定 | control | candidate |
|---|---|---|
| uv enforcer の cache rewrite | 保持 | rewrite 分岐だけ除く |
| `COPILOT_DOTFILES_UV_CACHE_DIR` | 子 CLI に設定 | 子 CLI から除外 |
| 専用 cache の exact write grant | 保持 | 除外 |

その他の sandbox 設定、`allowBypass`、hook 登録、launcher、Guard、他の enforcer、filesystem / network / MCP / LSP policy は元の値を保つ。両条件に同じ read-only grant を追加するのは、隔離 Copilot home と hook が使う既存 managed Python root だけである。測定コードと試験記録は workspace に置き、そこへのアクセスには既存の working-directory policy を使う。既存 cache を削除せず、実行環境の PATH や mise 設定も変更しない。

control の hook は通常どおり `modifiedArgs` で cache prefix を自動付加する。自動付加された prefix は、モデルによる環境変数の手動変更ではない。tool 要求と hook の変更を識別できないときは、どちらが値を加えたかを断定しない。モデルは測定 command に prefix を書き足したり、`UV_CACHE_DIR` を設定・解除したりしない。

## 1. 検証 branch を既存 checkout で取得する

Windows native PowerShell 7.3 以降の通常 terminal を開く。chezmoi source directory を使う場合は、次のコードを実行する前に `Set-Location -LiteralPath (chezmoi source-path)` を実行する。別の既存 checkout を使う場合は、コード冒頭の `Set-Location` に checkout の実パスを指定する。未コミット変更や未追跡ファイルがある checkout では停止する。コードは変更の stash、破棄、commit をしない。

```powershell
. {
    if (-not $IsWindows -or $PSVersionTable.PSVersion -lt [version]'7.3') {
        throw 'Use an ordinary native Windows PowerShell 7.3 or later terminal.'
    }
    Set-Location -LiteralPath (chezmoi source-path) -ErrorAction Stop
    $repoRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { throw 'Current directory is not inside a Git checkout.' }
    $originUrl = (& git -C $repoRoot remote get-url origin | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $originUrl -notmatch '[:/]torumakabe/dotfiles(?:\.git)?/?$') {
        throw 'This is not the expected torumakabe/dotfiles checkout.'
    }
    Set-Location -LiteralPath $repoRoot -ErrorAction Stop
    if (@(& git status --porcelain).Count) {
        git status --short
        throw 'Save existing checkout changes before switching branches.'
    }
    $trialBranch = 'validation/windows-uv-cache-trial'
    & git fetch origin "refs/heads/${trialBranch}:refs/remotes/origin/${trialBranch}"
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch the validation branch.' }
    if (@(& git branch --list $trialBranch).Count) {
        & git merge-base --is-ancestor $trialBranch "origin/$trialBranch"
        if ($LASTEXITCODE -ne 0) { throw 'Local validation branch has separate commits; review it without resetting.' }
        & git switch $trialBranch
        if ($LASTEXITCODE -ne 0) { throw 'Could not switch to the validation branch.' }
        & git merge --ff-only "origin/$trialBranch"
        if ($LASTEXITCODE -ne 0) { throw 'Could not fast-forward the validation branch.' }
    } else {
        & git switch --track "origin/$trialBranch"
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local validation branch.' }
    }
    $repoRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
    Set-Location -LiteralPath $repoRoot -ErrorAction Stop
    $prepareScript = Join-Path $repoRoot 'tests\manual\windows\uv-cache-trial\Prepare-UvCacheTrial.ps1'
    if (-not (Test-Path -LiteralPath $prepareScript -PathType Leaf)) {
        throw 'The validation kit is missing from this checkout.'
    }
}
```

chezmoi source path が checkout 外を指す場合は、branch を切り替えた後の checkout root に移動してから準備する。以降の操作は同じ通常 terminal で行う。CLI、mise 管理の `uv`、dotfiles の Copilot hook runtime が利用可能であることが前提となる。

## 2. control と candidate を準備する

下のコード全体を通常 terminal に貼り付ける。準備スクリプトはホストの通常 `uv` の種別、実パス、版だけを記録し、trial root を `%LOCALAPPDATA%\CopilotUvCacheTrials` 内に新しい GUID で作る。元の Copilot home と source hook を複製する。準備に失敗した root は再利用せず、新しい GUID で再実行する。

```powershell
. {
    $repoRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { throw 'Start inside the existing dotfiles checkout.' }
    Set-Location -LiteralPath $repoRoot -ErrorAction Stop
    $prepareScript = Join-Path $repoRoot 'tests\manual\windows\uv-cache-trial\Prepare-UvCacheTrial.ps1'
    if (-not (Test-Path -LiteralPath $prepareScript -PathType Leaf)) {
        throw 'The preparation script is missing; complete step 1 first.'
    }
    $trialParent = Join-Path $env:LOCALAPPDATA 'CopilotUvCacheTrials'
    if (-not (Test-Path -LiteralPath $trialParent -PathType Container)) {
        New-Item -ItemType Directory -Path $trialParent -ErrorAction Stop | Out-Null
    }
    $trialRoot = Join-Path $trialParent ('trial-' + [guid]::NewGuid().ToString('N'))
    $pwshPath = (Get-Command pwsh.exe -ErrorAction Stop).Source
    & $pwshPath -NoProfile -File $prepareScript -Action Prepare `
        -Root $trialRoot -SourceCopilotHome "$HOME\.copilot"
    if ($LASTEXITCODE -ne 0) { throw 'Trial preparation failed; do not reuse its partial directory.' }
    Write-Output "Trial root: $trialRoot"
}
```

`SourceCopilotHome` は対象端末の配布済み `~\.copilot` とする。準備は既存 hook runtime record の managed Python を hook 実行用に読み取り許可するが、uv が実行する Python は固定しない。親 terminal の `UV_CACHE_DIR` は変更せず、存在の有無だけを launch 記録に残す。Guard、uv enforcer、launcher、登録済み hook は複製して維持する。candidate の enforcer は既知の cache rewrite 分岐だけを除く。準備スクリプトは元 `allowBypass` を書き換えない。

## 3. control を実行する

準備時と同じ通常 terminal で、次のコード全体を貼り付ける。生成済み control prompt を clipboard に入れてから隔離 CLI を起動する。clipboard の現在の内容は置き換わる。起動後、その prompt を control CLI に貼り付ける。

```powershell
. {
    $trialPrompt = @(& $pwshPath -NoProfile -File $prepareScript -Action Prompt -Root $trialRoot -Mode control)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the prepared control prompt.' }
    ($trialPrompt -join "`n") | Set-Clipboard -ErrorAction Stop
    & $pwshPath -NoProfile -File $prepareScript -Action Launch -Root $trialRoot -Mode control
    if ($LASTEXITCODE -ne 0) { throw 'Control CLI exited with an error.' }
}
```

生成された prompt はまず Copilot PowerShell tool 内で `Get-Command uv` と通常の `uv --version` を実行する。ホストの記録と一致し、tool 内 `uv` が Application として解決された場合だけ測定へ進む。一致しない場合はその時点で停止し、絶対パス、別 command、PATH 変更を試さない。

測定は direct `uv run` で行う。Step 1 が成功した場合に限り、prompt にある Step 2 を別の PowerShell tool call で実行する。`uv run` が失敗した場合、準備済み command を別構文に変えたり、環境変数を追加したりしない。control の cache prefix は hook が自動付加するため、tool 要求に手入力しない。

## 4. candidate を実行する

control CLI を終了して通常 terminal に戻る。同じ `$trialRoot` のまま、candidate を起動する。生成済み candidate prompt をそのまま貼り付ける。

```powershell
. {
    $trialPrompt = @(& $pwshPath -NoProfile -File $prepareScript -Action Prompt -Root $trialRoot -Mode candidate)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the prepared candidate prompt.' }
    ($trialPrompt -join "`n") | Set-Clipboard -ErrorAction Stop
    & $pwshPath -NoProfile -File $prepareScript -Action Launch -Root $trialRoot -Mode candidate
    if ($LASTEXITCODE -ne 0) { throw 'Candidate CLI exited with an error.' }
}
```

## 5. 結果を判定する

条件ごとに次のファイルを確認する。

| ファイル | 内容 |
|---|---|
| `workspace\evidence\<mode>\uv-resolution.json` | tool 内 `uv` の種別、パス、版とホスト値の比較 |
| `workspace\evidence\<mode>\launch.json` | 隔離 CLI が読み込んだ設定と起動 mode |
| `workspace\evidence\<mode>\step-1.json` | cache path、marker 作成、rename、online `uv run` の結果 |
| `workspace\evidence\<mode>\step-2.json` | 別 tool call からの同一 cache / marker 確認、offline `uv run` の結果 |

`uv run` が payload を起動する前に失敗した場合、step JSON は作られない。tool の終了結果を失敗証拠として扱い、別の実行方法で再試行しない。payload 起動後の失敗は安全な stage / error code だけを step JSON に記録する。stderr 全文、認証情報、環境変数一覧は共有しない。既存 cache や失敗結果を削除、上書きしない。

`technical-success` は payload の測定が成功したことだけを示す。candidate の成功を上流 sandbox cache 機能へ帰属するには、対象 CLI が `1.0.98-0` で、報告 cache がその版の private `sandbox\packages\uv` と一致し、tool 実行時の `UV_CACHE_DIR` もその cache を指し、親 terminal からの同変数の既存指定がなく、cache が workspace、旧専用 grant、既存の他の user write grant、TEMP のいずれにも含まれないことが必要である。これらの記録は実行中 sandbox が有効だったこと自体の独立証明ではない。根拠がそろわない場合は判定を保留する。runtime backend 全体の手入力を測定開始条件にはしない。CLI が別版でも cache 動作は測るが、その版の runtime source を別途照合するまでは帰属しない。

| 観測結果 | 判定 |
|---|---|
| ホストと tool の `uv` 解決が一致しない | cache 測定前に停止。起動条件が異なり比較不能 |
| control / candidate とも成功し、candidate が private cache と既存 grant 外の条件を満たす | この CLI / Windows build での撤去候補。実環境の証拠と合わせて別途判断 |
| control 成功、candidate cache write / rename が失敗 | 現環境では回避策を維持 |
| control 失敗、offline 再利用失敗、または既存 grant / workspace / TEMP と cache が重なる | 比較または帰属が成立せず判定保留 |
| private cache の実行時帰属を確認できない | sandbox 書き込み成功だけで撤去を判断しない |

検証後、利用者が結果を保存する。`probeOwnedDirectory` に記録された試験専用 directory を削除する場合は、その exact directory だけを対象にする。cache の親 directory や既存 cache 内容は削除しない。隔離 CLI home に認証情報が含まれる場合があるため、trial root 全体や prompt を共有しない。

## 生成 prompt の内容

準備スクリプトは `<Root>` と `<Mode>` を実値へ置換し、control / candidate ごとの prompt を trial root に保存する。利用者は生成用 template ではなく、手順3または4で clipboard に入れた本文を使う。

<details>
<summary>生成用 template</summary>

<!-- uv-cache-trial-prompt:start -->
```text
Windows の uv cache 比較試験を実行してください。
Root: <Root>
Mode: <Mode>

この CLI は通常 terminal から隔離 home として起動され、PowerShell tool の cwd は trial workspace です。cwd から移動せず、別の PowerShell process、shell tool、追加 hook、質問フォーム、checkpoint を使わないでください。設定変更、grant 追加、PATH/mise の変更、Python / pip の直接起動、Python download、cache 削除をしないでください。

最初に次の preflight を PowerShell tool で一度実行してください。この command は通常の `uv` 解決を検証します。結果の `matched` が true でなければ停止し、Step 1 / 2 を実行しないでください。絶対パスへの fallback をしないでください。

$PSNativeCommandUseErrorActionPreference = $false
$resolutionPath = '.\evidence\<Mode>\uv-resolution.json'
if (Test-Path -LiteralPath $resolutionPath) { throw 'Preflight evidence already exists; do not overwrite it.' }
$trial = Get-Content -LiteralPath '.\trial.json' -Raw | ConvertFrom-Json
$hostUv = $trial.hostUv
$tool = Get-Command uv -ErrorAction SilentlyContinue
$toolType = if ($tool) { [string]$tool.CommandType } else { 'NotFound' }
$toolPath = if ($tool -and $tool.Source) { [IO.Path]::GetFullPath($tool.Source) } else { $null }
$toolVersionOutput = @()
$toolExitCode = -1
if ($toolType -eq 'Application') {
    uv --version | Tee-Object -Variable toolVersionOutput
    $toolExitCode = $LASTEXITCODE
}
$toolVersion = ($toolVersionOutput -join "`n").Trim()
$pathMatches = $false
if ($toolPath -and $hostUv.path) {
    $pathMatches = [IO.Path]::GetFullPath($toolPath).Equals(
        [IO.Path]::GetFullPath($hostUv.path), [StringComparison]::OrdinalIgnoreCase)
}
$record = [ordered]@{
    toolCommandType = $toolType
    toolPath = $toolPath
    toolVersion = $toolVersion
    toolExitCode = $toolExitCode
    uvCacheEnvironment = $env:UV_CACHE_DIR
    matched = ($toolType -eq 'Application' -and $toolExitCode -eq 0 -and
        $pathMatches -and $toolVersion -ceq $hostUv.version)
}
$record | ConvertTo-Json | Set-Content -LiteralPath $resolutionPath -Encoding utf8
$record | ConvertTo-Json -Compress
if (-not $record.matched) { throw 'uv resolution differs from the ordinary terminal; stop before cache measurement.' }

preflight が成功した後だけ、次の command を実行してください。各 command は別々の PowerShell tool call で実行します。control hook の `modifiedArgs` が自動付加する prefix を編集せず、そのまま実行してください。モデル自身は `COPILOT_DOTFILES_UV_CACHE_DIR` を `UV_CACHE_DIR` に転記せず、`UV_CACHE_DIR` を設定または解除しないでください。

Step 1:
uv run --no-python-downloads --with idna==3.10 python .\Test-UvCacheSandbox.py --mode <Mode> --step 1

Step 1 が成功した場合だけ、別の PowerShell tool call で実行してください。

Step 2:
uv run --offline --no-python-downloads --with idna==3.10 python .\Test-UvCacheSandbox.py --mode <Mode> --step 2

いずれかの command が失敗した場合は停止してください。別形式で再試行せず、tool の失敗結果と生成済み JSON を保持してください。`technical-success` は payload の実行成功だけを示します。結果を報告するときは cache path と environment の一致、既存 write grant / workspace / TEMP との重複、別 tool call の marker と offline 結果を含め、runtime 帰属を確認できない場合は判定保留としてください。
```
<!-- uv-cache-trial-prompt:end -->

</details>

## 実装根拠と適用範囲

Copilot CLI 1.0.98-0 の runtime は PowerShell command 中の実行名 `uv` を Python dev-tool scope に分類する。したがって測定 command は bare な `uv run` であり、wrapper、call operator、絶対パス起動を使わない。分類処理は `src/runtime/src/tools_base/shell_safety.rs`、`src/runtime/src/tools_base/program_name.rs`、`src/runtime/src/sandbox_pure/dev_tool_access.rs`、`src/runtime/src/turn_engine/shell_attached.rs` にある。通常 terminal と Copilot tool の `uv` が一致しない状況では、試験は cache 条件の比較に進まない。

runtime の Windows private uv cache は CLI cache home の `sandbox\packages\uv` にある。cache home は `COPILOT_CACHE_HOME` があればそれを使い、なければ Windows の `%LOCALAPPDATA%\copilot` を使う。runtime の path 解決は `src/runtime/src/workspace/path_helpers.rs` にある。この試験は cache path と関連 environment の観測から帰属を評価するが、一般のすべての Copilot sandbox 構成や backend を保証するものではない。
