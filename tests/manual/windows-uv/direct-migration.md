# Windowsのuvを同じ版で公式miseから導入するための事前確認

初回の対象はuv 0.12.10とする。候補lockは5プラットフォームともこの版を保持する。0.12.11の公開後経過時間を待たず、最小公開経過時間の制限も変更しない。以降の版を扱うときも、スクリプト内の版番号を更新する方式にはしない。

`plan-direct-windows-uv.ps1`は、この移行用の独立した**Plan入口のみ**を実装する。元環境を読み取り、新規のReportファイルを1個作る。mise、uv、uvxは起動せず、導入、元オブジェクトの移動、設定の公開、復元はできない。出力は常に`canApply: false`であり、実環境のaquaからGitHubへの切り替えは未完了である。

旧`windows-uv.ps1`のsnapshot、plan、journalは読み込まない。旧保存スクリプトと復元済みの記録はそのまま保持する。旧Applyによるバイナリディレクトリのコピーと公開は、この移行では使用しない。

## 一度だけ取得する実環境の情報

公式mise v2026.8.5は、導入先が既に存在すると同じ版を導入済みと判断する。また、uvだけを要求しても、初期化で他ツールの旧metadataを共有manifestへ移す場合がある。Windowsのruntime参照は通常ファイルの場合があり、数値名の実ディレクトリと区別する必要がある。

このため、直接導入の復元対象を確定するには、次の情報を一つのReportで取得する。診断用ディレクトリの削除や再現試験は行わない。

| 対象 | Reportの記録 | 判断への用途 |
|---|---|---|
| config、lock、候補ソース | SHA-256、ファイルID、通常メタデータ | 移行する設定入力の固定 |
| miseとchezmoiのApplication解決先 | パスとSHA-256 | WinGetの実行リンクも従来の解決方法で扱い、ハッシュを前後で照合する。これらは退避対象にしない |
| `installs/uv/<版>` | 全実バージョンのツリーと元オブジェクトの情報 | 対象版の存在と、残す旧版を区別する |
| major、minor、latest、configのuv alias | 不存在、ファイル、ディレクトリの区別とpointer候補 | 復元する個別のファイル名を決める |
| `installs/.mise-installs.toml`、`installs/uv/.mise.backend.toml` | 元オブジェクトとTOMLの意味内容 | uvの変更と他ツールの意味内容を分離する |
| 他ツールの`.mise.backend.toml` | 存否、元オブジェクトとTOMLの意味内容 | 共有manifestへの初期移行が起きる対象を特定する |
| 実cacheの`uv`と実dataの`downloads/uv` | ツリー全体。不完全状態を含む | 導入失敗時にも新規ディレクトリとcacheの状態を一緒に扱う |
| 対象の親と保存先の親 | ID、DACL、owner、group、属性 | 同一ボリュームと通常権限の保存条件を確認する |

数値の実バージョン名でも既知のalias名でもないuv直下の項目は、`outsideScopeNames`に名前だけを記録する。`.n4-uv-*`などの既存probeには入らず、移行対象へ追加しない。他ツールは旧metadataだけを読み、バイナリを再帰走査しない。

pointer候補の内容は版番号またはパス形式に限定して記録する。それ以外の内容はハッシュとサイズだけを記録する。`version_pointer_candidate`と`path_pointer_candidate`は観測上の分類であり、miseのpointerであることを保証しない。`blocked_directory`、`blocked_nonpointer`、`unresolved_pointer_format`があれば、そのslotを置換する実装へ進めない。custom aliasが実バージョン名と衝突する場合も実ディレクトリを保持する。

Planは渡されたConfig、Data、Cacheを読む。**これらが通常のmiseで実際に使われるパスかどうかは確認しない。** Reportの`rootsConfirmedByMise`と`installedVersionExecuted`はfalseとする。`MISE_*`のoverrideはPowerShell activationの`MISE_SHELL=pwsh`以外を拒否する。通常のactivationが保持する`__MISE_ORIG_PATH`、`__MISE_DIFF`、`__MISE_SESSION`は拒否しない。元configのuv aliasが省略されている場合も扱い、backendと版は元lockがaquaの指定版であることを照合する。指定版の`uv.exe`、`uvx.exe`の存在を照合するが、これを実行結果と扱わない。

