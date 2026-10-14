# Windows uv cache 回避策の比較検証

利用者が用意する Windows native 環境で、Copilot sandbox の上流機能だけで uv cache の書き込みと rename が成功するかを確認する。Python / pip の直接実行を拒否する uv enforcer と Guard は維持する。成功しても、この検証だけで回避策の撤去や dotfiles の適用を承認したことにはならない。

現行の cache 注入と専用 write grant を保持する **control** と、隔離設定からそれらだけを外す **candidate** を比較する。

利用者は Windows の通常の PowerShell 7.3 以降の terminal を開き、この検証コードが存在する dotfiles checkout のルートへ移動して開始する。Copilot の shell tool では開始しない。

この検証キットは `validation/windows-uv-cache-trial` branch から取得する。対象 Windows では同 branch のファイルがある既存 checkout を使う。手順1は別 repository や検証キットのない branch を検出して停止する。

導入済み Copilot CLI と uv、dotfiles が provision 済みの hook interpreter が必要である。本検証キットは Windows で動作検証していない。このガイドを上から順に読み、手順6のプロンプトまで同じ文書内で進める。スクリプト本文を読む必要はない。

## 1. 既存 checkout に移動して開始位置を確認する

利用者が chezmoi の既存 source directory を使う場合に限り、通常の PowerShell terminal で `Set-Location -LiteralPath (chezmoi source-path)` を実行する。この repository では source directory が checkout 内の `home/` を指す場合があるため、下のコードで Git root へ移動する。別の既存 checkout を使う場合は、`Set-Location -LiteralPath '<検証コードがある既存checkoutの実パス>'` の引数を実際のパスに置換して移動する。別 checkout の選択に `chezmoi source-path` は使わない。

移動した後、利用者は下のコード全体を同じ terminal へ貼り付ける。Git root と repository を確認し、検証 branch を fetch して switch する。既存の検証 branch は fast-forward だけで更新する。未コミットの変更や未追跡ファイルがあれば停止するため、利用者が先に既存の作業を保存する。コードは stash や変更の破棄を行わない。

```powershell
. {
    if (-not $IsWindows -or $PSVersionTable.PSVersion -lt [version]'7.3') {
        throw 'Use an ordinary native Windows PowerShell 7.3 or later terminal.'
    }
    $repoRoot = (& git rev-parse --show-toplevel | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { throw 'Current directory is not inside a Git checkout.' }
    $originUrl = (& git -C $repoRoot remote get-url origin | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $originUrl -notmatch '[:/]torumakabe/dotfiles(?:\.git)?/?$') {
        throw 'This is not the expected torumakabe/dotfiles checkout.'
    }
    Set-Location -LiteralPath $repoRoot -ErrorAction Stop
    $checkoutChanges = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the existing checkout.' }
    if ($checkoutChanges.Count) {
        git status --short
        throw 'Save existing checkout changes before fetching and switching the validation branch.'
    }
    $trialBranch = 'validation/windows-uv-cache-trial'
    & git fetch origin "refs/heads/${trialBranch}:refs/remotes/origin/${trialBranch}"
    if ($LASTEXITCODE -ne 0) { throw 'Could not fetch the validation branch.' }
    $localTrialBranch = @(& git branch --list $trialBranch)
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the local validation branch.' }
    if ($localTrialBranch.Count) {
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
    foreach ($relativePath in @(
        'tests\manual\windows\uv-cache-trial\Prepare-UvCacheTrial.ps1',
        'tests\manual\windows\uv-cache-trial\Test-UvCacheSandbox.ps1',
        'docs\windows-uv-cache-trial.md',
        'home\.chezmoitemplates\copilot-user-settings.json'
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $relativePath) -PathType Leaf)) {
            throw "Required file is missing: $relativePath. This checkout or branch does not contain the validation kit."
        }
    }
    Set-Location -LiteralPath $repoRoot -ErrorAction Stop
    $prepareScript = Join-Path $repoRoot 'tests\manual\windows\uv-cache-trial\Prepare-UvCacheTrial.ps1'
    git -C $repoRoot status --short
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the existing checkout.' }
}
```

