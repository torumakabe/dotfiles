# Windowsのuvを同じ版で公式miseから直接導入する

初回の対象はuv 0.12.10とする。候補lockは5プラットフォームともこの版を保持する。0.12.11の公開後経過時間を待たず、最小公開経過時間の制限も変更しない。以降の版を扱うときも、スクリプト内の版番号を更新する方式にはしない。

`plan-direct-windows-uv.ps1`は読取専用のPlan入口として維持する。`direct-windows-uv.ps1`が、取得済みReportからの`Prepare`、公式miseによる一回の`Install`、オフラインの`Restore`を実装する。Windowsでの直接InstallとRestoreは未実施であり、実環境の切り替え完了を意味しない。

旧`windows-uv.ps1`のsnapshot、plan、journalは読み込まない。旧保存スクリプトと復元済みの記録はそのまま保持する。旧Applyによるバイナリディレクトリのコピーと公開は、この移行では使用しない。

## 取得済みReportと対象範囲

Windows x64、PowerShell 7.6.5、mise 2026.8.5でPlanは終了コード0を記録済みである。Reportは`C:\Users\tomakabe\windows-uv-direct-inventory-777d610c52b8471183b25eeb4820721a.json`、SHA-256は`72F7C61F39FEF910A804B27E90943442AF6FF618E7EC619F1E90F1FD84F0BD4C`、取得時のソースSHAは`1ecefa39890cd280ad86eab42779cfe9fbd74d08`である。**このReportを再取得、上書きしない。**

4個のruntime slotは通常ファイルで、`0`、`0.12`、`latest`の内容は`.\0.12.10`、`0.11`は`.\0.11.31`である。9個の実バージョンのうち、0.12.10だけを置き換える。共有manifestは41項目、uv以外の`.mise.backend.toml`は27ファイルである。metadataの値はReport内に保持し、実行時に端末内で意味内容を照合する。

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

Install入口は上記の版とpointer内容を限定して受け入れる。別のslot、実ディレクトリ、別形式のpointerは停止条件とする。4個の既存`.n4-uv-*`証跡ディレクトリは移動、コピー、削除せず、中へ入らない。uv直下の一覧から名前の存続だけを照合する。

Planは渡されたConfig、Data、Cacheを読む。**これらが通常のmiseで実際に使われるパスかどうかは確認しない。** Reportの`rootsConfirmedByMise`と`installedVersionExecuted`はfalseとする。`MISE_*`のoverrideはPowerShell activationの`MISE_SHELL=pwsh`以外を拒否する。通常のactivationが保持する`__MISE_ORIG_PATH`、`__MISE_DIFF`、`__MISE_SESSION`は拒否しない。元configのuv aliasが省略されている場合も扱い、backendと版は元lockがaquaの指定版であることを照合する。指定版の`uv.exe`、`uvx.exe`の存在を照合するが、これを実行結果と扱わない。

## Prepareとソースの信頼

以下は実行手順であり、今回の実装作業ではWindowsコマンドを実行していない。書き込み元を停止した通常権限のPowerShellで使用する。Reportの`roots.recovery`に記録した未作成パスを使い、旧復元済みjournalや旧recovery checkoutは指定しない。

この実装を含む信頼済みの完全なコミットSHAを`SourceCommit`へ渡す。Report取得時のSHAと一致する必要はない。新ソースのHEAD、実行中の3ファイルのハッシュ、Reportのdigest、Reportが封印したテンプレートとlockのハッシュを別々に照合する。追跡対象の変更を拒否し、未追跡ファイルは`tests/manual/windows-uv/native-result-NN/`（数字2桁以上）配下だけを許可する。既存の結果は読み込まず、削除もしない。PrepareはGitをソース確認、chezmoiをTOML変換に使い、miseを起動しない。

mise、chezmoi、uvと、それらの対象を書き換えるエディター、自動更新などを停止してから実行する。入力と保存先はユーザープロファイル内の同一の固定NTFSボリュームに限定する。Reportは既存のファイルを指定し、Recoveryだけを新規作成する。既存のsnapshot、plan、journalを持つディレクトリの中へ新しいRecoveryを作ることも拒否する。親のIDと権限がReport取得時と異なる場合や、保存先を他の通常ユーザーが書き換えられる場合は停止し、ACLを変更して続行しない。