## Planの承認と実行

この文書の追加はWindows実行の依頼ではない。次に必要な承認は、**以下のPlanを通常権限のWindows PowerShellで一度実行し、新規Reportを保存することだけ**である。導入や切り替えの承認とは分ける。

公開済みの完全なコミットSHAと、実環境の既知のConfig、Data、Cacheを指定する。Sourceと実行中のスクリプトのハッシュを照合し、追跡対象の変更は拒否する。未追跡ファイルは、既存手順が保持する`tests/manual/windows-uv/native-result-NN/`（数字2桁以上）配下の結果だけを許可し、それ以外は拒否する。既存の結果は読み込まず、削除もしない。Gitとchezmoiは既存の実体を使用する。Gitはソースの識別、chezmoiはメモリ上のテンプレート展開とTOML解析だけに使う。

mise、chezmoi、uvと、それらの対象を書き換えるエディター、自動更新などを停止してから実行する。入力と保存先はユーザープロファイル内の同一の固定NTFSボリュームに限定する。ReportとRecoveryはどちらも未使用の名前を指定し、既に存在する非公開の親を使う。Reportは将来のRecoveryの外へ置く。既存のsnapshot、plan、journalを持つディレクトリの中へ新しい名前で保存することも拒否する。Reportの親を他の通常ユーザーが書き換えられる場合は停止し、ACLを変更して続行しない。

```powershell
$parameters = @{
    Command = 'Plan'
    Source = '<固定SHAのクリーンなリポジトリルート>'
    SourceCommit = '<公開済みの40文字のSHA>'
    Config = '<既知の実global config.toml>'
    Data = '<既知の実mise dataディレクトリ>'
    Cache = '<既知の実mise cacheディレクトリ>'
    Recovery = '<非公開の親の下の未作成ディレクトリ>'
    Report = '<非公開の親の下の未作成JSONファイル>'
    ExpectedVersion = '0.12.10'
    WritersStopped = $true
}
& (Join-Path $parameters.Source 'tests\manual\windows-uv\plan-direct-windows-uv.ps1') @parameters
```

元の対象を2回読み、内容やIDが変わっていればReportを作らず停止する。成功時はReportのパスとdigestを表示する。Reportは上書き不可で作成し、Recoveryは作成しない。Reportには端末内のパスとmetadataを含むため、公開リポジトリへ置かない。失敗した領域や旧記録を削除して再試行しない。

移行対象と設定入力について、通常権限で読める内容、ID、DACL、owner、group、属性、作成日時、最終更新日時を扱う。SACLと最終アクセス日時は検証対象外である。これらへの`Read-Tree`のreparse point、hardlink、ADS、未対応属性の拒否を維持する。実行用ツールは別の`toolHashes`へパスとハッシュを記録する。読み取りによる最終アクセス日時やOS監査の記録まで不変とは保証しない。

## Report取得後に実装する初回切り替え

次の判断は、Reportにあるruntime slotと他ツールの旧metadataを、v2026.8.5の初期化処理と照合して、復元対象を確定できるかどうかである。現在の入口にはInstallとRestoreを実装していないため、Reportだけで次の操作を実行しない。

