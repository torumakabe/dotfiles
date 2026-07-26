# ADR-020: gitleaks の pre-commit は Git の設定ベースフックで配る

## Status

Proposed

Windows と WSL での検証が完了していない。macOS と Linux コンテナでの検証結果は「検証記録」に、残る検証項目は「引き継ぐ検証」に記す。

## Context

ADR-018 で、機械全体への Git hook 配布を `core.hooksPath` から `init.templateDir` へ移した。`init.templateDir` は `git init` / `git clone` の瞬間に `~/.config/git/templates/hooks/pre-commit` を各リポジトリの `.git/hooks/` へコピーする。コピー後は repo-local な通常ファイルになるため、ADR-018 が対処した「共有 hooks ディレクトリが全リポジトリを汚染する」問題は起きない。

この方式には、gitleaks の適用範囲を狭める性質が二つ残っていた。

第一に、リポジトリ固有の hook マネージャがコピー済みの hook を置き換える。lefthook を導入したリポジトリで開発者が `lefthook install` を実行すると、lefthook は `.git/hooks/pre-commit` を自身の生成物へ差し替える。lefthook は退避先 `pre-commit.old` を作ったと表示するが、生成した hook は `pre-commit.old` を呼び出さない。したがって以後の commit で gitleaks は実行されず、その事実を知らせる出力も出ない。

第二に、既存リポジトリが対象にならない。`init.templateDir` は新規作成時にしかコピーしないため、開発者が各リポジトリで `git init` を再実行して backfill する必要がある。この操作は安全かつ冪等だが、実行の判断と実施が開発者に委ねられている。

### ADR-018 の運用で実際に起きたこと

第二の性質は、想定されたトレードオフにとどまらなかった。ADR-018 を採用した機械で、gitleaks が約 3 週間にわたり既存リポジトリで一度も実行されない状態が続いた。経緯は次のとおりである。

1. lefthook を使うリポジトリを clone し、`lefthook install` を実行した。当時の配布方式は global の `core.hooksPath` であり、lefthook はこれを尊重して共有 hooks ディレクトリへ書き込んだ。結果として全リポジトリの hook が置き換わった。
2. この事故への対処として、配布方式を `init.templateDir` へ移した（ADR-018）。同時に、汚染された共有 hooks ディレクトリの実体を削除した。
3. 既存リポジトリへの backfill は実行されなかった。ADR-018 はこれを開発者の手作業として残していた。

結果として、既存リポジトリは新しい配布経路からも古い配布経路からも外れた。ADR-018 はこの状態を検知する仕組みを持たないため、開発者は保護が失われたことに気づけなかった。

この経緯から、本 ADR は次の二つを要件とする。

- **要件 1**: gitleaks の pre-commit が、リポジトリの作成時期を問わず実行される。
- **要件 2**: リポジトリレベルの hook マネージャを導入しても、gitleaks が実行され続ける。

### Git 2.54 の設定ベースフック

Git 2.54 は、`gitconfig` に hook を定義する設定ベースフックを追加した。設定ベースフックは `$GIT_DIR/hooks` とは別の層で管理され、両者は加算的に実行される。global スコープに定義すれば、リポジトリの作成時期や `.git/hooks` の内容に関わらず実行される。この二つの性質が、要件 1 と要件 2 にそれぞれ対応する。

一方で、この機能は git のバージョンに依存する。2.54 より前の git は `[hook]` セクションをエラーも警告も出さずに無視する。したがって、設定を配るだけでは保護が効いているか分からない。ADR-018 で起きた沈黙と同じ形の失敗を繰り返さないために、バージョン要件を満たす git を各プラットフォームで用意し、満たせない場合はそれを開発者へ伝える必要がある。

## Decision

### 1. 設定ベースフックとして gitleaks を登録する

`~/.gitconfig`（`home/dot_gitconfig.tmpl`）へ次を追加し、走査スクリプトを `~/.local/bin/gitleaks-pre-commit`（`home/dot_local/bin/executable_gitleaks-pre-commit`）へ配置する。

```ini
[hook "dotfiles-gitleaks"]
	event = pre-commit
	command = "sh ~/.local/bin/gitleaks-pre-commit"
```

`command` は `sh` 経由で呼ぶ。パスを直接書くと、実行ビットが立っていない場合に gitleaks が一度も走らないまま commit だけが拒否される。`sh` を挟めばこの依存が無くなる。Windows でファイルの実行ビットがどう扱われるかは検証していないため、依存しない形を選んだ。

