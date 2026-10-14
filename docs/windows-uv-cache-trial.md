# Windows uv cache 回避策の比較検証

利用者が用意する Windows native 環境で、Copilot sandbox の上流機能だけで uv cache の書き込みと rename が成功するかを確認する。Python / pip の直接実行を拒否する uv enforcer と Guard は維持する。成功しても、この検証だけで回避策の撤去や dotfiles の適用を承認したことにはならない。

現行の cache 注入と専用 write grant を保持する **control** と、隔離設定からそれらだけを外す **candidate** を比較する。

利用者は Windows の通常の PowerShell 7.3 以降の terminal を開き、この検証コードが存在する dotfiles checkout のルートへ移動して開始する。Copilot の shell tool では開始しない。

この検証キットは `validation/windows-uv-cache-trial` branch から取得する。対象 Windows では同 branch のファイルがある既存 checkout を使う。手順1は別 repository や検証キットのない branch を検出して停止する。

導入済み Copilot CLI と uv、dotfiles が provision 済みの hook interpreter が必要である。本検証キットは Windows で動作検証していない。このガイドを上から順に読み、手順6のプロンプトまで同じ文書内で進める。スクリプト本文を読む必要はない。

## 1. 既存 checkout に移動して開始位置を確認する

利用者が chezmoi の既存 source directory を使う場合に限り、通常の PowerShell terminal で `Set-Location -LiteralPath (chezmoi source-path)` を実行する。この repository では source directory が checkout 内の `home/` を指す場合があるため、下のコードで Git root へ移動する。別の既存 checkout を使う場合は、`Set-Location -LiteralPath '<検証コードがある既存checkoutの実パス>'` の引数を実際のパスに置換して移動する。別 checkout の選択に `chezmoi source-path` は使わない。

