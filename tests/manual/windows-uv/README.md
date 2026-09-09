# Windowsのuv復元用fixture試験

この試験は、通常のmise、uv、profile、PATH、認証設定を変更しない。専用ディレクトリ内の77ケースと5件の静的検査で、元オブジェクトの退避と復帰、中断からの復旧、NTFSの属性、拒否処理を確認する。実際のパッケージ導入や移行は実行しない。

`windows-uv.ps1`は試験対象の関数を提供するために含めている。まだ実機での移行を確認していないため、同スクリプトの`Prepare`、`Install`、`Apply`、`Restore`を通常環境へ実行しない。`Prepare`に残る旧candidate-manifestの受け入れ条件は、この改訂によって実移行用に承認されたものではない。

## 通常権限で確認する範囲

変更対象の元ファイルと元ディレクトリは、同一のローカル固定NTFSボリューム内で`retained-<nonce>`へrenameして保持する。復元はそのオブジェクトを元のパスへrenameする。元オブジェクトと退避中のオブジェクトに`Set-Acl`やメタデータの書き直しは行わず、コピーから再構築しない。renameにはコピーへのフォールバックや既存オブジェクトの上書きを許可しない。

対象ツリー内のファイルとディレクトリについて、ボリュームシリアル番号とファイルIDを観測し、復帰後も同じIDであることを確認する。通常権限で読めるDACL、owner、group、ファイル内容のSHA-256、属性、作成日時、最終更新日時も比較する。同じ内容の別オブジェクトを置かれてもIDが異なるため拒否する。最終アクセス日時と対象の親ディレクトリの日時は比較対象外である。

**SACLは`unobserved`（未観測）と記録する。** 通常権限ではSACLの有無も退避前後の一致も測定しない。`Get-Acl -Audit`、権限の有効化、昇格は行わず、セキュリティ記述子全体を検証したとは扱わない。同じオブジェクトを戻す方式であり、SACLだけの並行変更を検出できるという保証はない。通常の観測項目を読み取れない場合は停止する。

候補は新しいオブジェクトとして作り、そのSACLには作成先での継承規則が適用される。コピー処理が再現するのは観測したDACL、owner、groupと通常のメタデータであり、元のSACLは候補へコピーしない。公開前の候補は対象の親ディレクトリ内に作る。**候補が有効な間のオブジェクト固有の監査設定の維持は保証しない。** この制約を受け入れられない対象へは適用できない。

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
| 復元済み | IDと観測項目が一致する場合は何も動かさない |

元が存在しなかった対象は、既知の候補を退避して不存在へ戻す。候補も不存在なら何もしない。観測項目が元と同じ候補では元オブジェクトを動かさない。未知の内容やID、退避元の欠落、journalと矛盾する配置があれば、コピーによる代用や再基準化はせず停止する。

書き込み元の停止が前提であり、全対象の事前確認と各renameの前後で変更を確認する。複数オブジェクトを一括更新するトランザクションや、並行書き込み、電源断、ストレージ故障への完全な保護ではない。試験はjournalの再読み込みとrename前後の例外による中断を扱う。journal保存前の中断では、未使用のステージングコピーが残ることがある。結果、退避物、コピーは自動削除せず保持する。

reparse point、hardlink、ADS、readonly、sparse、compressed、encryptedは引き続き対象外とする。試験を通すために既存対象の属性やACLを変更しない。

## リモートブランチから取得する

通常のPowerShell 7.6以上とGitを使う。管理者として開き直さない。対象はユーザープロファイル配下のローカルNTFSにあるdotfilesリポジトリとする。共有フォルダーやreparse pointを含む保存先は対象外である。

公開済みの完全なコミットSHAが別途提示され、fixture試験を依頼された後に以下を実行する。この文書の改訂だけを再実行の依頼と解釈しない。未コミット変更があれば停止し、既存の変更を退避、削除、上書きしない。

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
$changes = @(git status --porcelain=v1 --untracked-files=all)
if ($LASTEXITCODE -ne 0 -or $changes.Count -ne 0) { throw '未コミット変更があります。ここで停止してください。' }
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

## 結果を返して元のブランチへ戻る

`PASS`、`FAIL`、`BLOCKED`の表示と、次のファイルを依頼元セッションへ返す。通常設定や認証情報、HOME全体は送らない。ファイルはGit管理対象外であり、commitやpushは行わない。

- `tests/manual/windows-uv/native-result-02/result.json`
- 存在する場合は同ディレクトリの`native.stdout.json`と`native.stderr.txt`

結果を回収した後、上で記録したブランチまたはコミットへ戻す。途中でPowerShellを閉じた場合は、元の値を確認してから戻す。推測したブランチへ切り替えない。

```powershell
if ($wasDetached) { git switch --detach $previous }
else { git switch $previous }
if ($LASTEXITCODE -ne 0) { throw '元のブランチへ戻せません。強制切り替えせず、結果とともに知らせてください。' }
```

結果とfixtureは回収後も保持する。失敗後の再実行や通常環境への移行は、依頼元が結果を確認するまで行わない。

## 手元で行える確認

macOSのPowerShellでも構文、通常権限でのAudit呼び出しの不在、関数定義、mockの状態遷移を確認できる。mockは73ケースと5件の静的検査を実行する。Windowsではこれらの73ケースで実際のファイル操作を使い、NTFS固有の拒否試験4ケースを加える。ファイル同士の置換では元ファイルと候補を異なる作成日時で作り、候補の日時調整と公開前後の中断からの復元も対象とする。mockの成功をWindows API、SACLの一致、実際の移行成功とは扱わない。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File tests/manual/windows-uv/rehearse-windows-uv.ps1 -MockOnly
```
