# Migration Guide: v1.x → v2.0.0

v2.0.0 は dotfiles 管理を **シンボリンク + bootstrap.sh** から **chezmoi** ベースに全面移行する破壊的変更です。

このガイドでは、v1.x 環境を v2.0.0 に移行する手順をプラットフォーム別に説明します。

## 変更の概要

| 項目 | v1.x | v2.0.0 |
|------|------|--------|
| 設定ファイルの配置 | シンボリンク (`bootstrap.sh`) | chezmoi テンプレート |
| プラットフォーム分岐 | gitconfig-wsl / gitconfig-linux-native の2ファイル | gitconfig-linux.tmpl 内で WSL 分岐 |
| ツールインストール | setup/*.sh (13個の個別スクリプト) | run_once_* (5個のテンプレート) |
| Copilot Guard | bash + PowerShell 二重実装 | Python 単一スクリプト (uv run) |
| Python 管理 | brew install python@3 / pip / WinGet | uv に一元化 |
| Windows 設定 | host-files/windows-wsl/ | reference/windows/ |
| セキュリティ | `[safe] directory = *` あり | 削除済み |

## 事前準備（全プラットフォーム共通）

### 1. 現状のバックアップ

任意のディレクトリで実行:

```bash
# 既存の dotfiles リポジトリをバックアップ
cp -r ~/dotfiles ~/dotfiles.bak

# 現在の設定ファイルを退避（シンボリンクが壊れる前に）
mkdir -p ~/dotfiles_migration_backup
cp -L ~/.gitconfig ~/dotfiles_migration_backup/
cp -L ~/.gitconfig-linux ~/dotfiles_migration_backup/ 2>/dev/null
cp -L ~/.gitconfig-mac ~/dotfiles_migration_backup/ 2>/dev/null
cp -L ~/.gitconfig-corp ~/dotfiles_migration_backup/ 2>/dev/null
cp -L ~/.zshrc ~/dotfiles_migration_backup/
cp -L ~/.mise.toml ~/dotfiles_migration_backup/
```

### 2. chezmoi のインストール

任意のディレクトリで実行:

```bash
# Linux / WSL
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b ~/.local/bin

# macOS
brew install chezmoi

# Windows
winget install twpayne.chezmoi
```

### 3. uv のインストール（Copilot Guard に必要）

```bash
# mise 経由（推奨）
mise install uv

# または直接
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Linux（WSL）からの移行

v1.x では `bootstrap.sh` がシンボリンクを作成し、`setup/*.sh` でツールをインストールしていた。

### 手順

任意のディレクトリで実行（chezmoi がリポジトリのクローンと配置を自動で行う）:

```bash
# 1. 既存シンボリンクの除去
#    chezmoi は実ファイルで上書きするが、念のため手動で外す
rm -f ~/.gitconfig ~/.gitconfig-linux ~/.gitconfig-corp ~/.zshrc ~/.mise.toml

# 2. chezmoi で初期化＋適用
chezmoi init --apply torumakabe

# 初回プロンプト:
#   Windows username → (WSLのWindows側ユーザー名を入力)
#   Corp username    → (社内Gitユーザー名を入力、不要なら空)

# 3. 動作確認
git config user.name          # → Toru Makabe
git config gpg.ssh.program    # → /mnt/c/.../op-ssh-sign-wsl.exe
cat ~/.gitconfig | grep safe   # → 出力なし（削除済み）
mise doctor                    # → エラーなし
```

### 注意事項

- `[safe] directory = *` が削除されるため、他ユーザー所有のリポジトリで `git` コマンドが拒否される場合がある。必要なディレクトリは個別に追加する:
  ```bash
  git config --global --add safe.directory /path/to/dir
  ```
- Copilot Guard フックが bash → Python (uv run) に変わる。uv が未インストールの場合、フックは fail-safe deny になる。
- 旧スクリプト `copilot-guard.sh` / `copilot-guard.ps1` は ~/.copilot/hooks/scripts/ に残っている場合がある。新しい `copilot-guard.json` が `uv run copilot-guard.py` を指すため、旧ファイルは無視されるが、不要なら削除してよい。

---

## Linux（ネイティブ）からの移行

WSL との違いは 1Password のパスのみ。

### 手順

任意のディレクトリで実行:

```bash
rm -f ~/.gitconfig ~/.gitconfig-linux ~/.gitconfig-corp ~/.zshrc ~/.mise.toml
chezmoi init --apply torumakabe

# 初回プロンプト:
#   Windows username → (空でOK、ネイティブLinuxでは不使用)
#   Corp username    → (入力)
```

### 確認

```bash
git config gpg.ssh.program    # → /opt/1Password/op-ssh-sign
```

---

## macOS からの移行

v1.x では `host-files/macos/bootstrap.sh` が brew でパッケージをインストールし、シンボリンクを作成していた。

### 手順

任意のディレクトリで実行:

```bash
# 1. 既存シンボリンクの除去
rm -f ~/.gitconfig ~/.gitconfig-mac ~/.gitconfig-corp ~/.zshrc ~/.mise.toml

# 2. chezmoi インストール（未導入の場合）
brew install chezmoi

# 3. 適用
chezmoi init --apply torumakabe

# 初回プロンプト:
#   Windows username → (空でOK)
#   Corp username    → (入力)
```

### brew install python@3 について

v2.0.0 では `brew install python@3` を削除し、Python は uv に一元化している。
既に brew でインストール済みの場合、アンインストールは不要だが、今後は uv を使うことを推奨する:

```bash
# uv 経由で Python を使う（インストール不要で自動取得される）
uv run script.py

# 不要であれば brew 版を削除
brew uninstall python@3
```

---

## Windows からの移行

v1.x では `host-files/windows-wsl/configuration.dsc.yaml` を手動で WinGet DSC に渡してパッケージをインストールしていた。設定ファイルの管理は WSL 側で行い、Windows ネイティブには直接配置していなかった。

### 手順

PowerShell で実行:

```powershell
# 1. chezmoi インストール
winget install twpayne.chezmoi

# 2. 設定適用
chezmoi init --apply torumakabe

# 初回プロンプト:
#   Windows username → (Windowsユーザー名)
#   Corp username    → (入力)

# 3. GUI アプリ・ツールの一括インストール（手動）
#    DSC ファイルの場所が変更されている点に注意
winget configure -f (chezmoi source-path)/../reference/windows/configuration.dsc.yaml
```

### DSC の変更点

- **移動**: `host-files/windows-wsl/` → `reference/windows/`
- **削除**: `Python.Python.3.13`（Python は uv に一元化）
- **追加**: `jdx.mise`（mise の Windows ネイティブ導入）
- **追加**: `x-motemen.ghq`

---

## GitHub Codespaces からの移行

v1.x では `bootstrap.sh` が Codespaces を検出してツールインストールをスキップしていた。
v2.0.0 では `install.sh` が chezmoi をブートストラップし、run_once_ テンプレートが環境を検出してスキップする。

### 手順

特別な操作は不要。GitHub の設定でこのリポジトリを dotfiles として登録していれば、自動的に v2.0.0 の設定が適用される。

Codespaces では以下がスキップされる:
- `run_once_after_30-install-tools.sh`: Azure CLI, Docker, Rust 等のインストール
- デフォルトシェルの変更 (`chsh`)

---

## ロールバック

問題が発生した場合、v1.0.0 の状態に戻すことができる:

```bash
# chezmoi の管理を解除（ファイルは残る）
chezmoi purge

# バックアップから復元
cp ~/dotfiles_migration_backup/.gitconfig ~/
cp ~/dotfiles_migration_backup/.zshrc ~/
# ... 他のファイルも同様

# または v1.0.0 タグからクローンし直す
cd ~
rm -rf ~/dotfiles
git clone --branch v1.0.0 https://github.com/torumakabe/dotfiles.git ~/dotfiles
cd ~/dotfiles
./bootstrap.sh
```

---

## トラブルシューティング

### chezmoi apply でテンプレートエラーが出る

```
chezmoi: template: .chezmoiignore: map has no entry for key "isWSL"
```

`chezmoi init` を実行して設定ファイルを生成してから `chezmoi apply` を実行する。

### git commit が GPG 署名でハングする

1Password の SSH 署名エージェントが応答していない可能性がある。1Password アプリが起動しているか確認する。WSL の場合、Windows 側の 1Password が動作している必要がある。

### Copilot Guard が常に deny を返す

uv がインストールされているか確認する:

```bash
command -v uv    # パスが表示されること
uv python list   # Python が利用可能であること
```

### run_once_ スクリプトが sudo を要求して停止する

Codespaces 以外の環境では、パッケージインストールに sudo が必要。
パスワードを入力するか、sudoers を設定する。
