# Windowsのuv復元用fixture試験とホスト移行手順

この試験は、通常のmise、uv、profile、PATH、認証設定を変更しない。全件実行では専用ディレクトリ内の80ケースと5件の静的検査で、元オブジェクトの退避と復帰、中断からの復旧、NTFSの属性、拒否処理を確認する。実際のパッケージ導入や移行は実行しない。

`windows-uv.ps1`は試験対象の関数と、固定したGitコミットを入力とする移行の入口を提供する。**実環境でのInstall、Apply、Restoreは未実施であり、各操作には利用者の承認が必要である。** この手順の整備やfixtureの成功を実移行の承認として扱わない。Prepareも新しいバックアップ領域へ書き込む操作として承認範囲を確認する。

導入、設定変更、更新、バックアップ、復元とfixtureは、Copilot sandboxの外にある通常権限のWindows PowerShellで行う。導入済みツールを使うワークロードの受け入れはsandbox内で行い、両者の結果を分けて記録する。sandboxやCopilotの設定を無効化しない。

## 通常権限で確認する範囲

変更対象の元ファイルと元ディレクトリは、同一のローカル固定NTFSボリューム内で`retained-<nonce>`へrenameして保持する。復元はそのオブジェクトを元のパスへrenameする。元オブジェクトと退避中のオブジェクトに`Set-Acl`やメタデータの書き直しは行わず、コピーから再構築しない。renameにはコピーへのフォールバックや既存オブジェクトの上書きを許可しない。

対象ツリー内のファイルとディレクトリについて、ボリュームシリアル番号とファイルIDを観測し、復帰後も同じIDであることを確認する。通常権限で読めるDACL、owner、group、ファイル内容のSHA-256、属性、作成日時、最終更新日時も比較する。同じ内容の別オブジェクトを置かれてもIDが異なるため拒否する。最終アクセス日時と対象の親ディレクトリの日時は比較対象外である。

**SACLは`unobserved`（未観測）と記録する。** 通常権限ではSACLの有無も退避前後の一致も測定しない。`Get-Acl -Audit`、権限の有効化、昇格は行わず、セキュリティ記述子全体を検証したとは扱わない。同じオブジェクトを戻す方式であり、SACLだけの並行変更を検出できるという保証はない。通常の観測項目を読み取れない場合は停止する。

候補は新しいオブジェクトとして作り、そのSACLには作成先での継承規則が適用される。コピー処理が再現するのは観測したDACL、owner、groupと通常のメタデータであり、元のSACLは候補へコピーしない。公開前の候補は対象の親ディレクトリ内に作る。**候補が有効な間のオブジェクト固有の監査設定の維持は保証しない。** この制約を受け入れられない対象へは適用できない。

