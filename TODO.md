# v2.0.0 リリースまでの残作業

> このファイルは v2.0.0 リリース後に削除する。

## 完了済み（WSL 環境で実施）

### セッション概要

dotfiles 管理をシンボリンク + bootstrap.sh から **chezmoi + mise** に全面移行した。
PR: https://github.com/torumakabe/dotfiles/pull/3（マージ済み）

### 実施内容

| Phase | 内容 | 状態 |
|-------|------|------|
| 1 | chezmoi 基盤（テンプレート化、プラットフォーム検出） | ✅ 完了 |
| 2 | Copilot Guard を bash+PowerShell → Python に統一 | ✅ 完了 |
| 3 | 13個の setup/*.sh → 5つの run_once_* テンプレート | ✅ 完了 |
| 4 | Windows 設定を reference/windows/ に整理、DSC 更新 | ✅ 完了 |
| 5 | レガシーファイル削除、README/MIGRATION.md 作成 | ✅ 完了 |

### 主な技術判断

- `[safe] directory = *` を gitconfig から削除（セキュリティ改善）
- Azure CLI ARM64: pip workaround 削除 → ネイティブ APT
- `brew install python@3` 削除（Python は uv に一元化）
- WSL + native Linux の gitconfig を1テンプレートに統合（`.isWSL` で分岐）
- Docker インストールは WSL ではスキップ（Docker Desktop 側で管理）

## 残作業

### 1. macOS でのテスト

```zsh
# ~/dotfiles で実行
chezmoi init --source ./home --apply --dry-run
```

確認ポイント:

- [ ] `chezmoi cat ~/.gitconfig` で 1Password SSH 署名パス（`/Applications/1Password.app/...`）が正しい
- [ ] `chezmoi cat ~/.gitconfig-mac` の内容が妥当
- [ ] `chezmoi cat ~/.zshrc` で mise 初期化パスが正しい
- [ ] `run_once_before_10-install-packages.sh.tmpl` が Homebrew でインストール
- [ ] Copilot Guard テスト: `echo '{"method":"validate","path":"/etc/passwd"}' | uv run ~/.copilot/hooks/scripts/copilot-guard.py`

### 2. Windows でのテスト

```powershell
# 適用は手動。reference/windows/ の設定ファイルを確認
```

確認ポイント:

- [x] `reference/windows/configuration.dsc.yaml` の内容が妥当（jdx.mise 追加済み、Python.Python.3.13 削除済み）
- [x] Copilot Guard テスト: `'{"method":"validate","path":"C:\\Windows\\System32"}' | uv run $HOME\.copilot\hooks\scripts\copilot-guard.py`
- [x] `copilot-guard.json` の PowerShell エントリが動作する

### 3. v2.0.0 リリース（全テスト完了後）

```bash
# リポジトリルートで実行
git tag -a v2.0.0 -m "feat!: migrate to chezmoi + mise architecture"
git push origin v2.0.0
```

GitHub Release を作成し、MIGRATION.md へのリンクを含める。

### 4. このファイル（TODO.md）を削除

```bash
git rm TODO.md
git commit -m "chore: remove TODO.md after v2.0.0 release"
git push
```
