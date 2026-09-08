# Windowsのuv復元用fixture試験

この試験は、通常のmise、uv、profile、PATH、認証設定を変更しない。専用ディレクトリ内の11ケースで、コピー、復元、NTFSの属性、拒否処理を確認する。実際のパッケージ導入や移行は実行しない。

`windows-uv.ps1`は試験対象の関数を提供するために含めている。まだ実機での移行を確認していないため、同スクリプトの`Prepare`、`Install`、`Apply`を通常環境へ実行しない。

## リモートブランチから取得する

通常のPowerShell 7.6以上とGitを使う。管理者として開き直さない。対象はユーザープロファイル配下のローカルNTFSにあるdotfilesリポジトリとする。共有フォルダーやreparse pointを含む保存先は対象外である。

依頼文に記載された完全なコミットSHAを使う。未コミット変更があれば停止し、既存の変更を退避、削除、上書きしない。

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
pwsh -NoLogo -NoProfile -NonInteractive -File $runner -ExpectedCommit $expected
$fixtureExit = $LASTEXITCODE
Write-Host "Fixture exit code: $fixtureExit"
```

入口はコミットSHAと作業ツリーの状態を確認する。必要なSACL監査情報を通常の権限で読めなければ`BLOCKED`で停止し、ログ用の`native-result-01`だけを作る。昇格、実行ポリシーの変更、bypass、属性削除で試験を通さない。

前提を満たした場合だけ`native-result-01\fixture`を作る。拒否の確認用に、同じfixture内のjunction、hardlink、ADS、readonlyファイルも作る。既存の結果ディレクトリへの再実行は拒否する。

## 結果を返して元のブランチへ戻る

`PASS`、`FAIL`、`BLOCKED`の表示と、次のファイルを依頼元セッションへ返す。通常設定や認証情報、HOME全体は送らない。ファイルはGit管理対象外であり、commitやpushは行わない。

- `tests/manual/windows-uv/native-result-01/result.json`
- 存在する場合は同ディレクトリの`native.stdout.json`と`native.stderr.txt`

結果を回収した後、上で記録したブランチまたはコミットへ戻す。途中でPowerShellを閉じた場合は、元の値を確認してから戻す。推測したブランチへ切り替えない。

```powershell
if ($wasDetached) { git switch --detach $previous }
else { git switch $previous }
if ($LASTEXITCODE -ne 0) { throw '元のブランチへ戻せません。強制切り替えせず、結果とともに知らせてください。' }
```

結果とfixtureは回収後も保持する。失敗後の再実行や通常環境への移行は、依頼元が結果を確認するまで行わない。

## 手元で行える確認

macOSのPowerShellでも構文、関数定義、mockの状態遷移を確認できる。この結果をWindows APIや実際の移行成功とは扱わない。

```powershell
pwsh -NoLogo -NoProfile -NonInteractive -File tests/manual/windows-uv/rehearse-windows-uv.ps1 -MockOnly
```