コピーとの比較では、異なるファイルIDに加えて、DACL制御フラグの`AI`（`SE_DACL_AUTO_INHERITED`）だけを比較対象外とする。[WindowsがACLへ現在の自動継承モデルを適用すると、このフラグを設定する](https://learn.microsoft.com/en-us/windows/win32/secauthz/automatic-propagation-of-inheritable-aces)ためである。owner、group、ACEの内容と順序、ACEごとの継承フラグ、DACLの`P`と`AR`、通常メタデータは引き続き比較する。比較用の複製だけを変換し、snapshotとplan、journalには実際に観測したSDDLを保存する。元オブジェクトの変更検出とrename前後、復元後の照合では`AI`も含めた一致を要求する。候補と元の違いがIDと`AI`だけなら、その対象は置換しない。コピー不一致のエラーには項目名を含め、設定本文、ハッシュ値、SDDL本文は出力しない。

既存ファイルを別のファイルで置き換える場合は、候補側の作成日時を元ファイルと一致させてからplanへ記録する。NTFSが同じ名前の新ファイルへ以前の作成日時を引き継ぐ動作（timestamp tunneling）によって、公開直後の候補を未知の変更と誤判定することを防ぐ。元ファイルの日時は書き換えない。日時の異なる未調整の候補は、元ファイルを動かす前に拒否する。

`observations/`内のコピーは変更検出と隔離インストーラー用の入力であり、監査情報まで含むバックアップでも復元元でもない。復元はインストーラーの作業領域やコピーが使えなくても、保存済みのsnapshot、plan、journalと退避した元オブジェクトで行う。旧コピー方式のsnapshot（schema 1）との互換性はない。

## 中断時の動作

対象ごとに、退避先、候補のステージング先、候補の退避先、実際に公開する候補のIDをjournalへ保存してから元オブジェクトを動かす。journalはファイルをflushした後、置換を伴うrenameで更新する。復元を選んだ場合も、復元元と復元する意図を保存してから動かす。処理完了後も元オブジェクトと保存先の関連付けを消さない。

| 中断した状態 | Restoreの動作 |
|---|---|
| 元オブジェクトをまだ動かしていない | 元のパスを変更しない |
| 元オブジェクトを退避済みで、候補は未公開 | 候補を公開せず、元オブジェクトを戻す |
| 候補を公開済み | 既知の候補を`candidate-<nonce>`へ退避し、元オブジェクトを戻す |
| 復元途中で候補を退避済み | 残る元オブジェクトのrenameだけを行う |
| 復元済み | IDと観測項目を照合する。オブジェクトの移動やjournalの再書き込みは行わない |

元が存在しなかった対象は、既知の候補を退避して不存在へ戻す。候補も不存在なら何もしない。観測項目が元と同じ候補では元オブジェクトを動かさない。未知の内容やID、退避元の欠落、journalと矛盾する配置があれば、コピーによる代用や再基準化はせず停止する。

書き込み元の停止が前提であり、全対象の事前確認と各renameの前後で変更を確認する。複数オブジェクトを一括更新するトランザクションや、並行書き込み、電源断、ストレージ故障への完全な保護ではない。試験はjournalの再読み込みとrename前後の例外による中断を扱う。journal保存前の中断では、未使用のステージングコピーが残ることがある。結果、退避物、コピーは自動削除せず保持する。

reparse point、hardlink、ADS、readonly、sparse、compressed、encryptedは引き続き対象外とする。試験を通すために既存対象の属性やACLを変更しない。

## リモートブランチから取得する

通常のPowerShell 7.6以上とGitを使う。管理者として開き直さない。対象はユーザープロファイル配下のローカルNTFSにあるdotfilesリポジトリとする。共有フォルダーやreparse pointを含む保存先は対象外である。

公開済みの完全なコミットSHAが別途提示され、fixture試験またはホストでのPrepareを依頼された後に以下を実行する。この文書の改訂だけを再実行の依頼と解釈しない。Prepare用のSHAは、このGit入力対応を含む改訂の公開後に指定する。旧入口のSHAは代用できない。追跡ファイルの未コミット変更や、試験結果以外の未追跡ファイルがあれば停止し、既存の変更を退避、削除、上書きしない。元のブランチにはこの試験用の`.gitignore`がない場合があるため、保持した`native-result-<番号>/`内の未追跡ファイルだけを取得前の停止条件から除く。

```powershell
$branch = 'torumakabe-mise-shim-issues'
$expected = '<依頼文の40文字のコミットSHA>'
if ($expected -notmatch '^[0-9a-f]{40}$') { throw '完全なコミットSHAを指定してください。' }
$repo = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) { throw 'dotfilesリポジトリ内で実行してください。' }
$previous = git symbolic-ref --quiet --short HEAD
$wasDetached = $LASTEXITCODE -eq 1
if ($wasDetached) { $previous = git rev-parse HEAD }
if ($LASTEXITCODE -ne 0) { throw '現在のブランチまたはコミットを取得できません。' }
$changes = @(git status --porcelain=v1 --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $changes.Count -ne 0) { throw '追跡ファイルに未コミット変更があります。ここで停止してください。' }
$untracked = @(git ls-files --others --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw '未追跡ファイルを取得できません。' }
$unexpected = @($untracked | Where-Object { $_ -cnotmatch '^tests/manual/windows-uv/native-result-[0-9]{2,}/' })
if ($unexpected.Count -ne 0) { throw '試験結果以外の未追跡ファイルがあります。ここで停止してください。' }
git fetch origin $branch
if ($LASTEXITCODE -ne 0) { throw 'fetchに失敗しました。' }
$fetched = git rev-parse FETCH_HEAD
if ($LASTEXITCODE -ne 0 -or $fetched -cne $expected) { throw '取得したコミットが依頼文と一致しません。' }
git switch --detach $expected
if ($LASTEXITCODE -ne 0) { throw 'コミットの切り替えに失敗しました。' }
```

既存のchezmoiソース内で実行する場合も、`chezmoi apply`は行わない。

## fixtureだけを実行する

上のPowerShellセッションを使って、一度だけ実行する。

```powershell
$runner = Join-Path $repo 'tests\manual\windows-uv\run-native-fixture.ps1'
pwsh -NoLogo -NoProfile -NonInteractive -File $runner -ExpectedCommit $expected -ResultDirectory native-result-02
$fixtureExit = $LASTEXITCODE
Write-Host "Fixture exit code: $fixtureExit"
```

入口はコミットSHAと作業ツリーの状態を確認する。出力名は明示指定し、既存の結果ディレクトリへの実行を拒否する。旧版の`native-result-01`は保持し、削除も上書きもしない。旧版の`audit-read-preflight`での`BLOCKED`はfixture開始前の停止であり、fixtureの失敗として扱わない。この改訂の結果は別に記録する。

試験は`native-result-02\fixture`内にケース別の対象を作る。拒否の確認用に、同じfixture内のjunction、hardlink、ADS、readonlyファイルも作る。昇格、実行ポリシーの変更、bypassで試験を通さない。Windows以外では終了コード2で停止し、結果ディレクトリもfixtureも作らない。

### 停止したケースを限定して調べる

依頼文で限定実行が指定された場合は、全件実行の代わりに`-CaseName`へケース名を完全一致で渡す。たとえば、元が不存在の対象を公開した直後に中断し、復元するケースは次のとおり。`native-result-01`と`native-result-02`は変更せず、新しい結果名を使う。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File $runner -ExpectedCommit $expected -ResultDirectory native-result-03 -CaseName 'absence interruption absent/file apply after-move-1'
```

指定した1ケースと静的検査5件だけを実行し、`selectedCase`を結果へ記録する。不明なケース名は失敗として扱う。限定実行のPASSは全件の成功や以前の失敗原因の解消を示すものではない。同じ失敗を再現できなければ、その事実を報告する。

journal置換が失敗した場合は、ネイティブ呼び出しの直後に取得したWindowsエラーコード、操作名、置換元と置換先を`nativeError`へ記録する。失敗したケース名は`failedCase`に残す。子プロセスの終了コードが非ゼロでも、生成済みのJSONは`result.json`の`native`へ含める。中断を注入する試験中も、別のWindowsエラーを期待した中断として受け入れず、そのエラーで停止する。元のjournalと未公開の更新用ファイルを保持し、再試行や権限変更はしない。Windowsエラーコードがない旧ログから、共有違反やアクセス拒否を推定して対処しない。

## 結果を返して元のブランチへ戻る

`PASS`、`FAIL`、`BLOCKED`の表示と、次のファイルを依頼元セッションへ返す。通常設定や認証情報、HOME全体は送らない。ファイルはGit管理対象外であり、commitやpushは行わない。

- `tests/manual/windows-uv/native-result-02/result.json`
- 存在する場合は同ディレクトリの`native.stdout.json`と`native.stderr.txt`

限定実行では、上のパスの`native-result-02`を指定した結果名（例: `native-result-03`）に読み替える。

結果を回収した後、上で記録したブランチまたはコミットへ戻す。途中でPowerShellを閉じた場合は、元の値を確認してから戻す。推測したブランチへ切り替えない。

```powershell
if ($wasDetached) { git switch --detach $previous }
else { git switch $previous }
if ($LASTEXITCODE -ne 0) { throw '元のブランチへ戻せません。強制切り替えせず、結果とともに知らせてください。' }
```

結果とfixtureは回収後も保持する。失敗後の再実行や通常環境への移行は、依頼元が結果を確認するまで行わない。

## ホストでの準備と段階別の実行

以下は承認後に使う手順であり、一括実行するスクリプトではない。取得するのは上記のリモートブランチと固定した完全SHAであり、ZIPやアーカイブは使わない。SourceはGitルートそのものを指定する。入口はHEADの一致と、追跡済みおよび未追跡の変更がないことをバックアップ作成前とPrepare完了直前に確認し、検証済みSHAをsnapshotの`sourceCommit`へ保存する。保持した`native-result-*`は既存の`.gitignore`に従って除外する。入口はブランチの切り替えや既存変更の処理を行わない。

### 対象と保存先を確認する

mise、chezmoi、uv、設定を開いているエディター、バックグラウンドジョブなど、対象を書き換えるプロセスを停止する。各段階で停止状態を維持し、`-WritersStopped`はその確認後にだけ指定する。

ソースはWindowsで実際に使っている`C:\Users\tomakabe\.local\share\chezmoi`のGitルートを確認して使う。config、data、cacheは既定パスから推測しない。通常権限のPowerShell 7.6以上で、次のように実行ファイルと実際のパスだけを調べる。`$privateParent`には、リポジトリやmise管理領域の外にある既存の非共有ディレクトリを指定する。ユーザープロファイル配下で、対象と同じローカル固定NTFSボリュームにあり、他ユーザーに変更権限を与えていないことを確認する。ACLを広げて検査を通さない。

```powershell
$ErrorActionPreference = 'Stop'
$privateParent = '<確認済みの既存の非共有ディレクトリの絶対パス>'
Set-Location -LiteralPath $privateParent
$miseExe = (Get-Command mise -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
$chezmoiExe = (Get-Command chezmoi -CommandType Application -TotalCount 1 -ErrorAction Stop).Source
$overrides = @(Get-ChildItem Env:MISE_* | Where-Object {
    -not ($_.Name -ieq 'MISE_SHELL' -and $_.Value -ceq 'pwsh')
} | Select-Object -ExpandProperty Name)
if ($overrides.Count) { throw "専用手順が必要な変数があります（値は表示しません）: $($overrides -join ', ')" }
$configsJson = & $miseExe config ls --json 2>$null
if ($LASTEXITCODE -ne 0) { throw 'configの照会に失敗しました。' }
$configPaths = @($configsJson | ConvertFrom-Json | ForEach-Object { $_.path })
if ($configPaths.Count -ne 1) { throw '単一の有効なglobal configではありません。' }
$config = $configPaths[0]
$uvPath = (& $miseExe where uv 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw '既存uvの照会に失敗しました。' }
if ((Split-Path $uvPath -Leaf) -cne '0.12.10' -or
    (Split-Path (Split-Path $uvPath) -Leaf) -cne 'uv' -or
    (Split-Path (Split-Path (Split-Path $uvPath)) -Leaf) -cne 'installs') {
    throw '想定した既存uvの配置ではありません。'
}
$data = Split-Path (Split-Path (Split-Path $uvPath))
$cache = (& $miseExe cache path 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'cacheの照会に失敗しました。' }
[pscustomobject]@{mise=$miseExe; chezmoi=$chezmoiExe; config=$config; data=$data; cache=$cache; uv=$uvPath}
$backup = Join-Path $privateParent ('windows-uv-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $backup) { throw '新規の保存先を指定してください。' }
```

通常の`mise activate pwsh`は`MISE_SHELL=pwsh`を設定するため、この識別子だけを許可する。config、data、cache、stateなどを変える変数や未知の`MISE_*`はPrepare、Install、Applyで拒否する。変数を消して既定パスへ誘導しない。環境変数の値、設定本文、認証情報を画面や返却ログへ出さない。Gitのリポジトリやindexを差し替える環境変数もSource確認時に拒否する。

入口はPrepareの入力とmiseから取得したパスについて、`/`を`\`へ変換し、連続した区切りを一つにしてから検査や比較を行う。相対パス、UNC、デバイスパスは受け付けない。`..`などの要素は解決せずに残し、既存のパス検査で拒否する。リンクやADS、末尾の空白などに対する拒否条件は変更しない。

対象は、既存の`aqua:astral-sh/uv`版uv 0.12.10だけを持つ環境に限る。Prepareは31ツールの宣言とlock、共有インストール情報、実際のconfig、uv配置、cacheの一致を検査する。候補もuv 0.12.10を維持し、`github:astral-sh/uv`へ変更する。他の30ツールの宣言や設定、lock、共有情報を変更しないことを検査する。別バージョン、複数config、追加のuv版、reparse pointなどで停止したら、対象を消したり基準を書き換えたりしない。

### Prepareだけを実行して停止する

前節の取得手順で固定SHAへ切り替えた`$repo`と`$expected`を使う。Prepare中はGitソースも編集しない。

```powershell
$entry = Join-Path $repo 'tests\manual\windows-uv\windows-uv.ps1'
pwsh -NoLogo -NoProfile -NonInteractive -File $entry -Command Prepare `
    -Source $repo -SourceCommit $expected -Config $config -Data $data -Cache $cache `
    -Backup $backup -WritersStopped
if ($LASTEXITCODE -ne 0) { throw 'Prepare停止。作成済みの保存先は保持し、再利用しないでください。' }
```

`prepared_not_installed`と出力された`backup`、`snapshotDigest`、指定したSHAを、バックアップとは別の信頼できる記録先へ保存する。snapshotはschema 2、`rollback=same_volume_original_object`である。バックアップ内に入口の2スクリプト、観測用コピー、隔離したconfig、lock、作業領域を保存する。元のconfig、lock、uv、cache、shimsは変更しない。失敗してsnapshotとjournalが完成していない保存先をInstallやRestoreへ渡さない。

**ここで停止する。Prepareの成功からInstallやApplyを自動実行しない。** 完了後のInstall、Apply、Restoreは保存済み入口を使い、候補checkoutやGitに依存しない。ソースのブランチを戻す場合は取得時に記録した値を使う。復元用ファイルや退避物を削除しない。

### 承認後に隔離Installを一度だけ実行する

別記録から`$backup`と`$snapshotDigest`を設定し、バックアップ内でdigestを再計算した値を無条件に採用しない。

```powershell
$savedEntry = Join-Path $backup 'windows-uv.ps1'
pwsh -NoLogo -NoProfile -NonInteractive -File $savedEntry -Command Install `
    -Backup $backup -SnapshotDigest $snapshotDigest -WritersStopped
if ($LASTEXITCODE -ne 0) { throw 'Install停止。再試行せず、結果と保存先を保持してください。' }
```

この段階はネットワークを使い得る実インストールであり、`work`内の隔離したconfig、data、cache、stateに対して`mise --locked install --force uv`を一度だけ実行する。元の対象は変更しない。既存のGitHub認証を利用する承認がある場合だけ`-UseExistingGitHubAuth`を追加する。新規ログインは行わず、tokenやインストーラー出力をログへ保存しない。force installの再試行は禁止する。

成功時の`isolated_install_verified_not_applied`と`planDigest`を別記録へ保存し、**Apply前に停止する。** backend、実行ファイル、PEのx64形式、版、他ツールの情報、隔離パスの混入を検査する。失敗時もコピーやログを消さない。`plan.json`が作られた後に中断し、digestを記録できなかった場合は、planの確認とdigestの確保が済むまで次の操作を止める。

### Applyとsandbox内の受け入れを分ける

Applyの承認後、別記録の2つのdigestを使う。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File $savedEntry -Command Apply `
    -Backup $backup -SnapshotDigest $snapshotDigest -PlanDigest $planDigest -WritersStopped
if ($LASTEXITCODE -ne 0) { throw 'Apply停止。対象とjournalを保持し、承認したRestoreを検討してください。' }
```

Applyは対象の親ディレクトリに候補を作り、journalを保存してから元オブジェクトをバックアップへrenameし、候補を公開する。対象はconfig、mise.lock、uvのインストールディレクトリ、共有インストール情報、uvのcacheとdownloads、uv/uvxのshim名群である。profile、PATH、Copilot設定は変更しない。成功後も退避した元オブジェクトを保持する。

ホストで`mise which uv`、`mise which uvx`と版の確認が成功しても、sandbox内のワークロード成功とは扱わない。入口が出力する`sandboxSuccess`は常に`false`である。導入後は通常の公式mise環境生成を使ったホストからCopilotを起動し、sandbox内で導入済みuvを使う承認済みの実ワークロードを別途確認する。このuvバックエンド変更だけで、全ツールのsandbox互換性を保証しない。受け入れのためにsandbox内で再インストール、移行、復元を行わない。

### 承認後にオフラインRestoreを実行する

ネットワーク、Git、候補checkout、mise、chezmoiの実行は不要である。保存済みの2スクリプト、snapshot、存在する場合のplan、journal、退避した元オブジェクトと通常権限のPowerShellを使う。インストーラーの作業領域や`observations`のコピーを復元元にしない。SourceCommitの再指定も不要である。

```powershell
$restore = @{
    Command='Restore'; Backup=$backup
    SnapshotDigest=$snapshotDigest; WritersStopped=$true
}
if (Test-Path -LiteralPath (Join-Path $backup 'plan.json')) {
    if (-not $planDigest) { throw '別記録のplanDigestが必要です。planを削除して進めないでください。' }
    $restore.PlanDigest = $planDigest
}
& (Join-Path $backup 'windows-uv.ps1') @restore
```

planがまだ存在しない失敗ではPlanDigestを指定しない。候補の公開後は既知の候補を退避して元オブジェクトを戻し、未変更の対象は動かさない。未知の変更やID不一致は停止条件であり、コピーで置き換えない。Restore自体もホストの対象へ書き込む操作なので、承認なしに実行しない。`restored`と元IDの一致を確認しても、退避物と記録は自動削除しない。

## 検証結果の範囲

Windows X64、PowerShell 7.6.5で、`native-result-04`の77件、`native-result-06`のADS 1件、通常権限のWindows Terminalでの`native-result-07`のjunction 1件と`native-result-08`のhardlink 1件に成功証跡がある。重複する静的検査5件を加算せず、異なるnativeケース80件を合算した結果である。sandboxとホストに分かれた実行の合算であり、全80件をホストだけで一括実行した結果ではない。`native-result-01`から`08`までを無視対象のまま保持する。この記録はfixtureの再実行依頼でも実移行の成功記録でもない。

## 手元で行える確認

macOSのPowerShellでも構文、通常権限でのAudit呼び出しの不在、関数定義、mockの状態遷移を確認できる。mockは76ケースと5件の静的検査を実行する。Windowsではこれらの76ケースで実際のファイル操作を使い、NTFS固有の拒否試験4ケースを加える。ファイル同士の置換では元ファイルと候補を異なる作成日時で作り、候補の日時調整と公開前後の中断からの復元も対象とする。journal置換にはエラーコード5と32を注入し、コードの保持、再試行なし、元のjournalと対象を変更しないことを確認する。この注入試験は実機で発生したエラーコードの特定ではない。mockの成功をWindows API、SACLの一致、実際の移行成功とは扱わない。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File tests/manual/windows-uv/rehearse-windows-uv.ps1 -MockOnly
```

Git入力の検査は、実際の専用GitリポジトリとmacOSの既存PowerShellで実行できる。`tests/test_windows_uv_source.py`はASTから必要な関数だけを読み、Prepare本体を実行しない。PATH上にpwshがない場合は`PWSH`へ既存実行ファイルの絶対パスを指定する。新しい依存関係は導入しない。

```sh
UV_PYTHON_DOWNLOADS=never uv run --no-project --offline python -m unittest discover -s tests -p test_windows_uv_source.py -v
```
