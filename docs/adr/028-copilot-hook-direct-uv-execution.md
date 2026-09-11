# ADR-028: Copilot は mise 管理ツールを実体パスから実行する

## Status

Accepted

## Context

Copilot CLIのcommand hookはruntime親プロセスの環境を継承する。従来の`MISE_ENABLE_TOOLS=uv mise exec -- uv run ...`は、hookごとにmiseと設定を読み込み、親のPATHからmiseを実行できることを前提としていた。

`activate_shims = false`はshim farmを除外するが、OSや他のパッケージ管理ツールが提供する同名コマンドよりmiseの実体ディレクトリを優先しない。通常のsandbox shellとcommand hookは環境の取得方法も異なるため、両方で実体を直接解決できる構成が必要である。

## Decision

miseはツールの導入、バージョン固定、更新を担う。global configへ`activate_shims = false`と`activate_aggressive = true`を設定し、対話zshとPowerShellでは公式の`mise activate`、Unixの共有profileでは公式の`mise env`を使う。

Copilotのcommand hook 5件はruntime親PATH上のuvを`uv run ...`で直接起動する。hook内ではmiseを起動せず、`MISE_ENABLE_TOOLS`も設定しない。通常のsandbox shellはhost側で生成して継承したmise実体PATHを使う。

Windowsは非対話環境との互換性のためUser PATHのshim登録を維持する。実体PATHの契約は、PowerShell profileを読み込んだターミナルからCopilot CLIを起動する場合に適用する。

## Consequences

- hookごとのmise起動と設定読み込みがなくなり、親プロセスが提供するuvの実体PATHが実行条件になる。
- shim登録は残るが、通常のshellとhookはshimを選ばない。
- sandboxからmise管理ツールのsymlink先を読むための設定はADR-029、uv cacheへの書き込みはADR-030で扱う。
- WSL2、macOS、Windowsの実測結果と未確認範囲は[実機検証記録](../copilot-sandbox-verification.md#検証記録)で管理する。Copilot hook 5件全体と、WindowsのGUIまたはprofileを読まない起動は未検証である。