以降は、この PowerShell terminal を閉じず、cwd を `$repoRoot` のまま保つ。各コードブロックは全体を一度に貼り付ける。先頭の `. { ... }` は現在の session の scope で実行するため、`$repoRoot`、`$prepareScript`、後で設定する `$trialRoot` と `$pwshPath` が親 session に残る。子 scope を作る `& { ... }` に置換したり、新しい terminal を開いたりしない。エラーが出たら次の手順へ進まない。試験データは OS の temporary directory と既存 checkout の外にある利用者 profile 内へ、一意な名前で作る。親 terminal は生成した trial root の実パスを出力する。Copilot sandbox tool では環境変数から root を再計算せず、ここで作った値をそのまま使う。

## 2. 前提ツールと配布済み設定を確認する

利用者は同じ通常 terminal で、対象 CLI の help と hook interpreter の存在を確認する。`python-runtime.env` の `python` と `python_root` は準備スクリプトが読み取るため、架空の interpreter path を指定する必要はない。出力を外部へ貼る前に token や private key がないことを確認する。

設定の source は対象 Windows に配布済みの `settings.json` と `hooks/` である。Guard、uv enforcer、launcher と `python-runtime.env` が必要で、source の uv enforcer が本成果物の既知の cache rewrite branch と一致しなければ準備を停止する。source は sandbox、developer-tool access、working-directory access を有効にし、現在の専用 cache exact write grant を持つこと。

uv の自動 Python download は行わない。`idna==3.10` の取得先に到達できる既存 network policy と package index 設定が必要である。接続制限、TLS、registry の認証問題は cache の不具合と分ける。認証情報や全環境変数は出力しない。

```powershell
. {
    copilot --version
    uv --version
    copilot help environment | Select-String 'COPILOT_HOME'
    copilot config --help
    copilot help sandbox
    Get-Content -LiteralPath "$HOME\.copilot\hooks\python-runtime.env" -ErrorAction Stop |
        Where-Object { $_ -match '^(python|python_root)=' }
}
```

対象 CLI の help が `COPILOT_HOME`、`copilot config sandbox`、`-C`、`--no-auto-update`、`/sandbox` に対応していなければ停止する。`copilot sandbox status` と `copilot sandbox policy` は存在しないため使用しない。

スクリプトは次の2本であり、利用者はこのガイド内のコマンドで実行する。

| スクリプト | 役割 |
|---|---|
| [`Prepare-UvCacheTrial.ps1`](../tests/manual/windows/uv-cache-trial/Prepare-UvCacheTrial.ps1) | 通常 terminal で隔離設定と実値入りプロンプトを作り、control または candidate の CLI を起動する |
| [`Test-UvCacheSandbox.ps1`](../tests/manual/windows/uv-cache-trial/Test-UvCacheSandbox.ps1) | 手順6のプロンプトを受けた Copilot が sandbox 内で cache、rename、uv run、別 tool call からの永続性を検査する |

## 3. 隔離した検証データを準備する

利用者は同じ通常 terminal で一意な trial root を作り、既存 checkout にある準備スクリプトを別の PowerShell child process で起動する。`SourceCopilotHome` は普段の CLI home と一致させる。script は interpreter を `python-runtime.env` から取得し、`Root` が checkout と `%TEMP%` の外にあり、reparse point を通らないことを確認する。repository、既存 cache、OneDrive、network drive、junction 下は試験データの保存先にしない。準備失敗後の半生成 directory は再利用せず、原因を解消して新しい GUID でやり直す。