`gitconfig` の値は引用しないと `;` や `#` 以降が切り捨てられるため、`command` の値は二重引用符で囲む。friendly-name にイベント名（`pre-commit` など）を使うと `hook.<event>.enabled` のような既存キーと曖昧になり、git が fatal error を出す。名前はイベント名と重ならないものにする。

### 2. 各プラットフォームで git 2.54 以降を用意する

| プラットフォーム | 入手方法 | dotfiles 側の変更 |
| --- | --- | --- |
| macOS | Homebrew | `run_once_before_10-install-packages.sh.tmpl` の `brew install` へ `git` を追加し、`dot_zprofile.tmpl` で PATH を調整する |
| Linux | `ppa:git-core/ppa` | `run_once_before_10-install-packages.sh.tmpl` の apt ブロックへ PPA 追加を挿入する |
| Windows | Git for Windows | 変更なし。既定のインストーラが要件を満たすバージョンを配る |

macOS では、`brew install git` だけでは要件を満たさない。`/etc/zprofile` の `path_helper` が login shell の PATH を再構築し、`/etc/paths` に載るシステムディレクトリを先頭へ、それ以外を末尾へ移す。`~/.zshenv` 経由で `~/.profile` が先頭に置いたディレクトリも、login zsh ではここで `/usr/bin` より後ろへ回る。`~/.profile` は多重読み込みガードにより再実行されないため、並びは `~/.zprofile` で戻す。

戻す対象は `/opt/homebrew/opt/git/bin` に限る。このディレクトリは git 関連の実行ファイルだけを持つため、影響が git に閉じる。`~/.local/bin` や mise の shims をまとめて `/usr/bin` より前へ出すと、システムツール全般を shadow して影響範囲が読めなくなる。

Linux で PPA を追加できない環境では、ディストリビューション標準の git のまま処理を続ける。設定ベースフックは無効になるが、`init.templateDir` による保護は残る。

### 3. `init.templateDir` は撤去せず、二重実行を hook 側で抑止する

`init.templateDir` と `~/.config/git/templates/hooks/pre-commit` は ADR-018 のまま残す。git 2.54 より前のバージョンでは、これが唯一の配布経路であり続ける。

両方が有効な環境では、設定ベースフックが先に、`$GIT_DIR/hooks` の hook が後に実行される。同じ staged tree を二度走査しても結果は変わらないが、テンプレート側の hook が自身の実行を抑止する。

```sh
if git hook list pre-commit --show-scope 2>/dev/null \
  | awk -F'\t' '$NF == "dotfiles-gitleaks" && $0 !~ /\tdisabled\t/ { found = 1 }
                END { exit !found }'; then
  exit 0
fi
```

この判定が安全である理由は二つある。第一に、git は hook を実行する前に自身の `GIT_EXEC_PATH` を PATH の先頭へ置くため、hook の中で解決される `git` は hook を起動した git と同一である。`hook list` を知らない git は標準出力へ何も書かないので、判定は成立しない。第二に、設定ベースフックは fail-closed であり、git が実行できなければ commit を中断する。一覧に現れることは、走査が済んでいることを意味する。

どちらの条件も満たされない場合、判定は成立せずテンプレート側の走査が実行される。したがって失敗の向きは「二度走る」であって「一度も走らない」ではない。

### 4. 保護が効いていない状態を apply のたびに報告する

`run_after_40-check-git-hooks.sh.tmpl`（Windows は `.ps1.tmpl`）を追加する。このスクリプトは `chezmoi apply` のたびに実行され、設定ベースフックが有効かを確認する。有効でなければ、保護される範囲と git の更新手順を標準エラーへ出力する。apply は失敗させない。

判定には git のバージョン番号ではなく `git hook list` の出力を使う。バージョンが条件を満たしていても設定が届いていなければ保護は効かないため、両方をまとめて確認できる。

`init.templateDir` を撤去しない以上、この報告が無くても保護が完全に消えるわけではない。それでも報告する理由は、ADR-018 で失われたのが保護そのものではなく、失われたことに気づく手段だったからである。

### リポジトリ単位の無効化

```sh
git config --local hook.dotfiles-gitleaks.enabled false
```

これは設定ベースフックだけを無効にする。同じリポジトリが `init.templateDir` 由来の hook を持つ場合、そちらは実行され続ける。両方を止めるには hook ファイルも削除する。

## Consequences

