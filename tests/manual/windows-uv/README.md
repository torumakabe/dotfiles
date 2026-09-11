# Windowsのuv復元用fixture試験とホスト移行手順

同版のuv 0.12.10を公式miseからcanonical pathへ直接導入する入口は、[初回の直接導入とオフライン復元](direct-migration.md)を参照する。認証修正前のInstallはGitHub attestation APIのHTTP 403で失敗し、元環境は保存済みコードで復元済みである。認証修正版のInstallと実環境の切り替えは未完了である。以下の旧Applyとそのコピーによる公開手順は、新しい移行には使用しない。保存済みの旧復元記録と対応スクリプトは保持する。

この試験は、通常のmise、uv、profile、PATH、認証設定を変更しない。全件実行用の定義は専用ディレクトリ内の113ケースと5件の静的検査で、元オブジェクトの退避と復帰、中断からの復旧、NTFSの属性、拒否処理を確認する。実際のパッケージ導入や移行は実行しない。今回のACL契約と事後検証再開の変更はmacOS上の単体テストとインメモリmockで検査しており、変更後のWindowsネイティブ実行は未実施である。以前の80ケースの成功を、この変更のネイティブ検証結果として扱わない。

`windows-uv.ps1`は試験対象の関数と、固定したGitコミットを入力とする移行の入口を提供する。**実環境でのInstall、VerifyInstall、Apply、Restoreには、それぞれ利用者の承認が必要である。** この手順の整備やfixtureの成功を実移行の承認として扱わない。Prepareも新しいバックアップ領域へ書き込む操作として承認範囲を確認する。

導入、設定変更、更新、バックアップ、復元とfixtureは、Copilot sandboxの外にある通常権限のWindows PowerShellで行う。導入済みツールを使うワークロードの受け入れはsandbox内で行い、両者の結果を分けて記録する。sandboxやCopilotの設定を無効化しない。

## 通常権限で確認する範囲

変更対象の元ファイルと元ディレクトリは、同一のローカル固定NTFSボリューム内で`retained-<nonce>`へrenameして保持する。復元はそのオブジェクトを元のパスへrenameする。元オブジェクトと退避中のオブジェクトに`Set-Acl`やメタデータの書き直しは行わず、コピーから再構築しない。renameにはコピーへのフォールバックや既存オブジェクトの上書きを許可しない。

対象ツリー内のファイルとディレクトリについて、ボリュームシリアル番号とファイルIDを観測し、復帰後も同じIDであることを確認する。通常権限で読めるDACL、owner、group、ファイル内容のSHA-256、属性、作成日時、最終更新日時も比較する。同じ内容の別オブジェクトを置かれてもIDが異なるため拒否する。最終アクセス日時と対象の親ディレクトリの日時は比較対象外である。

**SACLは`unobserved`（未観測）と記録する。** 通常権限ではSACLの有無も退避前後の一致も測定しない。`Get-Acl -Audit`、権限の有効化、昇格は行わず、セキュリティ記述子全体を検証したとは扱わない。同じオブジェクトを戻す方式であり、SACLだけの並行変更を検出できるという保証はない。通常の観測項目を読み取れない場合は停止する。

コピーと公開候補は新しいオブジェクトとして作り、そのSACLには作成先での継承規則が適用される。元のSACLはコピーしない。公開前の候補は対象の親ディレクトリ内に作る。**候補が有効な間のオブジェクト固有の監査設定の維持は保証しない。** この制約を受け入れられない対象へは適用できない。

### 非公開コピーと公開候補のACL

`observations/`と隔離インストーラー用の`work/`は、バックアップ領域の親ディレクトリからDACLを継承する。コピーに元のDACLを設定しない。元のowner、group、内容、属性、作成日時、最終更新日時はコピー先でも照合する。元と保存先で継承元が違うため、元の継承ACEと非公開コピーのACEが一致するとは限らない。この差を元オブジェクトのACL変更やアクセス権の無視で解消しない。