既存の設定、User/Machine environment、cache は変更しない。execution policy が script を拒否した場合も設定を変更せず停止する。明示 cache 設定が検出された場合は判定を保留する。準備は `UV_CONFIG_FILE`、`UV_NO_CACHE` 等の選択した変数だけの有無と、ancestor `uv.toml` / `pyproject.toml`、`%APPDATA%\uv\uv.toml`、`%PROGRAMDATA%\uv\uv.toml` の `cache-dir` / `no-cache` 宣言を検査する。TOML 検査は保守的な宣言検出であり、他の table の同名 key も停止対象になる。停止したら対象 Copilot が該当 table を確認する。設定を自動削除しない。

準備スクリプトは、複製した `hooks.json` と hook launcher を変更せずに使う。書き換えが必要なのは candidate の `uv-enforcer.py` だけで、既知の cache rewrite 分岐を除く。Guard と uv enforcer の直接実行制限を各コピーで確認し、両条件の設定に同じ分離用 read-only paths を加える。元の `allowBypass` 値はそのまま保つ。配布元ファイル、ACL、他の sandbox 許可は変更しない。準備が途中で失敗した場合は、その root を再利用せず、手順3のコード全体を再実行して新しい GUID の root を作る。

```powershell
. {
    $trialParent = Join-Path $env:LOCALAPPDATA 'CopilotUvCacheTrials'
    if (-not (Test-Path -LiteralPath $trialParent -PathType Container)) {
        New-Item -ItemType Directory -Path $trialParent -ErrorAction Stop | Out-Null
    }
    $trialRoot = Join-Path $trialParent ('trial-' + [guid]::NewGuid().ToString('N'))
    $pwshPath = (Get-Command pwsh.exe -ErrorAction Stop).Source
    & $pwshPath -NoProfile -File $prepareScript -Action Prepare `
        -Root $trialRoot -SourceCopilotHome "$HOME\.copilot"
    if ($LASTEXITCODE -ne 0) { throw 'Trial preparation failed; do not reuse its partial directory.' }
    Write-Output "Trial root for both runs: $trialRoot"
}
```

## 4. control の CLI を起動する

利用者は同じ通常 terminal で下のコードを実行する。準備済みの Root と control を埋め込んだプロンプトを clipboard に入れてから control を起動するため、clipboard の既存内容は置き換わる。Root と Mode の手置換は不要である。必要なら隔離 home で `/login` する。既存 token ファイル、CA private key、plugin state はコピーしない。credential masking により CA の追加承認が必要になっても、検証のために証明書を勝手に trust しない。

子 `pwsh.exe` は checkout root から起動し、準備スクリプトが Copilot CLI を `-C <Root>\workspace` で起動する。Copilot の powershell tool とその probe の cwd は `<Root>\workspace` であり、コードがある checkout とは別である。CLI と子 PowerShell の終了後は、cwd が `$repoRoot` の親 terminal に戻る。親 session の変数は保持される。通常環境の User/Machine environment は変更しない。

```powershell
. {
    $trialPrompt = @(& $pwshPath -NoProfile -File $prepareScript -Action Prompt -Root $trialRoot -Mode control)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the prepared control prompt.' }
    ($trialPrompt -join "`n") | Set-Clipboard -ErrorAction Stop
    & $pwshPath -NoProfile -File $prepareScript -Action Launch -Root $trialRoot -Mode control
    if ($LASTEXITCODE -ne 0) { throw 'Control CLI exited with an error.' }
}
```

## 5. control の sandbox 設定を読み込む

準備スクリプトは CLI の `config sandbox` 出力を元設定と比較し、試験用 `settings.json` が読み込まれたことを確認する。`allowBypass` は利用者の元設定を変更せず、その値を両条件で維持する。CLI の設定表示だけでは、実行中の sandbox 状態や有効な全 policy は確認できない。

runtime backend 名や有効 policy 全体を手入力する必要はなく、未確認でも次の手順で cache 測定を始める。ただし、sandbox 内の実行を別途確認できない結果は sandbox の合格にせず、撤去判断を保留する。

## 6. control の CLI に検証プロンプトを貼る

利用者は手順4で clipboard に入れたプロンプトを、そのまま起動中の control CLI に貼る。通常 terminal には貼らない。Copilot は Step 1 と Step 2 を別々の powershell tool 呼び出しで実行する。生成済み本文は `<Root>\code\control-prompt.txt` にも保存される。

以下は準備スクリプトが読み取るテンプレートである。**以下の本文を直接コピーしない。** スクリプトが Root、Mode、PowerShell のパス引数を実値へ置換する。

<details>
<summary>生成用テンプレート（直接貼り付けない）</summary>

<!-- uv-cache-trial-prompt:start -->
```text
Windows native の uv cache 比較検証を行ってください。
Root: <Root>
Mode: <Mode>