1. 固定ソースSHA、入力digest、Planのdigestを照合し、新しい専用Recoveryへ独立したsnapshotとjournalを作る。Reportとは異なる実行用schemaを定義し、旧schemaへ読み替えない。復元に必要な情報はインストーラー起動前に保存する。
2. 元の対象版ディレクトリを、同一ボリューム内のRecoveryへrenameする。元ディレクトリをコピーで再構成したり、上書き、削除したりしない。この間だけcanonical pathが不存在になる。書き込み元の停止と、この初回切り替えへの明示的な承認を必要とする。
3. config、lock、共有manifest、uv backend metadata、確定したruntime pointer、実uv cache、必要なdownload状態についても元オブジェクトを保持する。共有manifestなどインストーラーへの入力が必要なファイルは、保持した元から新規ファイルを作る。cacheを新しくする場合は、元の実uv cacheをrenameして保持し、実cache内に空の置き換え先を作る。不完全状態のmarkerだけを別cacheへ隔離しない。
4. 公式miseの子プロセスで`mise install --locked uv`を一度だけ実行する。導入先は実data内の不存在になったcanonical pathとし、私有ディレクトリへ導入したバイナリをコピーして公開しない。`--force`は使わない。
5. 成否と新規出力を記録する。成功時も、対象版のuvとuvxの解決先と実行結果、候補configとlockの不変性、他30ツールのmetadataの意味内容、既存uv各版の不変性を確認するまでglobal configとlockを公開しない。新規導入オブジェクトのACLを元と同一と仮定せず、通常権限での検査条件を別に定義する。
6. 失敗した場合は、journalに対応する既知の新規出力だけをquarantineへrenameしてから、元オブジェクトを戻す。失敗した新規ディレクトリを通常のcacheで導入済みと見なせる状態に残さない。成功後のplanが存在しなくても復元できるようにする。未知の変更があれば停止し、任意のオブジェクトを上書きしない。

子プロセスは`MISE_GLOBAL_CONFIG_FILE`、`MISE_CONFIG_DIR`、`MISE_CEILING_PATHS`で候補設定の探索範囲を限定する。`MISE_DATA_DIR`と`MISE_CACHE_DIR`は実際の対象を使い、`MISE_ENABLE_TOOLS=uv`で対象ツールを絞る。`MISE_SHIMS_DIR`は新しいRecovery内の専用ディレクトリを指定し、実shimsとPATHは変更しない。共有manifestの初期化はツールの絞り込みより前に起き得るため、この変数だけを他30ツールの保護として扱わない。

根拠となる公式ソースは、[backendの導入処理](https://github.com/jdx/mise/blob/v2026.8.5/src/backend/mod.rs#L2632-L2779)、[manifestの初期化](https://github.com/jdx/mise/blob/v2026.8.5/src/toolset/install_state.rs#L215-L333)、[manifestの保存](https://github.com/jdx/mise/blob/v2026.8.5/src/toolset/install_state.rs#L566-L591)、[shimsなどの再生成](https://github.com/jdx/mise/blob/v2026.8.5/src/config/mod.rs#L3033-L3077)、[runtime参照](https://github.com/jdx/mise/blob/v2026.8.5/src/runtime_symlinks.rs)を参照する。

## 移行後の通常更新

通常更新には元ディレクトリの退避を組み込まない。別のツール名、永続alias、独自install root、専用updaterは追加しない。初回移行が完了した後は、隔離した設定とlockで公式miseの次のコマンドを使う。隔離にはglobal設定ファイルの指定だけでなく、設定ディレクトリと探索上限の指定も必要である。

```powershell
mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64 --bump uv
```

他30ツールの内容が変わっていないことを確認したlockを通常の管理手順で反映してから、`mise install --locked uv`で新しい版を通常の場所へ導入する。公開後経過時間の条件を満たさない版を強制採用しない。旧版を自動削除する更新操作は使わない。`mise upgrade`を別途選ぶ場合は`mise upgrade uv --no-prune`で旧版を残す。

## 検証範囲

macOS上の既存PowerShellで、TOMLからの同版照合、5プラットフォーム、ARM64のx64 asset指定、他ツールlockの保持、版番号のパラメーター化、runtime slotの分類、probeの範囲外扱い、保存先の重複拒否、新規Reportの上書き拒否を検査する。`tests/test_windows_uv_direct_plan.py`が対象である。

WindowsのNTFSでのPlan実行、実際のruntime pointer形式、他ツールの旧metadataの残存状態は未確認である。これらをmockの成功で代用しない。直接InstallとRestoreのWindows試験、実導入、sandbox内ワークロードの検証も未実施である。