コピー作成時は保存先の親から算出したDACL要件と実際のコピーを照合する。snapshotには元のツリーと、非公開コピーの実際のSDDL、ID、通常メタデータを別々に封印する。以後のコピー破損検査は非公開コピー自身の封印値との完全一致を要求する。Prepare完了時の`work/`も封印し、Install前に全項目を再確認する。Install後は既存ノードのownerとgroup、および非公開領域からのDACL継承を検査する。新規ノードのownerとgroupには、封印済みの作業対象の親ディレクトリの値を要求する。インストーラーによる独自のACEや継承保護の追加は採用せず停止する。

planは非公開のインストーラー出力（`blobState`）と公開要件（`after`）を分離する。Applyは前者との完全一致を確認してから、対象に隣接する新規ステージへコピーする。公開要件は次の規則で決め、保存済みの元ツリーと親から再計算してplanとの一致を確認する。

- 元と相対パスと種類が一致するノードには、元のDACL、owner、groupを要求する。明示ACEや継承保護も維持する。
- 新規ノードと種類が変わるノードには、公開先の親から継承するDACLを要求する。ルートでは封印済みの既存の親、子では同じ公開候補の親ノードを使う。ownerとgroupは検査済みの非公開出力の値を維持する。
- 公開候補の親ACLを設定してから子を作る。Windowsが実際に設定したDACLを公開要件と照合し、不一致なら元オブジェクトを動かさない。非公開コピーのACLを公開要件として採用しない。

対象の既存の親、バックアップ領域と観測コピーの親、作業対象の親について、ID、DACL、owner、group、属性もsnapshotに封印する。Prepareの終わり、Installの前後、Applyと公開用renameの前に再確認する。子の作成とrenameで変わる親の日時は対象外である。欠けている外側の親を自動作成しない。Restoreは作業領域や観測コピーを要求せず、元オブジェクトとjournalの候補を完全一致で照合してrenameする。

成功した隔離インストーラーは`work\data\installs\uv`自体を置換する場合がある。この1ディレクトリに限り、終了コード0を記録した`install-started`から事後検証を始める時点で、同じボリューム内のID変更を許可する。SDDLの`AI`を含むID以外の全記録項目はsnapshotと完全一致を要求する。他の親、元ツリー、観測コピーのIDは除外しない。既存のパス検査とノード検査を通し、候補ツリー全体のreparse point、hardlink、未対応属性も実行ファイルの起動前に拒否する。

検査した親のIDと検証コードのSHAをjournalの`validation`へ保存してから、残る事後検証を行う。以後のVerifyInstallはそのIDとの完全一致を要求し、再び置換された親を採用しない。成功時は同じ記録をplanへ含める。Applyとステージ作成、公開用renameの前の検査もこのIDを使う。snapshotの親情報、snapshot自身、保存済みスクリプトは書き換えない。

継承計算は通常のAllow/Deny ACE、具体的なアクセスマスク、`OI`、`CI`、`NP`、`IO`、`ID`に限定する。ACEの順序とアクセスマスクを保持し、子の種類と伝播範囲に応じて継承フラグを計算する。親のNULL DACL、継承可能なACEがないDACL、汎用アクセスマスク、Creator Owner/Group、オブジェクトACE、条件付きACE、未対応のフラグは停止条件である。既定DACLや近似したACLで代用しない。必要なownerとgroupを通常権限で設定できない場合も停止する。元の既存ノードの公開ACLは継承計算で書き換えず、適用後のWindowsの値と照合する。