```powershell
$parameters = @{
    Command = 'Prepare'
    Source = '<この実装を含むクリーンなリポジトリルート>'
    SourceCommit = '<信頼済みの新ソースの40文字SHA>'
    Recovery = '<既存Reportのroots.recovery>'
    Report = 'C:\Users\tomakabe\windows-uv-direct-inventory-777d610c52b8471183b25eeb4820721a.json'
    ReportDigest = '72F7C61F39FEF910A804B27E90943442AF6FF618E7EC619F1E90F1FD84F0BD4C'
    WritersStopped = $true
}
& (Join-Path $parameters.Source 'tests\manual\windows-uv\direct-windows-uv.ps1') @parameters
```

Prepareは専用Recoveryへ実行スクリプト3個、設定候補、独立した`direct-snapshot.json`（format=`windows-uv-direct-recovery`、schema=1）、追記専用の`events/000001.json`を保存する。元環境は移動しない。成功時に表示する`recoveryDigest`をRecovery外にも保存する。後続コマンドがこのdigestでsnapshotを検証し、snapshotのハッシュで保存コードを検証する。作成に失敗したRecoveryを削除して再利用しない。

移行対象と設定入力について、通常権限で読める内容、ID、DACL、owner、group、属性、作成日時、最終更新日時を扱う。SACLと最終アクセス日時は検証対象外である。これらへの`Read-Tree`のreparse point、hardlink、ADS、未対応属性の拒否を維持する。実行用ツールは別の`toolHashes`へパスとハッシュを記録する。読み取りによる最終アクセス日時やOS監査の記録まで不変とは保証しない。

## 初回Install

```powershell
& '<Recovery>\direct-windows-uv.ps1' -Command Install `
    -Recovery '<Recovery>' -RecoveryDigest '<Prepareが表示したdigest>' -WritersStopped
```

1. ハッシュで固定したmiseの`--version`を専用環境で確認する。2026.8.5以外なら停止する。
2. 元の0.12.10、共有manifest、uv backend、4個のpointer、実cacheのuv、downloadsのuv、他27個のmetadataを同一NTFSボリュームのRecoveryへrenameする。metadataには元バイト列の新規コピーを供給する。元オブジェクトの上書き、削除、コピーによる再構成はしない。
3. 実cacheに`uv/0.12.10/incomplete`を新規作成する。子プロセスの汎用cacheとlockfile cacheはRecovery内へ隔離するが、通常のmiseが参照する実cacheにもmarkerを維持する。
4. `mise install --locked uv`を一度だけ実行する。導入先は空になった実dataの`installs/uv/0.12.10`であり、私有領域からバイナリをコピー、昇格しない。`--force`は使わない。
5. 終了コードと出力を非公開の`installer-result.json`へ保存し、新規出力の観測値をjournalへ封印する。失敗時はここで停止し、再試行も自動Restoreもしない。
6. 成功時は`mise which uv`、`mise which uvx`、canonicalの両実行ファイルの`--version`、metadataの意味内容、pointer、元8版と親の不変性を確認する。他27個のmetadataはコピーをquarantineへ退避し、元オブジェクトを戻す。
7. 元configとlockをrenameで保存し、封印済み候補を公開する。最後に実cacheのmarker用ディレクトリをquarantineへrenameし、成功した子cacheのuvを実cacheへrenameする。バイナリの場所は変えない。

検証結果は`verification.json`へ保存する。停止理由は保存先の権限が安全な場合だけ`failure-<識別子>.json`へ保存し、端末にはphaseと処理中の操作の有無だけを表示する。これらのログは端末内のパスや出力を含むため公開しない。

子プロセスの環境変数は明示的な許可リストから構成する。OSの基本パスだけを引き継ぎ、token、proxy、activationの内部変数、任意の`MISE_*`は暗黙に引き継がない。認証が必要な場合に秘密情報を引き継ぐオプションは実装していない。親のPATH、profile、sandbox設定は変更しない。

`MISE_GLOBAL_CONFIG_FILE`、`MISE_CONFIG_DIR`、`MISE_GLOBAL_CONFIG_ROOT`、`MISE_CEILING_PATHS`、system configの指定で設定探索を限定する。子configはuvだけを宣言し、公開configは他30ツールを保持する。`MISE_ENABLE_TOOLS=uv`、`MISE_NO_HOOKS=1`、`MISE_NO_ENV=1`、`MISE_YES=1`、`MISE_AUTO_INSTALL=0`を指定する。shims、state、plugins、system data、作業用ファイルはRecovery内へ置く。共有installディレクトリは使用しない。

元configのsettingsは`experimental`、`lockfile`、`lockfile_platforms`、`fetch_remote_versions_timeout`、`minimum_release_age`、`minimum_release_age_excludes`だけを受け入れる。公開後経過時間の設定は子にも保持する。未対応の設定やenv、hook、task節があれば、暗黙に捨てずPrepareを停止する。

新規ファイルには作成先から継承した権限と新しいIDがあり、元オブジェクトのACLと一致すると仮定しない。新規コピーはそれ自身の観測値で封印する。元オブジェクトの復元ではID、DACLのAIを含むSDDL、属性、作成日時、最終更新日時を完全一致で照合する。ACLの緩和や監査権限の取得はしない。

## オフラインRestoreと停止状態

```powershell
& '<Recovery>\direct-windows-uv.ps1' -Command Restore `
    -Recovery '<Recovery>' -RecoveryDigest '<Prepareが表示したdigest>' -WritersStopped
```