これは試験用 COPILOT_HOME と空の試験 workspace で起動したセッションです。Root は利用者が通常 terminal で生成し、同じ terminal に出力した絶対パスです。Copilot sandbox 内の `$env:LOCALAPPDATA` から Root を再計算しないでください。通常設定、User/Machine environment、repository、既存 cache は変更しないでください。Node hook削除やGuardのenv checker削除、MCP/LSP等を再検証しないでください。

目的は Python/pip 直接実行禁止と Guard を維持し、Windows の `UV_CACHE_DIR` rewrite と専用 cache write grant を candidate から外して uv の動作を比較することです。複製した hook 登録と launcher は元のまま使います。`allowBypass` を含む sandbox 設定も元の値を保ちます。権限変更や bypass を試さず、必要な write grant を追加しないでください。

この CLI の project directory と powershell tool の cwd は <Root>\workspace です。コードを置いた dotfiles checkout ではありません。最初に <Root>\manifest.json、launch.json、cli-configured-sandbox.json を読み、試験条件を確認してください。これらは runtime sandbox の実行証明ではありません。runtime 状態や有効 policy が別途確認できない場合も測定を行い、結果の sandbox 帰属と撤去判断を保留にしてください。sandbox 外で動いたコマンド結果を sandbox の合格にしないでください。

追加のplugin/repository hookやmanaged policyがcontrol/candidateに違いを作る場合は、勝手に解除せず判定保留としてください。target CLIのhelpが計画と異なる場合も未確認optionを発明しないでください。認証は利用者が隔離homeで行います。tokenやprivate keyを読まないでください。

Copilot の powershell tool から以下の Step 1 を実行してください。導入済み PowerShell 7.3 以降の `pwsh.exe` を起動します。通常 terminal や別 tool に切り替えないでください。準備済み Python 絶対パスと `idna==3.10` だけを使い、Python を download しないでください。execution policy は変更しないでください。tool 呼び出しが hook に拒否された場合はその場で停止し、別の手段で実行しないでください。

Step 1 の例:
Set-Location -LiteralPath <WorkspaceLiteral> -ErrorAction Stop
& (Get-Command pwsh.exe -ErrorAction Stop).Source -NoProfile -File <ProbeLiteral> -Root <RootLiteral> -Mode '<Mode>' -Step 1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step 1 が `technical-success` かつ exit 0 の場合だけ、別の powershell tool 呼び出しで Step 2 を実行してください。一つの command や PowerShell process で両方を実行しないでください。

Step 2 の例:
Set-Location -LiteralPath <WorkspaceLiteral> -ErrorAction Stop
& (Get-Command pwsh.exe -ErrorAction Stop).Source -NoProfile -File <ProbeLiteral> -Root <RootLiteral> -Mode '<Mode>' -Step 2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

sandbox 内で `UV_CACHE_DIR` を unset したり `--cache-dir` / `--no-config` を追加したりしないでください。`uv cache clean` や既存 cache の削除もしないでください。script 失敗はそのまま結果として保存し、別構文や別 tool で迂回しないでください。native stderr に credential が含まれる可能性があるため、raw 出力を共有せず script の error 分類を報告してください。