新しいコピーや公開候補と要件の比較では、異なるファイルIDに加えて、DACL制御フラグの`AI`（`SE_DACL_AUTO_INHERITED`）だけを比較対象外とする。[WindowsがACLへ現在の自動継承モデルを適用すると、このフラグを設定する](https://learn.microsoft.com/en-us/windows/win32/secauthz/automatic-propagation-of-inheritable-aces)ためである。owner、group、ACEの内容と順序、ACEごとの継承フラグ、DACLの`P`と`AR`、通常メタデータは引き続き比較する。元オブジェクトの変更検出、封印済みコピーの検査、rename前後、復元後はIDと`AI`も含めた完全一致を要求する。公開要件と元の違いがIDと`AI`だけなら、その対象は置換しない。比較エラーには項目名を含め、設定本文、ハッシュ値、SDDL本文は出力しない。

既存ファイルを別のファイルで置き換える場合は、候補側の作成日時を元ファイルと一致させてからplanへ記録する。NTFSが同じ名前の新ファイルへ以前の作成日時を引き継ぐ動作（timestamp tunneling）によって、公開直後の候補を未知の変更と誤判定することを防ぐ。元ファイルの日時は書き換えない。日時の異なる未調整の候補は、元ファイルを動かす前に拒否する。

`observations/`内のコピーは変更検出と隔離インストーラー用の入力であり、監査情報まで含むバックアップでも復元元でもない。復元はインストーラーの作業領域やコピーが使えなくても、保存済みのsnapshot、plan（作成済みの場合）、journalと退避した元オブジェクトで行う。Git、mise、chezmoiへの依存はない。

この改訂のsnapshotは**schema 3**を維持し、新規planは**schema 4**とする。planにはsnapshotのdigest、事後検証済みの親、検証コードの完全なGit SHAと2スクリプトのハッシュを含める。schema 1と2のsnapshotは読み替えず拒否する。schema 3の旧planを持つ完成済みバックアップは、そのバックアップに保存された一致するスクリプトと当時の契約に従って扱う。旧領域へのスクリプト上書き、schema変更、失敗後の再基準化は行わない。snapshot未作成の部分的なPrepare領域も保持し、再開元として採用しない。

旧schema 3のsnapshotから事後検証だけ再開する場合は、後述の`-VerificationOnlySource`で固定した改訂版を明示する。通常の入口はsnapshotに保存されたコードハッシュとの一致を要求する。この指定は異なる検証コードを使うための限定的な互換モードであり、PrepareとInstallは拒否する。**旧保存スクリプトのApplyとRestoreはschema 4のplanを拒否する。** 改訂版のplanを作成した後は、そのplanに封印した改訂版を保持し、ApplyとRestoreにも使用する。

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

隔離した子プロセスには`MISE_GLOBAL_CONFIG_FILE`と`MISE_CONFIG_DIR`の両方を`work\config`に合わせて渡し、`MISE_CEILING_PATHS`をバックアップのルートに設定する。globalファイルだけの指定では、ホーム配下の作業ディレクトリから祖先を探索する際に通常の`~/.config/mise/config.toml`も見つかる。mise 2026.8.5の[設定探索処理](https://github.com/jdx/mise/blob/v2026.8.5/src/config/mod.rs)は、`MISE_CONFIG_DIR`を既定以外へ変更した場合に既定ディレクトリ内のconfigを除外し、ceilingに到達する前までの祖先だけを探索する。利用者の環境変数や通常設定は変更しない。Prepareで隔離用configを初めて利用する前とInstall前に、一覧が専用の1ファイルだけであることを照合する。work内の別のプロジェクトconfigなどが見つかった場合は停止し、追加configを無条件に許容しない。

入口はPrepareの入力とmiseから取得したパスについて、`/`を`\`へ変換し、連続した区切りを一つにしてから検査や比較を行う。相対パス、UNC、デバイスパスは受け付けない。`..`などの要素は解決せずに残し、既存のパス検査で拒否する。リンクやADS、末尾の空白などに対する拒否条件は変更しない。

対象は、既存の`aqua:astral-sh/uv`版uv 0.12.10が選択されている環境に限る。Prepareは31ツールの宣言とlock、共有インストール情報、実際のconfig、uv配置、cacheの一致を検査する。候補もuv 0.12.10を維持し、`github:astral-sh/uv`へ変更する。他の30ツールの宣言や設定、lock、共有情報を変更しないことを検査する。別バージョンの選択、複数config、対象内のreparse pointなどで停止したら、対象を消したり基準を書き換えたりしない。

uvの実体を扱う対象は`installs\uv\0.12.10`だけであり、親の`installs\uv`全体ではない。他バージョンのディレクトリが併存していても、コピー、インストール、置換、復元の対象に含めず、そのまま残す。隔離領域にも0.12.10だけを配置する。共有のuv backend設定、インストール情報、cache、downloadsは引き続き移行対象である。旧版のファイルを残すことと、旧版を新しいbackend設定で利用できることは別であり、後者の動作確認はこの手順に含めない。

### Prepareだけを実行して停止する

前節の取得手順で固定SHAへ切り替えた`$repo`と`$expected`を使う。Prepare中はGitソースも編集しない。

```powershell
$entry = Join-Path $repo 'tests\manual\windows-uv\windows-uv.ps1'
pwsh -NoLogo -NoProfile -NonInteractive -File $entry -Command Prepare `
    -Source $repo -SourceCommit $expected -Config $config -Data $data -Cache $cache `
    -Backup $backup -WritersStopped
if ($LASTEXITCODE -ne 0) { throw 'Prepare停止。作成済みの保存先は保持し、再利用しないでください。' }
```

`prepared_not_installed`と出力された`backup`、`snapshotDigest`、指定したSHAを、バックアップとは別の信頼できる記録先へ保存する。snapshotはschema 3、`rollback=same_volume_original_object`である。バックアップ内に入口の2スクリプト、観測用コピー、隔離したconfig、lock、作業領域を保存する。元のconfig、lock、uv、cache、shimsは変更しない。失敗してsnapshotとjournalが完成していない保存先をInstallやRestoreへ渡さない。

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

### 成功済みインストーラーの事後検証だけを再開する

VerifyInstallはインストーラーを呼ばず、保存済みの出力に対してInstallと共通の事後検証を行う。対象はschema 3のsnapshotが完成済みで、journalが`install-started`、公開記録が空、planが未作成の場合だけである。`install-status.json`は数値の`exitCode: 0`、`isolated: true`、`output: "withheld_to_avoid_secrets"`、`sandboxSuccess: false`の一致を要求する。終了状態が不明、失敗、準備中、適用済み、復元済みの場合は採用しない。Installの再実行、新しいPrepare、snapshotや保存済みスクリプトの差し替えは行わない。

この改訂で新規Prepareしたバックアップでは、保存済み入口の`-Command VerifyInstall`を使える。旧保存スクリプトにはこのコマンドがないため、旧schema 3からの再開には次の手順を使う。**修正版のcommitとpush、Windowsでの実行が別途承認され、完全なSHAが提示された後に限り実行する。**

1. 「リモートブランチから取得する」の手順で提示された改訂版SHAを取得し、`$repo`、`$expected`、元ブランチの記録を保持する。元のPrepareに用いたSHAで代用しない。
2. `$backup`と`$snapshotDigest`は、既存のPrepareで別記録した値をそのまま使う。既存の領域を改訂版コードの保存先にしない。
3. 書き込み元の停止を確認して、次のVerifyInstallだけを実行する。

```powershell
$revisedEntry = Join-Path $repo 'tests\manual\windows-uv\windows-uv.ps1'
$revised = @{
    Backup=$backup; SnapshotDigest=$snapshotDigest; WritersStopped=$true
    VerificationOnlySource=$true; Source=$repo; SourceCommit=$expected
}
pwsh -NoLogo -NoProfile -NonInteractive -File $revisedEntry -Command VerifyInstall @revised
if ($LASTEXITCODE -ne 0) { throw '事後検証停止。保存物を変更せず、結果を確認してください。' }
```

入口は改訂版のGitルート、HEADの完全SHA、追跡済みと未追跡の変更の不在を検査し、既存の2保存スクリプトは元snapshotにあるハッシュと照合する。検証中も元ツリーと観測コピーを照合し、最後に入力コードを再確認する。GitHub認証の取得とforce installは行わない。miseの参照先と版の照会、uv/uvxの版の実行、私有候補のメタデータ調整とplan作成は行うため、単なる読み取り専用操作ではない。ライブ対象と保存済みの元データは変更しない。

成功時の`planDigest`と改訂版の完全SHAを別記録し、Apply前に停止する。検証が途中で失敗しても、保存済み`validation`を消さない。同じ固定SHAから再検証する場合も、封印済み親のIDとメタデータの一致を要求する。planが既にあればVerifyInstallを拒否する。planの保存後、journalの`installed`更新前に中断した場合は、planとdigestを確認した後、同じ改訂版のApplyまたはRestoreを別途承認して使う。

Applyの承認後は、旧保存入口の代わりに同じ固定SHAの入口を使う。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File $revisedEntry -Command Apply @revised -PlanDigest $planDigest
if ($LASTEXITCODE -ne 0) { throw 'Apply停止。対象とjournalを保持してください。' }
```

Restoreの承認後も、schema 4のplanがある場合は同じ改訂版を使う。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File $revisedEntry -Command Restore @revised -PlanDigest $planDigest
if ($LASTEXITCODE -ne 0) { throw 'Restore停止。対象とjournalを保持してください。' }
```

このRestoreは外部記録のPlanDigestでplanを確認し、指定した完全SHAと実行中の2スクリプトのハッシュをplanと照合する。ネットワークやGit、mise、chezmoiは呼ばず、作業領域や観測コピーも要求しない。ただし改訂版の2ファイルを保持したSourceは必要であり、元ブランチへ戻したcheckoutをそのまま使うことはできない。再取得が必要になる前に復元用コードを利用できる状態で保持する。plan作成前のRestoreには旧保存スクリプトを使える。改訂版の互換モードによるRestoreは、planが未作成なら拒否する。

### Applyとsandbox内の受け入れを分ける

この改訂のPrepareで保存したスクリプトを使う場合は、Applyの承認後、別記録の2つのdigestを使う。旧snapshotを改訂版から検証した場合は、前節の固定SHAの入口を使う。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File $savedEntry -Command Apply `
    -Backup $backup -SnapshotDigest $snapshotDigest -PlanDigest $planDigest -WritersStopped
if ($LASTEXITCODE -ne 0) { throw 'Apply停止。対象とjournalを保持し、承認したRestoreを検討してください。' }
```

Applyは対象の親ディレクトリに候補を作り、journalを保存してから元オブジェクトをバックアップへrenameし、候補を公開する。対象はconfig、mise.lock、`installs\uv\0.12.10`、共有インストール情報、uvのcacheとdownloads、uv/uvxのshim名群である。profile、PATH、Copilot設定は変更しない。成功後も退避した元オブジェクトを保持する。

ホストで`mise which uv`、`mise which uvx`と版の確認が成功しても、sandbox内のワークロード成功とは扱わない。入口が出力する`sandboxSuccess`は常に`false`である。導入後は通常の公式mise環境生成を使ったホストからCopilotを起動し、sandbox内で導入済みuvを使う承認済みの実ワークロードを別途確認する。このuvバックエンド変更だけで、全ツールのsandbox互換性を保証しない。受け入れのためにsandbox内で再インストール、移行、復元を行わない。

### 承認後にオフラインRestoreを実行する

この改訂のPrepareで保存したスクリプトを使う場合、ネットワーク、Git、候補checkout、mise、chezmoiの実行は不要である。保存済みの2スクリプト、snapshot、存在する場合のplan、journal、退避した元オブジェクトと通常権限のPowerShellを使う。インストーラーの作業領域や`observations`のコピーを復元元にしない。SourceCommitの再指定も不要である。旧snapshotを改訂版から検証してschema 4のplanを作った場合は、前節の改訂版Restoreを使う。

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

## 復元後の同名公開を偽ツリーで診断する

`diagnose-windows-uv.ps1`は、元ディレクトリの退避直後に、その名前へ候補を公開する順序を一回だけ再現する。実際の`0.12.10`を移動せず、移行入口のPrepare、Install、VerifyInstall、Apply、Restoreも呼ばない。復元済みバックアップは読み取り専用の入力であり、診断結果から実Applyの再実行を許可しない。

コードの公開とWindowsでの実行は別途承認を必要とする。承認後は固定SHAの変更のないGit checkoutを使い、保存済みスクリプトを差し替えない。次の引数を事前に設定する。

| 引数 | 入力と条件 |
|---|---|
| `Backup` | 復元済みschema 3バックアップ。journalのphaseが`restored`で、schema 4のplanがあること |
| `SnapshotDigest` / `PlanDigest` | 外部に保存済みのSHA256。バックアップから再計算した値を新たな基準にしない |
| `ApprovedUvParent` | そのsnapshotに記録された`0.12.10`の親の絶対パス。ここへの新規診断ディレクトリ作成を明示的に承認する |
| `FixtureRoot` | 同じローカル固定NTFSボリューム上、ユーザーホーム配下の未作成パス。既存の私有親を使い、Backup、ApprovedUvParent、Git checkout、snapshotの全実対象（不存在を含む）と包含関係を持たせない |
| `SourceCommit` | 診断コードを含むcheckoutの完全な40桁SHA |
| `WritersStopped` | 書き込み元を停止したことの明示。指定しない場合は書き込み前に拒否する |
| `UsePublicationCopy` | 任意。新規の試験用候補だけを本番と同じ`Copy-Tree`で作成し、planの公開要件に従ってSDDL、owner、groupも設定する。この新規コピーへの設定を承認した場合だけ指定する |

```powershell
$diagnostic = @{
    Backup=$backup; SnapshotDigest=$snapshotDigest; PlanDigest=$planDigest
    ApprovedUvParent=$approvedUvParent
    FixtureRoot=$newFixtureRoot; SourceCommit=$expected; WritersStopped=$true
}
pwsh -NoLogo -NoProfile -NonInteractive `
    -File (Join-Path $repo 'tests\manual\windows-uv\diagnose-windows-uv.ps1') @diagnostic
if ($LASTEXITCODE -ne 0) { throw '診断停止。再試行や削除をせず、全fixtureと結果を保持してください。' }
```

元データにはバックアップの観測コピー、候補にはplanに封印されたblobを使う。保存物とすべての実対象を検査した後、承認済み親にGUID付きの`.n4-uv-diagnostic-live-*`と`.n4-uv-diagnostic-stage-*`を新規作成する。バイト列、属性、作成日時、更新日時をコピーする。ACLは作成先の継承規則に従わせ、ownerとgroupは作成時の既定値を維持する。コピーの比較基準はsnapshotの元ツリーとplanの公開候補であり、除外する差は新規IDとDACLの`AI`だけである。権限が一致しなければ、設定し直さずrename前に停止する。

`-UsePublicationCopy`を指定した場合は、候補側だけを本番の公開用コピーに切り替える。コピー先が診断用の新規パスであることを確認してから、共通の`Copy-Tree`へ同じ入力と公開要件を渡す。試験用の元ツリーは既定の継承方式を維持し、既存の実体、ACLと保存物は変更しない。既定方式とこの方式を同じ実行内で繰り返さない。結果の`publicationCopyRequested`と各コピーの`copyMethod`に選択した方式を記録する。`explicitAclSetterReproduced`は候補コピーの成功後にtrueとなり、開始前はfalse、途中で失敗した場合はnullとなる。

両コピーが一致した場合だけ、次の4回のrenameを順番に試みる。各段階の前後で、4つの偽ツリーの存在状態、ID、内容、観測メタデータの完全一致を要求する。

1. 偽liveを新規FixtureRoot内の`retained-original`へ退避する。
2. 偽stageを、直前に空いた同じ偽live名へ公開する。
3. 公開した偽候補をFixtureRoot内の`candidate`へ退避する。
4. `retained-original`を偽live名へ戻す。

一段階でも失敗したら、それ以降のrenameと自動復元を行わない。既存のprobe、残存stage、実際のuv、保存済みjournalを操作しない。成功時も偽liveと退避した偽候補を残す。FixtureRootとGUID付きディレクトリの再利用、リトライ、待機、置換フラグ、既存オブジェクトのACL変更は行わない。

FixtureRootには`copy-original.json`、`copy-candidate.json`、`synthetic-state.json`、実行した段階の`phase-1.json`から`phase-4.json`、`result.json`を新規保存する。コピー途中の失敗では未到達のファイルは作られない。各コピーとrenameの記録にはphase、source、destination、経過ミリ秒、成否が含まれる。ネイティブrenameの失敗ではC#内で直ちに取得したWin32コードとoperationを記録し、PowerShellに戻ってからlast-errorを読み直さない。一般の検査失敗ではWin32コードはnullである。

成功時のstatusは`synthetic_restored`、失敗時は`failed`であり、常に`simulated_only=true`、`sandboxSuccess=false`を出力する。失敗後もsnapshot、plan、既存journalと保存済みスクリプトのハッシュ、入力にした観測コピーと候補、snapshotの全実対象、既存のuv兄弟ツリー、uv親の日時以外のメタデータ、Git入力を検査する。診断入力ではないmiseの内部状態ディレクトリは走査しない。検査不一致は`invariantErrors`へすべて記録し、先の操作エラーも保持する。事前検査での拒否はfixtureを作らず、プロセス強制終了や記録先のI/O障害ではJSONの完成を保証しない。

この診断は実データと観測メタデータ、同じ親、退避直後の名前再利用を扱う。明示的なSDDL設定は`-UsePublicationCopy`で候補側に限り再現する。実際の`0.12.10`という名前、既存オブジェクトの履歴、過去のハンドルやフィルタードライバーの状態、SACLは再現しない。新規コピーの単純rename成功だけでも、この診断の成功だけでも、過去の失敗原因は確定しない。ロック、AV、親ACL、last-errorの値のいずれも原因とは断定しない。

## 検証結果の範囲

Windows X64、PowerShell 7.6.5で、`native-result-04`の77件、`native-result-06`のADS 1件、通常権限のWindows Terminalでの`native-result-07`のjunction 1件と`native-result-08`のhardlink 1件に成功証跡がある。重複する静的検査5件を加算せず、異なるnativeケース80件を合算した結果である。sandboxとホストに分かれた実行の合算であり、全80件をホストだけで一括実行した結果ではない。`native-result-01`から`08`までを無視対象のまま保持する。この記録はfixtureの再実行依頼でも実移行の成功記録でもない。

## 手元で行える確認

macOSのPowerShellでも構文、通常権限でのAudit呼び出しの不在、関数定義、mockの状態遷移を確認できる。mockは109ケースと5件の静的検査を実行する。Windowsではこれらの109ケースで実際のファイル操作を使い、NTFS固有の拒否試験4ケースを加える。ACL契約の単体テストは合成SIDで6 ACEの元ツリーと3 ACEの非公開コピーを区別し、継承フラグ、新規子ノード、未対応ACEの拒否、コピー処理の親子作成順序と元ツリーの再照合を検査する。Windowsのセキュリティ記述子APIはmacOSのテストで呼び出さない。

ファイル同士の置換では元ファイルと候補を異なる作成日時で作り、候補の日時調整と公開前後の中断からの復元も対象とする。journal置換にはエラーコード5と32を注入し、コードの保持、再試行なし、元のjournalと対象を変更しないことを確認する。この注入試験は実機で発生したエラーコードの特定ではない。mockの成功をWindows API、SACLの一致、実際の移行成功とは扱わない。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File tests/manual/windows-uv/rehearse-windows-uv.ps1 -MockOnly
```

Git入力の検査は、実際の専用GitリポジトリとmacOSの既存PowerShellで実行できる。`tests/test_windows_uv_source.py`はASTから必要な関数だけを読み、Prepare本体を実行しない。PATH上にpwshがない場合は`PWSH`へ既存実行ファイルの絶対パスを指定する。新しい依存関係は導入しない。

`tests/test_windows_uv_resume.py`は終了状態、親の変更範囲、journalへの封印、再検証時の変更拒否、schema 4のApplyとRestoreを検査する。実際のコマンド分岐をmockで実行し、VerifyInstallがインストーラーを呼ばないこと、通常Installが同じ事後検証を使うこと、snapshotと保存スクリプトのバイト列を変更しないことも確認する。固定SHAと保存コードの照合、改訂版RestoreでGitを呼ばない契約はGit入力の単体テストで扱う。公開用コピーの診断モード追加前は対象単体テスト66件とmock109件、静的検査5件がmacOSで成功し、追加後は変更対象の診断用11件が成功した。新モードのWindows実行は未検証である。
LinuxとWSLでは、PowerShellのパス処理がWindowsと異なるため、このresumeテストを実行しない。Windowsでのネイティブ確認とmacOSの既存PowerShellによるmock確認は維持する。

`tests/test_windows_uv_diagnostic.py`は、C#の呼び出し先をstubにしたエラー取得、偽ツリーの4段階、同名公開失敗後の停止、読み取り入力と実対象への書き込み拒否、失敗後の全検査を扱う。Windows APIは呼ばないため、Windowsでのネイティブ診断結果とは区別する。

```sh
UV_PYTHON_DOWNLOADS=never uv run --no-project --offline python -m unittest discover -s tests -p 'test_windows_uv_*.py' -v
```