Restoreは保存したスクリプトだけを使い、Git、mise、chezmoi、ネットワークを起動しない。既知の新規出力をquarantineへrenameし、元オブジェクトを元の場所へ戻す。実cacheは最後に戻し、復元途中の部分installを導入済みに見せない。config公開前の失敗にも対応する。quarantine、Report、旧記録は削除しない。復元済みjournalでInstallや再Restoreはできない。

インストーラーの終了記録がない場合や、新規コピーの記録前に中断した場合、既定のRestoreは停止する。子プロセスを含む書き込み元が停止していることを確認したうえで、**記録済みの書き込み先にある未封印の内容を、作成元を問わず削除せず退避することを承認する場合だけ**、同じRestoreコマンドへ`-QuarantineInterruptedOutputs`を追加する。InstallやPrepareには指定できない。この指定は、導入を再開する許可ではない。

この復元処理は、元オブジェクトが退避先に存在し、内容、ID、権限が不変であることを要求する。設定とlock、実cacheのmarker、旧8版など、当該中断の書き込み範囲外も照合する。中断対象にある内容は2回観測し、`quarantine_only_provenance_unknown`として復元専用イベントへ記録する。導入成功やインストーラー由来とは認定しない。その後、記録した内容をquarantineへ移動して元オブジェクトを戻す。退避のrename中に再中断した場合は、記録したIDから通常のRestoreで続行できる。

イベントは操作前に書き、SHA-256の連鎖を持つファイルへ追記する。rename直後に停止した場合は、移動元か移動先のどちらに封印済みの元IDがあるかを確認して復元を進める。両方が存在する場合や、未知の内容、ID、権限の変化は停止条件である。

| 停止状態 | 動作 |
|---|---|
| `preserving`、renameの途中 | 保存済みのIDと内容から操作前後を判定する |
| `installer-exited`、終了コードが非0 | 封印した出力だけを退避し、元オブジェクトを戻せる |
| `publishing`、`installed` | 公開候補と元オブジェクトを識別して戻せる |
| `installer-started`、終了結果を保存できなかった場合 | 既定では停止。書き込み停止と未封印内容の退避を明示承認したRestoreで、元オブジェクトを戻す |
| 新規コピー作成中で観測値が未封印 | 同じ明示承認により、記録済みの作成先だけを退避して元へ戻す |
| 退避済みの元オブジェクトや中断対象外に変更がある場合 | 明示指定があっても停止する。変更を上書きしない |

親PowerShellの強制終了が子プロセス全体を終了させる保証はない。`-WritersStopped`は残った子プロセスの停止確認も含む。未封印内容の作成元は特定できず、当該書き込み先に別の処理が作った内容があれば、それも削除せず退避することになる。このため、追加指定を既定の復元手順へ常時付けない。reparse point、hardlink、未対応属性、読取不能、稼働中の書き込み、破損したjournalを無視して進む指定ではない。journalは手編集しない。

