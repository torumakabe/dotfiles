# ADR-013: mise lockfile 変更時に install / reshim を自動同期する

## Status

Accepted

## Context

`mise upgrade` 等で `~/.config/mise/private_mise.lock` が更新されても、ローカルの `mise install` / `mise reshim` は自動で走らない。結果として shim と install marker が古いまま残り、shell 起動時の `_mise_hook`（`mise hook-env`）で `mise WARN missing:` が出る。Windows では `installs\<tool>\<ver>` が junction として作られるため shim が一度欠落すると復元されにくく、`MISE_AUTO_INSTALL=true`（既定）により毎起動で再 install が試みられて rustup の `info: syncing channel updates ...` も繰り返し表示される。

`private_mise.lock` は chezmoi で管理しているため、lockfile が更新された apply の瞬間に install/reshim を流せば構造的に同期できる。

## Decision

`home/run_onchange_after_15-mise-sync-tools.{sh,ps1}.tmpl` を新設し、`{{ include "dot_config/mise/private_mise.lock" | sha256sum }}` を template hash に埋め込む。chezmoi の `run_onchange` は hash 変化時のみ再実行するため、lockfile が変わるたびに `mise install` と `mise reshim` を流して install marker と shim を lockfile と同期させる。

- 番号 15 は `run_onchange_after_21-link-mise-shims.sh.tmpl`（macOS の shim symlink, ADR-002）より前で `run_once_after_20-mise-install.sh.tmpl` の後に走らせるための位置取り。
- mise が PATH に無い環境（CI 等）は skip して exit 0、apply 全体を止めない。
- mise 用の GitHub token が未設定で `gh` が認証済みの場合は、`gh auth token` から取得した token を `MISE_GITHUB_TOKEN` としてフックのプロセス内だけで `mise install` へ渡す。`gh` が未認証の環境では従来の動作を変更しない。
- `mise install` / `mise reshim` が失敗しても exit 0 で警告のみ。次回 apply で hash 再評価により再試行される。

## Consequences

- 起動時の `mise WARN missing:` と rustup の `info: syncing channel updates ...` が解消する。
- lockfile が変わった `chezmoi apply` の所要時間が数秒〜数十秒延びる（unchanged 時の install は短時間で完了）。
- lockfile 以外の理由（手動 `mise uninstall` 等）で shim が欠落したケースは本フックでは復元されないため、その場合は手動で `mise install && mise reshim` を実行する（`docs/troubleshooting.md` 参照）。
- ADR-009（Windows での mise rust home 分離）の症状（junction marker と install 判定の揺れ）を直接修正するわけではないが、結果として顕在化を抑止する。