- 設定ベースフックは `.git/hooks` を参照しないため、`lefthook install` が `.git/hooks/pre-commit` を置き換えても gitleaks は実行され続ける。lefthook 自身の job も従来どおり実行される。
- 既存リポジトリにも適用される。backfill を実行していないリポジトリでも gitleaks が走る。
- 保護の有無は、実行された git バイナリのバージョンで決まる。PATH の解決が経路ごとに異なる環境では、保護される経路とされない経路が混在し得る。macOS の login shell については `~/.zprofile` で対処したが、Finder から起動した GUI アプリのように shell の設定を読まない経路は対象外である。
- `$GIT_DIR/hooks` の hook は git が実行可能性を確認して欠落時は無視するのに対し、設定ベースフックには存在確認がない。`~/.local/bin/gitleaks-pre-commit` が読めなければ commit が拒否される。`chezmoi apply` が中断した場合などにこの状態が起こり得る。秘密情報の走査が無言で消えるよりも、commit が止まって原因が表示される方を選ぶ。
- 走査スクリプトは設定ベースフック用とテンプレート用の二つに分かれる。探索ロジックを変更するときは両方を更新する。共有すると、片方を撤去する際にもう片方が壊れる結合が生まれるため、重複を選んだ。
- `--no-verify` で回避できる点は `init.templateDir` 方式と変わらない。誤って秘密情報を commit する事故を早期に止めることが目的であり、意図的な持ち出しを防ぐ境界は GitHub 側の secret scanning と push protection が担う。

## 検証記録

macOS 実機（Homebrew git）と Linux コンテナで確認した。使用した git のバージョンは macOS が 2.55.0、Linux が `ppa:git-core/ppa` の 2.54.0、比較対象の Apple Git が 2.50.1 である。

| 確認項目 | 結果 |
| --- | --- |
| 要件 1: `.git/hooks` に hook を持たないリポジトリで秘密鍵の commit を拒否する | 拒否した（`leaks found: 1`、exit 1、commit 数 0） |
| 要件 2: lefthook 生成の hook で上書きした状態で秘密鍵の commit を拒否する | 拒否した。lefthook 側の hook も実行された |
| 設定ベースフック有効時の走査回数 | 1 回 |
| リポジトリ単位で無効化した場合の走査回数 | 1 回（テンプレート由来の hook が実行される） |
| Apple Git 2.50.1 での走査回数 | 1 回。`[hook]` セクションによるエラーは出ない |
| gitleaks が PATH にも mise shims にも無い場合 | 警告のみで commit は成功する（fail-open） |
| hook の中で解決される `git` | hook を起動した git と同一のバイナリ |
| login zsh での `git` の解決先 | `/opt/homebrew/opt/git/bin/git`。PATH に重複は無い |
| `chezmoi apply` 時の報告 | 設定ベースフックが有効なら無出力、無効なら警告を出力する |

判定方法について確認した事項を記す。`git hook list` は該当する hook が無い場合に exit 1 を返し、サブコマンド自体を知らない git は exit 129 を返す。終了コードだけでは両者と「対応しているが未設定」を区別できないため、判定には標準出力の内容を使う。`--show-scope` を付けない場合、スコープと `disabled` の表示は出ない。

## 引き継ぐ検証

Windows と WSL では未検証である。Windows と WSL は `~` の指す先も chezmoi の状態も別なので、**それぞれで branch を pull して `chezmoi apply` を実行する**。片方だけでは他方へ反映されない。

### 検証用の秘密情報

`ssh-keygen` は使わない。PowerShell 5.1 は空文字列の引数を外部コマンドへ渡す際の挙動が一定でなく、`-N ''` が意図どおり渡らないことがある。実鍵を作らずに済む点でも次の方が扱いやすい。gitleaks は鍵の中身ではなく PEM のヘッダ形式で検出するため、合成したブロックでブロックされることを macOS で確認済みである。

```powershell
@'
-----BEGIN OPENSSH PRIVATE KEY-----
NOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEY
-----END OPENSSH PRIVATE KEY-----
'@ | Set-Content -Path fake_key -NoNewline
```

改行コードと末尾改行の有無は検出に影響しない（CRLF かつ末尾改行なしでも検出することを macOS で確認済み）。

本文を短くしてはならない。gitleaks の private-key ルールは本文の長さも見ており、33 文字では検出しなかった（macOS で実測）。上記の 55 文字は検出を確認した値である。

### apply が途中で止まった場合

設定ベースフックは fail-closed である。`~/.gitconfig` が配られた後、`~/.local/bin/gitleaks-pre-commit` が配られる前に `chezmoi apply` が中断すると、**その機械のすべての commit が拒否される**。復旧は次の 1 コマンドで済む。