両 step の結果から、同じ cache、marker の永続性、atomic rename、online package metadata の取得と実行、後続 offline 実行、Python prefix が cache 配下であることを報告してください。package が事前 cache にあった可能性を残し、cold と断定しないでください。

candidate cache path が workspace、旧専用 cache、既存 user write grant、TEMP のいずれに入ったかを結果で確認してください。既存 grant で書けた可能性や runtime sandbox の有効性を特定できなければ、上流 cache 許可の効果を確認できたとは扱わず、撤去判断を保留にしてください。`technical-success` は測定コマンドが成功した意味に限り、回避策の撤去可を示しません。

結果は <Root>\workspace\evidence\<Mode>\ に保存します。最後に Mode、OS build、CLI / uv / Python 版、CLI 設定読み込み、実 cache path、各 step の status / exit / error、cross-command の根拠、sandbox 帰属、判定と未確認事項を簡潔に報告してください。control と candidate の両方を測るまで比較全体を完了としないでください。各 CLI を終了し、checkout root の親 terminal に戻って、同じ Root で次の条件を起動してください。repository、通常設定、commit、push、chezmoi apply、現行回避策は変更しないでください。
```
<!-- uv-cache-trial-prompt:end -->

</details>

## 7. candidate を起動して同じ検証を行う

利用者は control の CLI を終了し、checkout root の親 terminal に戻る。下のコードは control と同じ `$trialRoot` を使い、candidate の生成済みプロンプトを clipboard に入れてから CLI を起動する。clipboard の本文をそのまま candidate CLI に貼る。手置換や手順の追加は不要である。candidate の終了後も、同じ親 terminal の checkout root に戻る。

```powershell
. {
    $trialPrompt = @(& $pwshPath -NoProfile -File $prepareScript -Action Prompt -Root $trialRoot -Mode candidate)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the prepared candidate prompt.' }
    ($trialPrompt -join "`n") | Set-Clipboard -ErrorAction Stop
    & $pwshPath -NoProfile -File $prepareScript -Action Launch -Root $trialRoot -Mode candidate
    if ($LASTEXITCODE -ne 0) { throw 'Candidate CLI exited with an error.' }
}
```

## 8. 結果を比較して検証データを片付ける

Step 1 は `uv cache dir`、cache 下の新規専用 directory への作成と同 directory 内 atomic rename、`uv run --no-project --isolated --no-python-downloads --python <既存絶対パス> --with idna==3.10 --refresh-package idna python -c <検証code>` を行う。refresh はこの package の metadata に限定し、cache 全体を消去しない。package が元から cache にあった可能性は残るため、cold cache の証拠とはしない。

Step 2 は前の cache path と marker を確認し、別の atomic rename を行った後、同じ package 実行を `--offline` で行う。Copilot は Step 1 と Step 2 を別々の powershell tool 呼び出しで実行し、会話の tool call 履歴で別呼び出しであることを確認する。一つの shell process 内で連続実行した結果は無効である。

Python payload は実際の run 環境内から同じ uv の `cache dir`、Python prefix、idna の版を返す。prefix が対象 cache の外なら失敗する。candidate が cwd に fallback したり、旧 cache や既存 user write grant に入った場合も合格にしない。sandbox 内では `UV_CACHE_DIR` を unset せず、`--cache-dir` / `--no-config` も付けない。自動注入された `UV_CACHE_DIR` は観測対象である。

`manifest.json` は `<Root>\manifest.json` に保存する。条件別の `cli-configured-sandbox.json`、`launch.json`、`step-1.json`、`step-2.json` は `<Root>\workspace\evidence\control\` と `<Root>\workspace\evidence\candidate\` に保存する。結果は checkout 内には作らない。configured snapshot には元設定から必要な sandbox flags と filesystem paths だけを保存し、proxy credential や全環境は記録しない。native error は raw stderr の代わりに exit code と分類を保存する。各 step は成功時 0、失敗時 1 を返す。`technical-success` は測定コマンドが成功したことを示すが、sandbox 内で実行された証拠にはならない。

| 結果 | 判定 |
|---|---|
| control / candidate とも 2 回成功。candidate cache は旧専用 grant 外で、既存の user write grant にも覆われていない。runtime sandbox が実行に適用された証拠がある | 対象 CLI / Windows build で撤去候補。別途 dotfiles 撤去を承認する |
| control 成功、candidate の cache 作成 / rename / uv cache 書き込み失敗 | 現環境では回避策を維持。失敗 stage と exit / error を報告 |
| control 失敗 | 比較基準が成立していない。network / Python / hook / policy 問題を分離 |
| 同一 cache / marker を次の別 tool call で読めない、offline 実行失敗 | 永続性または package 再利用の条件不成立。撤去しない |
| 明示 cache 設定、candidate cache が旧 grant / user write grant / workspace 内、candidate cache が TEMP 内、runtime sandbox の適用が未確認 | 判定保留。書き込み成功だけでは upstream cache 機能に帰属させない |

検証後は利用者が記録を保存し、各 `probeOwnedDirectory` に本試験のファイルだけがあることを確認して、その明示された directory だけを削除する。既存 cache の親 directory や内容は削除しない。trial directory には隔離 login の資格情報や CA が含まれる場合があるため、共有しない。共有するのは review 済みの最小 JSON と測定要約だけにする。

## 比較条件の詳細

| 条件 | control | candidate |
|---|---|---|
| Guard と Python / pip 直接実行拒否 | 複製した同じ実装 | 同じ Guard。uv の cache rewrite branch だけを除く |
| CLI 親 process の `UV_CACHE_DIR` | なし | なし |
| 補助環境変数 | 現行専用 cache を設定 | 親 process から除外 |
| 専用 cache exact write grant | 保持 | 除外。別の重複 grant があれば停止 |
| 他の filesystem / network / MCP / LSP 設定 | source を保持 | 同じ |
| sandbox bypass | 元設定を保持 | 元設定を保持 |
| 隔離 code、hook、interpreter の read grant | 両条件に同じ目的の RO grant | 同じ |

準備で追加する RO grant は隔離 home、code、manifest、既存 managed Python root に限る。試験 workspace は既存 `addCurrentWorkingDirectory` で書き込める。candidate cache に新しい write grant を追加しない。既存の broad user / managed grant、workspace、TEMP の許可で cache が書ける場合は、その成功だけで upstream cache grant による成功としない。

## 根拠と未確認事項

[github/copilot-agent-runtime#18974](https://github.com/github/copilot-agent-runtime/issues/18974) は 2026-10-12 に completed で closed になった。[maintainer comment](https://github.com/github/copilot-agent-runtime/issues/18974#issuecomment-6119987639) と [v1.0.92 release note](https://github.com/github/copilot-cli/releases/tag/v1.0.92) は Windows TEMP/TMP rename 修正と、developer-tool access 有効時の uv writable cache を説明している。[github/copilot-agent-runtime#25725](https://github.com/github/copilot-agent-runtime/pull/25725) は 2026-10-09 に merge され、Windows の安定した Copilot-owned cache と明示設定、hook override の尊重を実装した。対象 CLI にこの PR が含まれるかは、版と配布経緯から別途確認する。[github/copilot-agent-runtime#24537](https://github.com/github/copilot-agent-runtime/issues/24537) は 2026-10-01 更新の open issue であり、これだけでは上記修正を未解消とは判定できない。

作成側では CLI の help で `COPILOT_HOME`、`copilot config sandbox`、`-C`、`--no-auto-update`、`/sandbox` を確認した。Windows 実機の動作確認は未実施である。uv 設定ファイルの探索場所は [uv configuration documentation](https://docs.astral.sh/uv/concepts/configuration-files/) に基づく。