## v2026.8.5で確認した処理

2026-09-09にGitHub APIでタグを解決し、commit `a51a56b70b5172610e860ca356e3033e3b67c595`を確認した。Macにある別版のmiseの挙動は根拠にしていない。

- [初期化](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/toolset/install_state.rs#L215-L333)はツールの有効化フィルターより前に実行される。`.mise.backend.toml`を共有manifestより優先し、両方がなければ旧`.mise.backend.json`または`.mise.backend`へフォールバックする。取得した実装に27個の`.mise.backend.toml`を削除する処理はない。`full`の角括弧内にoptionがある場合の書換えはあり、入口はこの形式を拒否する。共有manifestの`opts`は保持し、共有側と個別TOMLの値が異なっても統合せず、それぞれの意味を保存する。
- [導入](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/backend/mod.rs#L2632-L2779)はパスとcache markerから導入済みか判定する。[ディレクトリ作成](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/backend/mod.rs#L3065-L3108)と[展開](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/backend/static_helpers.rs#L573-L700)は導入先を削除、再作成するため、元オブジェクトを先に退避する必要がある。
- [manifestの保存](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/toolset/install_state.rs#L566-L591)は共有manifestと対象ツールのTOMLを更新する。`--locked`はmanifestの変更を防がない。新しいuv metadataには、[設定のoption処理](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/config/config_file/mise_toml.rs)と[永続optionの定義](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/toolset/tool_version_options.rs)に従い、`opts.platforms.windows-arm64.asset_pattern`も保持する。
- [lockfile](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/lock_file.rs)は汎用cacheの`lockfiles`にも書く。このためcache全体を実cacheに指定せず、実cacheの不完全markerを別途維持する。
- [runtime参照](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/runtime_symlinks.rs)はWindowsで相対パスを含む通常ファイルを使う。[再生成](https://github.com/jdx/mise/blob/a51a56b70b5172610e860ca356e3033e3b67c595/src/config/mod.rs#L3033-L3077)はruntime参照とshimsを扱うため、uvだけのtoolsetと専用shimsを使用する。

## 移行後の通常更新

通常更新には元ディレクトリの退避を組み込まない。別のツール名、永続alias、独自install root、専用updaterは追加しない。初回移行が完了した後は、隔離した設定とlockで公式miseの次のコマンドを使う。隔離にはglobal設定ファイルの指定だけでなく、設定ディレクトリと探索上限の指定も必要である。

```powershell
mise lock --global --platform linux-x64,linux-arm64,macos-arm64,windows-x64,windows-arm64 --bump uv
```

他30ツールの内容が変わっていないことを確認したlockを通常の管理手順で反映してから、`mise install --locked uv`で新しい版を通常の場所へ導入する。公開後経過時間の条件を満たさない版を強制採用しない。旧版を自動削除する更新操作は使わない。`mise upgrade`を別途選ぶ場合は`mise upgrade uv --no-prune`で旧版を残す。

## 検証範囲

`tests/test_windows_uv_direct_plan.py`が既存Planの設定、lock、pointer分類、保存先を検査する。`tests/test_windows_uv_direct.py`はmacOS上の既存PowerShellで合成fixtureを作り、成功後のRestore、導入失敗、rename中断、未封印の導入とコピーの中断、digest不一致、元8版と4証跡の保持、27個のmetadata保護を検査する。未封印内容を扱う試験では、明示指定なしでの拒否、指定した場合の原物復元、作成元不明のファイルの退避保存、バックアップや設定の改変拒否、退避renameの再中断を扱う。トランザクション試験ではネイティブのIDとrename、TOML解析、子プロセスの導入をmockへ置き換える。追加の試験では既存chezmoiでlockと候補configのTOML往復変換を検査する。

WindowsのPlan実行とReportの観測内容は確認済みである。新入口のNTFSでの直接InstallとRestore、実際の候補TOMLを使うmise子プロセス、ネットワーク経由の公式導入、sandbox内ワークロードは未検証である。mockの成功でこれらを代用しない。以前のコピー候補の公開失敗は原因不明のままであり、この実装をその原因解決とは扱わない。