```powershell
chezmoi apply ~/.local/bin/gitleaks-pre-commit
```

### Windows（Git for Windows）

1. `git --version` が 2.54 以降であること。満たさない場合は `winget upgrade --id Git.Git` で更新し、新しいシェルで再確認する。dotfiles 側に Windows 用の git 導入処理は無いため、この更新は手動になる。
2. `chezmoi apply` が `run_after_40-check-git-hooks.ps1` の警告を出さないこと。このスクリプトは PowerShell の実行環境が無い機械で書いたため、構文が通ることの確認も兼ねる。git を更新する前に一度 apply すれば、警告を出す経路の表示も確認できる。
3. `git hook list pre-commit --show-scope` が `dotfiles-gitleaks` を含む行を返すこと。
4. 要件 1（作成時期を問わず走る）。`init.templateDir` 由来の hook を持たない状態を作って確認する。`git init` しただけでは hook が入るため、明示的に削除する。

   ```powershell
   mkdir $env:TEMP\gl1; cd $env:TEMP\gl1
   git init
   git config commit.gpgsign false   # 署名の失敗を gitleaks の結果と取り違えないため
   Remove-Item (Join-Path (git rev-parse --git-path hooks) 'pre-commit') -ErrorAction SilentlyContinue
   # 上記の fake_key を作成
   git add fake_key
   git commit -m t
   ```

   期待する結果は、出力に `leaks found: 1` が現れ、`git rev-list --count HEAD` が commit を数えないことである。

5. 要件 2（lefthook と併用できる）。lefthook を使うリポジトリで `lefthook install` を実行した後、同じ commit がブロックされ、かつ lefthook 自身の job も実行されること。
6. 走査が 1 回だけであること。`init.templateDir` 由来の hook を持つリポジトリ（手順 4 の削除をしない状態）で commit し、出力に含まれる gitleaks の要約行を数える。

   ```powershell
   mkdir $env:TEMP\gl2; cd $env:TEMP\gl2
   git init
   git config commit.gpgsign false
   'ok' | Set-Content -Path f; git add f
   (git commit -m t 2>&1 | Select-String 'no leaks found').Count   # 期待値: 1
   ```

7. `command` に書いた `sh ~/.local/bin/gitleaks-pre-commit` の解決先。手順 4 が成功すれば `sh` と `~` の解決は両方とも成立している。失敗した場合に切り分けるため、`sh` が Git for Windows のものか（WSL の bash ではないか）、`~` が Windows のユーザプロファイルを指すかを個別に確認する。

### WSL

WSL 側の git はディストリビューションの apt から入る。`appendWindowsPath` を無効にしているため、WSL から Windows 側の実行ファイルを PATH 経由で呼べない。WSL 側は Linux ネイティブの git と gitleaks で完結させる。

1. WSL 内でこの branch を pull し、`chezmoi apply` を実行する。Windows 側の apply は WSL の `~` に反映されない。
2. `git --version` が 2.54 以降であること。`run_once_before_10-install-packages.sh` は内容を変更したため、`chezmoi apply` で再実行され `ppa:git-core/ppa` が追加される。PPA を追加できない環境では警告を出して処理を続けるので、その場合は git がディストリビューション版のままになる。
3. `~/.gitconfig` に `[hook "dotfiles-gitleaks"]` が届いていること。
4. 上記 Windows の手順 4、5、6 を、次のように読み替えて WSL 側で実行する。

   ```sh
   mkdir -p /tmp/gl1 && cd /tmp/gl1 && git init
   git config commit.gpgsign false
   rm -f "$(git rev-parse --git-path hooks)/pre-commit"     # 手順 4 のみ
   printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\n%s\n-----END OPENSSH PRIVATE KEY-----\n' \
     'NOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEY' > fake_key
   git add fake_key && git commit -m t
   ```

   走査回数は `git commit -m t 2>&1 | grep -c 'no leaks found'` で数える。

### 未検証のまま残る範囲

- Finder から起動した GUI アプリのように、shell の設定を読まない経路で解決される git のバージョン。
- Dev Container と Codespaces のベースイメージが配る git。現時点では 2.54 に満たない。ベースイメージが更新されるか、`run_once_before_10-install-packages.sh.tmpl` の PPA 追加が効くかで決まる。

## 関連

- ADR-018: `init.templateDir` による配布。本 ADR はこれを置き換えず、git 2.54 より前の環境での配布経路として残す。
