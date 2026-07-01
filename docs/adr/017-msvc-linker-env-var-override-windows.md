# ADR-017: Windows の MSVC リンカーは CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER で明示指定する

## Status

Accepted

## Context

Windows で `cargo build`（`windows-msvc` ターゲット）は `link.exe`（MSVC リンカー）を必要とする。一方、winget で導入している Coreutils for Windows (`Microsoft.Coreutils`, `reference/windows/configuration.dsc.yaml`) は GNU coreutils 版の `link`（ハードリンク作成用）を提供し、これが `C:\Program Files\coreutils\bin\link.exe` として Machine PATH（MSI が登録、現ユーザーには書き込み権限なし）に存在する。

rustc/cc クレートの MSVC ツールチェイン解決は「PATH 上に `link.exe` が見つかればそれを無条件使用し、無い場合のみ vswhere.exe で自動検出する」仕様のため、coreutils 版が存在するだけで vswhere による正しい自動検出が丸ごとスキップされ、誤った `link.exe` が呼ばれてリンクエラーになる。

Windows のプロセス初期 PATH は Machine PATH → User PATH の順で連結されるため、User PATH で新ディレクトリを prepend しても Machine PATH 上の coreutils を追い越せない（実機確認: 現ユーザーでの当該ファイルへの書き込み・リネームは Access Denied）。

本リポジトリの既存 Windows 自動化スクリプトはすべて非昇格のユーザースコープ操作のみであり、この方針を崩したくない。また Copilot CLI のシェルセッションでは `$PROFILE` が読み込まれないため、プロファイルで `$env:Path` を書き換える方式は効かない。ユーザー環境変数（レジストリ永続化）ならこの制約を回避できる。`.cargo/config.toml` への絶対パスのハードコードは、MSVC ツールセットのバージョンフォルダが Build Tools 更新で変わりうるため陳腐化リスクがある。

この衝突は上流 `microsoft/coreutils` でも既知の不具合として認識されている（Issue #123「`link` can conflict with MSVC linker」、Issue #31 の重複としてクローズ）。メンテナは `coreutils-manager disable <utility>` による個別無効化を用意しているが、README の「Shell conflicts」一覧（CMD/PowerShell 組み込みコマンドとの衝突が対象）に `link` は載っておらず、Coreutils 自体が preview 段階で無効化にも管理者権限が必要と見られる（未検証）ため、上流対応より本 ADR の方式のほうが現時点で堅牢と判断した。

## Decision

coreutils の `link.exe` 自体は変更・削除・リネームしない。代わりに Cargo 公式の `CARGO_TARGET_<triple>_LINKER` 仕組みを使い、`CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER` をユーザースコープ環境変数として設定する。PATH の並び順にも `$PROFILE` にも依存しない。

値（MSVC `link.exe` の絶対パス）は `vswhere.exe` で毎回動的に解決し、ハードコードは持たない。実装は `home/run_onchange_after_20-resolve-msvc-linker.ps1.tmpl`（Windows 限定）。安定した変更検知元が無いため `{{ now }}` を埋め込み `chezmoi apply` の度に強制再実行させ、解決結果が現在値と同じ場合は書き込みを行わない（冪等）。VS Build Tools/vswhere が未導入でもエラーにせず fail-soft で継続する。

併せて `reference/windows/configuration.dsc.yaml` に VS 2022 Build Tools 本体と C++ ワークロード（`Microsoft.VisualStudio.DSC/VSComponents`, `Microsoft.VisualStudio.Workload.VCTools`）を追加した。`WinGetPackage` リソースにはインストーラー追加引数を渡すプロパティが無いため。

## Consequences

- coreutils の `link` コマンドは PATH 上に存在し続ける。Cargo のビルドだけが環境変数経由で正しい MSVC リンカーを使う
- `chezmoi apply` の実行時間がわずかに伸びる（vswhere 実行分）
- 新規マシンでは `winget configure -f reference/windows/configuration.dsc.yaml` を管理者権限で手動実行するまで解決が効かない
- 他プロジェクトが独自の `CARGO_TARGET_*_LINKER` を `.cargo/config.toml` で設定している場合、環境変数側が優先され意図しない上書きになりうる（現状未確認）
- amd64 Windows のみ対応。環境変数名 (`CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER`) と vswhere 検索パターン (`Hostx64\x64`) がターゲットトリプル/ホスト固定のため、ARM64 Windows（Coreutils ARM64 版でも同種の衝突が起こりうる）は未対応。将来的に `.chezmoi.arch` での分岐が必要
