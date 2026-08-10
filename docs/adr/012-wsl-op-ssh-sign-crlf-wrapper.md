# ADR-012: WSL では op-ssh-sign-wsl.exe を CR 除去ラッパー経由で呼ぶ

## Status

Accepted

## Context

Git 2.36 未満の WSL で 1Password の SSH 署名 (`gpg.format = ssh`) を使うと、`git verify-commit` / `git log --show-signature` が `Could not verify signature.` で失敗する。原因は git と 1Password の Windows バイナリの間の改行の不整合:

1. git は `op-ssh-sign-wsl.exe -Y find-principals` を呼び stdout から principal を取り出す
2. Windows 流に CRLF で出力されるため `993850+...github.com\r\n` となる
3. git は `\n` のみを剥がし、`-I '993850+...github.com\r'` を後段の `-Y verify` に渡す
4. allowed_signers の principal は `\r` を含まないので照合が失敗する

`strace` で `\r` 混入を確認済み、ローカル `ssh-keygen -Y verify` ではファイルもキーも有効、commit object 自体は正常に署名されている（GitHub 側の Verified 表示には影響しない）。WSL+op-ssh-sign-wsl.exe 固有の interop 問題で、Linux ネイティブ (`/opt/1Password/op-ssh-sign`) や Windows ネイティブ (`op-ssh-sign.exe`) では発生しない。

## Decision

WSL 限定で `op-ssh-sign-wsl.exe` の stdout/stderr から CR を剥がすラッパー `~/.local/bin/op-ssh-sign-wrapper.sh` を経由させる。`isWSL` と WSL interop の実体の論理積で 3 ヶ所をゲート:

| 配置 | WSL | ネイティブ Linux | macOS / Windows |
| --- | --- | --- | --- |
| `~/.local/bin/op-ssh-sign-wrapper.sh` | 配置 | `home/.chezmoiignore` で除外 | `.gitconfig-linux` ごと除外 |
| `gpg.ssh.program` | wrapper を指す | `/opt/1Password/op-ssh-sign` | 各 OS の値 |

署名 (`-Y sign`) は `-s <file>` にバイナリを書き出し stdout を経由しないため、CR 除去で改ざんされない。

`isWSL` (`home/.chezmoi.toml.tmpl`) は `/proc/sys/kernel/osrelease` が `microsoft` を含むかどうかだけで判定する。しかし Docker Desktop の WSL2 バックエンドで動く Dev Container はホストの WSL カーネルを共有するため、`osrelease` は実 WSL と同一の値になる。この条件だけでは両者を区別できないことを実測で確認した。

そこで本 ADR の 3 ヶ所では、`isWSL` に加えて `/proc/sys/fs/binfmt_misc/WSLInterop` の存在を確認する。ラッパーは Windows 側の `op-ssh-sign-wsl.exe` を interop 経由で起動するため、interop が無ければ機能しない。`/run/WSL` や `/mnt/wsl` の有無でも同じ結果になるが、これらは interop が使えることを直接には示さない。ラッパーは `windowsUser` から `/mnt/c/Users/<user>/...` を組み立てるため、この値が空の場合も機能しない。`chezmoi init` を非対話で実行した場合や、interop が無い状態で初期化した場合に空になる。3 ヶ所の条件は次のとおり。

- `home/dot_gitconfig-linux.tmpl`：`{{ if and .isWSL (stat "/proc/sys/fs/binfmt_misc/WSLInterop") (ne .windowsUser "") }}` で `gpg.ssh.program` を切り替える
- `home/.chezmoiignore`：同じ条件の否定でラッパーの配布を除外する
- `home/.chezmoi.toml.tmpl`：`isWSL`、interop、`stdinIsATTY` の論理積で `windowsUser` の prompt をゲートする

参照側と配布側の条件が食い違うと、`gpg.ssh.program` が配布されていないファイルを指す。`tests/test_platform_parity.py` の `WrapperGateParityTests` が、両テンプレートが同じ述語を使っていることを静的に検査する。

`isWSL` 自体を 2 条件の論理積へ変更する案は採らなかった。`isWSL` は `home/run_once_after_30-install-tools.sh.tmpl` で Docker Engine と draw.io の導入判断にも使われており、そこで求められる意味は「native Linux か」である。interop 条件を `isWSL` へ入れると、interop を持たない Dev Container や interop を無効化した WSL でこれらが導入対象になる。加えて、新しいデータキーを増やすと、既存環境の `~/.config/chezmoi/chezmoi.toml` に当該キーが無いまま `chezmoi apply` した際に `map has no entry for key` で失敗する（実測）。`.chezmoi.toml.tmpl` は `chezmoi init` 時にしか評価されないのに対し、`dot_gitconfig-linux.tmpl` と `.chezmoiignore` は `chezmoi apply` のたびに評価されるため、この形なら環境の変化に追従する。

## Consequences

- WSL でも `git verify-commit` / `git log --show-signature` がローカル検証できる
- Git 2.36 以降は find-principals 出力の `\r` を剥がすが、Git 2.36 未満への fallback が残る対応 WSL 経路では wrapper が必要になる。撤去条件は `.github/copilot-instructions.md` のワークアラウンド節で追跡する
- wrapper は bash の `set -o pipefail` と process substitution に依存するため、`/usr/bin/env bash` が必須
- `wsl.conf` で interop を無効化した WSL では `isWSL` は真のままだが、本 ADR の 3 ヶ所では偽と同じ扱いになる。その環境では `.exe` を起動できずラッパーも機能しないため、この扱いが正しい
- interop を確認していなかった時期は、Dev Container で `gpg.ssh.program` がラッパーを指し、`home/.chezmoiignore` の `not .isWSL` ゲートが外れてラッパーが不要に配布され、TTY があれば `windowsUser` の入力を求められた（実測）
- `stat "/proc/sys/fs/binfmt_misc/WSLInterop"` を含む同じ条件が `dot_gitconfig-linux.tmpl` と `.chezmoiignore` に重複する。いずれかを変更する場合は両方を揃える必要があり、`tests/test_platform_parity.py` がその一致を検査する
- `windowsUser` が空の WSL では、ラッパーではなく `/opt/1Password/op-ssh-sign` を指す。どちらもその環境では機能しないが、空のユーザー名を含むパスを指すよりは失敗の原因を追いやすい。`chezmoi init` を対話的に再実行すれば解消する
