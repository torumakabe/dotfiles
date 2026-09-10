# ADR-013: mise lockfile 変更時に install / reshim を自動同期する

## Status

Accepted

## Context

`mise upgrade` 等で `~/.config/mise/mise.lock` が更新されても、ローカルの `mise install` / `mise reshim` は自動で走らない。結果として shim と install marker が古いまま残り、shell 起動時の `_mise_hook`（`mise hook-env`）で `mise WARN missing:` が出る。Windows では `installs\<tool>\<ver>` が junction として作られるため shim が一度欠落すると復元されにくく、`MISE_AUTO_INSTALL=true`（既定）により毎起動で再 install が試みられて rustup の `info: syncing channel updates ...` も繰り返し表示される。

`private_mise.lock` は chezmoi で管理しているため、lockfile が更新された apply の瞬間に install/reshim を流せば構造的に同期できる。ローカル Dev Container（`REMOTE_CONTAINERS=true` かつ Codespaces ではない）はコンテナ作成直後の dotfiles 適用時点で GitHub 認証を持たないことがあり、この状態で `mise install` を実行すると GitHub API のレート制限や 401 でコンテナ作成そのものが失敗しうる。

## Decision

`home/run_onchange_after_15-mise-sync-tools.{sh,ps1}.tmpl` を新設し、`{{ include "dot_config/mise/private_mise.lock" | sha256sum }}` を template hash に埋め込む。chezmoi の `run_onchange` は hash 変化時のみ再実行するため、lockfile が変わるたびに `mise install` と `mise reshim` を流して install marker と shim を lockfile と同期させる。

- 実行順は `run_once_before_20-install-mise`、`run_onchange_after_15-mise-sync-tools`、`run_once_after_20-mise-install`、`run_onchange_after_21-link-mise-shims` となる。番号 15 は、lockfile 変更の同期を通常のツール導入と macOS の shim symlink 更新より前に実行するために使う。
- mise が PATH に無い環境（CI 等）は skip して exit 0、apply 全体を止めない。
- ローカル Dev Container では、`MISE_GITHUB_TOKEN` / `GITHUB_API_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN` がすべて未設定かつ `gh auth token` も失敗する場合、install/reshim を実行せず成功終了（exit 0）し、`gh auth login` 後に `GITHUB_TOKEN=$(gh auth token) mise install --yes` を手動実行するよう案内する。Codespaces と通常 Unix/macOS/Linux/WSL は本条件の対象外で、従来どおり lockfile 起点の install/reshim を維持する。
- mise 用の GitHub token が未設定で `gh` が認証済みの場合は、`gh auth token` から取得した token を `MISE_GITHUB_TOKEN` としてフックのプロセス内だけで `mise install` へ渡す。`gh` が未認証の環境では従来の動作を変更しない。
- `mise install` / `mise reshim` は一括処理し、いずれかが失敗した場合は原因と `chezmoi apply` による再実行方法を表示して非ゼロ終了する。失敗した `run_onchange` の状態は成功として保存されないため、原因解消後の apply で再実行される。

## Consequences

- 起動時の `mise WARN missing:` と rustup の `info: syncing channel updates ...` が解消する。
- lockfile が変わった `chezmoi apply` の所要時間が数秒〜数十秒延びる（unchanged 時の install は短時間で完了）。
- install / reshim の失敗時は apply が失敗し、lockfile と実体の不整合が残ったことを利用者が認識して明示的に再実行できる。
- lockfile 以外の理由（手動 `mise uninstall` 等）で shim が欠落したケースは本フックでは復元されないため、その場合は手動で `mise install && mise reshim` を実行する（`docs/troubleshooting.md` 参照）。
- ローカル Dev Container の GitHub 未認証スキップは成功終了のため、同一内容の lockfile に対する `run_onchange` の hash は再試行されない。手動での初回同期後は、後続の lockfile 変更で通常の自動同期に戻る。
- ADR-009（Windows での mise rust home 分離）の症状（junction marker と install 判定の揺れ）を直接修正するわけではないが、結果として顕在化を抑止する。