移動した後、利用者は最初に下のコード全体を同じ terminal へ貼り付ける。Git root、repository の識別、検証ファイルを確認し、branch は切り替えない。未コミットの変更は `git status --short` で確認し、検証対象の変更と区別する。

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
    foreach ($relativePath in @(
        'tests\manual\windows\uv-cache-trial\Prepare-UvCacheTrial.ps1',
        'tests\manual\windows\uv-cache-trial\Trace-UvCacheHook.ps1',
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

スクリプトは次の3本であり、利用者はこのガイド内のコマンドで実行する。

| スクリプト | 役割 |
|---|---|
| [`Prepare-UvCacheTrial.ps1`](../tests/manual/windows/uv-cache-trial/Prepare-UvCacheTrial.ps1) | 通常 terminal で隔離設定を作り、control または candidate の CLI を起動する |
| [`Trace-UvCacheHook.ps1`](../tests/manual/windows/uv-cache-trial/Trace-UvCacheHook.ps1) | 複製した hook の結果を変えずに返し、script の hash と rewrite 有無だけを記録する。利用者による直接実行は不要 |
| [`Test-UvCacheSandbox.ps1`](../tests/manual/windows/uv-cache-trial/Test-UvCacheSandbox.ps1) | 手順6のプロンプトを受けた Copilot が sandbox 内で cache、rename、uv run、別 tool call からの永続性を検査する |

## 3. 隔離した検証データを準備する

利用者は同じ通常 terminal で一意な trial root を作り、既存 checkout にある準備スクリプトを別の PowerShell child process で起動する。`SourceCopilotHome` は普段の CLI home と一致させる。script は interpreter を `python-runtime.env` から取得し、`Root` が checkout と `%TEMP%` の外にあり、reparse point を通らないことを確認する。repository、既存 cache、OneDrive、network drive、junction 下は試験データの保存先にしない。準備失敗後の半生成 directory は再利用せず、原因を解消して新しい GUID でやり直す。

既存の設定、User/Machine environment、cache は変更しない。execution policy が script を拒否した場合も設定を変更せず停止する。明示 cache 設定が検出された場合は判定を保留する。準備は `UV_CONFIG_FILE`、`UV_NO_CACHE` 等の選択した変数だけの有無と、ancestor `uv.toml` / `pyproject.toml`、`%APPDATA%\uv\uv.toml`、`%PROGRAMDATA%\uv\uv.toml` の `cache-dir` / `no-cache` 宣言を検査する。TOML 検査は保守的な宣言検出であり、他の table の同名 key も停止対象になる。停止したら対象 Copilot が該当 table を確認する。設定を自動削除しない。

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

利用者は同じ通常 terminal で control を起動し、必要なら隔離 home で `/login` する。既存 token ファイル、CA private key、plugin state はコピーしない。credential masking により CA の追加承認が必要になっても、検証のために証明書を勝手に trust しない。

子 `pwsh.exe` は checkout root から起動し、準備スクリプトが Copilot CLI を `-C <Root>\workspace` で起動する。Copilot の powershell tool とその probe の cwd は `<Root>\workspace` であり、コードがある checkout とは別である。CLI と子 PowerShell の終了後は、cwd が `$repoRoot` の親 terminal に戻る。親 session の変数は保持される。通常環境の User/Machine environment は変更しない。

```powershell
. {
    & $pwshPath -NoProfile -File $prepareScript -Action Launch -Root $trialRoot -Mode control
    if ($LASTEXITCODE -ne 0) { throw 'Control CLI exited with an error.' }
}
```

## 5. control の sandbox 状態を確認する

利用者は起動した control CLI で `/sandbox` の現在の状態と policy を確認する。native Windows backend が使われ、sandbox 有効、bypass 不可、developer-tool access 有効であること、試験用 settings を読んでいることを確認する。managed policy や追加 hook の影響も記録する。設定変更はしない。runtime 表示を観測できなければ未確認として停止する。`cli-configured-sandbox.json` は設定読み込みの証拠であって、runtime policy の証拠ではない。

手順6のプロンプトを受けた Copilot は、この実際の観測から `<Root>\workspace\evidence\control\sandbox-observation.json` を作る。candidate では同じ `<Root>` の `candidate` directory に作る。利用者しか観測できない UI は利用者に操作を依頼する。下の形の true は例であり、観測せずコピーしてはならない。

```json
{
  "runtimeEnabledObserved": true,
  "bypassDisabledObserved": true,
  "devToolAccessObserved": true,
  "isolatedHomeObserved": true,
  "policyReviewed": true,
  "backendObserved": "画面に表示された実際のWindows backend名",
  "observationReference": "利用者のsandbox表示確認、時刻、または保存した診断への参照"
}
```

## 6. control の CLI に検証プロンプトを貼る

利用者は以下の本文の `<Root>` を手順3で出力した実際の絶対パスへ、`<Mode>` を `control` へ置換し、起動中の control CLI に貼る。`$trialRoot` という文字列をそのまま貼るのではない。通常 terminal には貼らない。Copilot は Step 1 と Step 2 を別々の powershell tool 呼び出しで実行する。

```text
Windows native の uv cache 比較検証を行ってください。
Root: <Root> （通常 terminal で表示された `$trialRoot` の値）
Mode: <Mode> （control または candidate）

これは試験用 COPILOT_HOME と空の試験 workspace で起動したセッションです。Root は利用者が通常 terminal で生成し、同じ terminal に出力した絶対パスです。Copilot sandbox 内の `$env:LOCALAPPDATA` から Root を再計算しないでください。通常設定、User/Machine environment、repository、既存 cache は変更しないでください。Node hook削除やGuardのenv checker削除、MCP/LSP等を再検証しないでください。

目的は Python/pip 直接実行禁止とGuardを維持し、Windows UV_CACHE_DIR rewriteと専用cache/grantなしで上流sandboxがuvを動かせるかを比較することです。準備scriptが除いたcache rewrite以外にhookを変更したり、Guardを解除したりしないでください。bypassは試験設定で禁止されています。permission denyやhook askが出たら迂回せず、必要な具体的承認を利用者へ提示してください。新しいwrite grantは追加しないでください。

このCLIのproject directoryとpowershell toolのcwdは <Root>\workspace です。コードを置いたdotfiles checkoutではありません。まず <Root>\manifest.json と <Root>\workspace\evidence\<Mode>\launch.json、cli-configured-sandbox.json を読んで設定読み込みを確認してください。これをruntime sandbox有効の証拠と取り違えないでください。利用者の /sandbox 表示、runtime policy、実backend、dev-tool access、bypass不可の観測を確認し、<Root>\workspace\evidence\<Mode>\sandbox-observation.json に実際の観測を記録してください。観測できないflagをtrueで埋めないでください。利用者しか操作できない表示は利用者へ操作を依頼し、結果を待ってください。存在しない copilot sandbox status / policy サブコマンドは使わないでください。

追加のplugin/repository hookやmanaged policyがcontrol/candidateに違いを作る場合は、勝手に解除せず判定保留としてください。target CLIのhelpが計画と異なる場合も未確認optionを発明しないでください。認証は利用者が隔離homeで行います。tokenやprivate keyを読まないでください。

runtime条件が確認できたら、Copilotのpowershell toolで以下のStep 1を実行してください。導入済みPowerShell 7.3以降のpwsh.exeをsandbox toolの子processとして起動します。外部terminalへ移さないでください。準備済みPython絶対パスとidna==3.10だけを使い、Pythonをdownloadしないでください。execution policyの変更や-ExecutionPolicy Bypassは使わないでください。

Step 1 の例:
Set-Location -LiteralPath '<Root>\workspace' -ErrorAction Stop
& (Get-Command pwsh.exe -ErrorAction Stop).Source -NoProfile -File '<Root>\code\Test-UvCacheSandbox.ps1' -Root '<Root>' -Mode '<Mode>' -Step 1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Step 1がtechnical-successかつexit 0の場合だけ、別の新しいpowershell tool呼び出しでStep 2を実行してください。一つのcommandで両方を実行せず、1つのPowerShell process内の反復をcross-command試験と呼ばないでください。

Step 2 の例:
Set-Location -LiteralPath '<Root>\workspace' -ErrorAction Stop
& (Get-Command pwsh.exe -ErrorAction Stop).Source -NoProfile -File '<Root>\code\Test-UvCacheSandbox.ps1' -Root '<Root>' -Mode '<Mode>' -Step 2
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

sandbox内でUV_CACHE_DIRをunsetしたり--cache-dir / --no-configを追加したりしないでください。uv cache cleanや既存cacheの削除もしないでください。script失敗はそのまま結果として保存し、別構文や別toolで迂回しないでください。native stderrにcredentialが含まれる可能性があるため、raw出力を共有せずscriptのerror分類を報告してください。

二回の結果とhook-events.jsonlから、Guard/uv hookの実行hash、candidate modifiedArgs/cachePrefixなし、同じcache、marker永続性、atomic rename、オンラインpackage metadata更新/実行と後続offline実行、実際のPython prefixがcache配下であることを確認してください。packageが事前cacheにあった可能性を残し、coldと断定しないでください。

candidateのcache pathをruntime effective policyと照合してください。旧exact grant以外のbroad user/managed grant、workspaceやTEMPの一般許可だけで書けているなら上流dev-tool cache修正による成功とは断定せず、判定保留としてください。technical-successだけでは撤去可と判定しないでください。

結果は <Root>\workspace\evidence\<Mode>\ にあります。最後にMode、OS build、実CLI/uv/Python版、設定読み込みとruntime観測、実cache path、hook rewrite、各stepのstatus/exit/error、cross-command根拠、判定と未確認事項を簡潔に報告してください。controlとcandidate両方を測るまで比較全体を完了としないでください。利用者は各CLIを終了して元のcheckout rootにある親terminalへ戻り、同じRootで次の条件を起動します。リポジトリ編集、commit、push、chezmoi apply、現行回避策の撤去はしないでください。
```

## 7. candidate を起動して同じ検証を行う

利用者は control の CLI を終了し、checkout root の親 terminal に戻る。下のコードで保存済みの `$trialRoot` を指定して candidate を起動する。手順5の状態確認を candidate に対して行い、手順6の同じプロンプト本文を再利用する。`<Root>` は control と同じ実パス、`<Mode>` だけを `candidate` に置換して candidate CLI に貼る。candidate 用 observation は別ファイルに保存する。candidate の終了後も、同じ親 terminal の checkout root に戻る。

```powershell
. {
    & $pwshPath -NoProfile -File $prepareScript -Action Launch -Root $trialRoot -Mode candidate
    if ($LASTEXITCODE -ne 0) { throw 'Candidate CLI exited with an error.' }
}
```

## 8. 結果を比較して検証データを片付ける

Step 1 は `uv cache dir`、cache 下の新規専用 directory への作成と同 directory 内 atomic rename、`uv run --no-project --isolated --no-python-downloads --python <既存絶対パス> --with idna==3.10 --refresh-package idna python -c <検証code>` を行う。refresh はこの package の metadata に限定し、cache 全体を消去しない。package が元から cache にあった可能性は残るため、cold cache の証拠とはしない。

Step 2 は前の cache path と marker を確認し、別の atomic rename を行った後、同じ package 実行を `--offline` で行う。二つの powershell tool 呼び出しが独立していることは会話の tool call と `hook-events.jsonl` も使って確認する。一つの shell process 内で連続実行した結果は無効である。

Python payload は実際の run 環境内から同じ uv の `cache dir`、Python prefix、idna の版を返す。prefix が対象 cache の外なら失敗する。candidate が cwd に fallback したり、旧 cache や既存 user write grant に入った場合も合格にしない。sandbox 内では `UV_CACHE_DIR` を unset せず、`--cache-dir` / `--no-config` も付けない。自動注入された `UV_CACHE_DIR` は観測対象である。

`manifest.json` は `<Root>\manifest.json` に保存する。条件別の `cli-configured-sandbox.json`、`launch.json`、`sandbox-observation.json`、`hook-events.jsonl`、`step-1.json`、`step-2.json` は `<Root>\workspace\evidence\control\` と `<Root>\workspace\evidence\candidate\` に保存する。結果は checkout 内には作らない。configured snapshot には sandbox の relevant flags と filesystem paths だけを保存し、proxy credential や全環境を記録しない。native error は raw stderr の代わりに exit code と分類を保存する。各 step は成功時 0、失敗時 1 を返す。`technical-success` は測定項目の成功であり、撤去可の自動判定ではない。

| 結果 | 判定 |
|---|---|
| control / candidate とも 2 回成功。candidate rewrite なし、旧 grant なし。runtime policy の automatic dev-tool cache が実 cache に適用され、他の writable grant による成功ではない | 対象 CLI / Windows build で撤去候補。別途 dotfiles 撤去を承認する |
| control 成功、candidate の cache 作成 / rename / uv cache 書き込み失敗 | 現環境では回避策を維持。失敗 stage と exit / error を報告 |
| control 失敗 | 比較基準が成立していない。network / Python / hook / policy 問題を分離 |
| 同一 cache / marker を次の別 tool call で読めない、offline 実行失敗 | 永続性または package 再利用の条件不成立。撤去しない |
| 明示 cache 設定、bypass、追加 grant、cwd fallback、runtime policy 未確認、candidate cache が単に TEMP grant 内 | 判定保留。書き込み成功だけでは upstream cache 機能に帰属させない |

検証後は利用者が記録を保存し、各 `probeOwnedDirectory` に本試験のファイルだけがあることを確認して、その明示された directory だけを削除する。既存 cache の親 directory や内容は削除しない。trial directory には隔離 login の資格情報や CA が含まれる場合があるため、共有しない。共有するのは review 済みの最小 JSON と測定要約だけにする。

## 比較条件の詳細

| 条件 | control | candidate |
|---|---|---|
| Guard と Python / pip 直接実行拒否 | 複製した同じ実装 | 同じ Guard。uv の cache rewrite branch だけを除く |
| CLI 親 process の `UV_CACHE_DIR` | なし | なし |
| 補助環境変数 | 現行専用 cache を設定 | 親 process から除外 |
| 専用 cache exact write grant | 保持 | 除外。別の重複 grant があれば停止 |
| 他の filesystem / network / MCP / LSP 設定 | source を保持 | 同じ |
| sandbox bypass | 試験設定だけ false | 同じ |
| 隔離 code、hook、interpreter の read grant | 両条件に同じ目的の RO grant | 同じ |

準備で追加する RO grant は隔離 home、code、manifest、既存 managed Python root に限る。試験 workspace は既存 `addCurrentWorkingDirectory` で書き込める。candidate cache に新しい write grant を追加しない。既存の broad user / managed grant、workspace、TEMP の許可で cache が書ける場合は、その成功だけで upstream cache grant による成功としない。

## 根拠と未確認事項

[github/copilot-agent-runtime#18974](https://github.com/github/copilot-agent-runtime/issues/18974) は 2026-10-12 に completed で closed になった。[maintainer comment](https://github.com/github/copilot-agent-runtime/issues/18974#issuecomment-6119987639) と [v1.0.92 release note](https://github.com/github/copilot-cli/releases/tag/v1.0.92) は Windows TEMP/TMP rename 修正と、developer-tool access 有効時の uv writable cache を説明している。[github/copilot-agent-runtime#25725](https://github.com/github/copilot-agent-runtime/pull/25725) は 2026-10-09 に merge され、Windows の安定した Copilot-owned cache と明示設定、hook override の尊重を実装した。対象 CLI にこの PR が含まれるかは、版と配布経緯から別途確認する。[github/copilot-agent-runtime#24537](https://github.com/github/copilot-agent-runtime/issues/24537) は 2026-10-01 更新の open issue であり、これだけでは上記修正を未解消とは判定できない。

作成側では CLI の help で `COPILOT_HOME`、`copilot config sandbox`、`-C`、`--no-auto-update`、`/sandbox` を確認した。Windows 実機の動作確認は未実施である。uv 設定ファイルの探索場所は [uv configuration documentation](https://docs.astral.sh/uv/concepts/configuration-files/) に基づく。
