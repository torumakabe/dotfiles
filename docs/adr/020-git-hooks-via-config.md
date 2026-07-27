# ADR-020: gitleaks の pre-commit は Git の設定ベースフックで配る

## Status

Proposed

macOS、Linux コンテナ、Windows、WSL で検証した。結果は「検証記録」に記す。Dev Container と Codespaces は未検証であり、残る検証項目は「引き継ぐ検証」に記す。

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
- `$GIT_DIR/hooks` の hook は git が実行可能性を確認して欠落時は無視するのに対し、設定ベースフックには存在確認がない。`~/.local/bin/gitleaks-pre-commit` が読めなければ commit が拒否される。`chezmoi apply` が中断した場合などにこの状態が起こり得る。秘密情報の走査が無言で消えるよりも、commit が止まって原因が表示される方を選ぶ。この状態からの復旧は `chezmoi apply ~/.local/bin/gitleaks-pre-commit` で済む。
- 走査スクリプトは設定ベースフック用とテンプレート用の二つに分かれる。探索ロジックを変更するときは両方を更新する。共有すると、片方を撤去する際にもう片方が壊れる結合が生まれるため、重複を選んだ。
- `--no-verify` で回避できる点は `init.templateDir` 方式と変わらない。誤って秘密情報を commit する事故を早期に止めることが目的であり、意図的な持ち出しを防ぐ境界は GitHub 側の secret scanning と push protection が担う。

## 検証記録

macOS 実機、Linux コンテナ、Windows 実機、WSL (Ubuntu 22.04) で確認した。使用した git は、macOS が Homebrew の 2.55.0、Linux コンテナが `ppa:git-core/ppa` の 2.54.0、Windows が Git for Windows 2.55.0、WSL が同じ PPA の 2.54.0 である。WSL の git は apply 前が 2.34.1 であり、`run_once_before_10-install-packages.sh` の PPA 追加によって 2.54.0 へ更新された。

commit を拒否したことの判定には、出力に `leaks found: 1` が現れること、git の終了コードが 1 であること、commit が作られないことの三つを使った。

| 確認項目 | macOS / Linux | Windows | WSL |
| --- | --- | --- | --- |
| 要件 1: `.git/hooks` に hook を持たないリポジトリで秘密鍵の commit を拒否する | 拒否した | 拒否した | 拒否した |
| 要件 2: lefthook 生成の hook で上書きした状態で秘密鍵の commit を拒否する | 拒否した | 拒否した | 拒否した |
| 要件 2: 同じ状態で lefthook 自身の job も実行される | 実行した | 実行した | 実行した |
| 設定ベースフック有効時の走査回数 | 1 回 | 1 回 | 1 回 |
| リポジトリ単位で無効化した場合の走査回数 | 1 回 | 1 回 | 1 回 |
| hook の中で解決される `git` が hook を起動した git と同一である | 同一 | 同一 | 同一 |
| `chezmoi apply` 時の報告が、有効なら無出力、無効なら警告になる | 一致した | 一致した | 一致した |

プラットフォームごとに個別に確認した事項を記す。

- macOS: Apple Git 2.50.1 でも走査回数は 1 回であり、`[hook]` セクションによるエラーは出ない。login zsh での `git` は `/opt/homebrew/opt/git/bin/git` に解決され、PATH に重複は無い。
- macOS と Linux コンテナ: gitleaks が PATH にも mise shims にも無い場合、警告のみで commit は成功する (fail-open)。
- Windows: hook の中で `sh` は `/usr/bin/sh` に解決される。これは Git for Windows が同梱する MSYS の sh であり、WSL の bash ではない。`command` に書いた `~` は Windows のユーザプロファイルを指す。
- WSL: hook の中で `sh` は `/usr/bin/sh`、`git` は `/usr/lib/git-core/git` に解決される。`appendWindowsPath` を無効にしているため、Windows 側の実行ファイルは経路に入らない。

判定方法について確認した事項を記す。`git hook list` は該当する hook が無い場合に exit 1 を返し、サブコマンド自体を知らない git は exit 129 を返す。終了コードだけでは両者と「対応しているが未設定」を区別できないため、判定には標準出力の内容を使う。`--show-scope` を付けない場合、スコープと `disabled` の表示は出ない。

`run_after_40-check-git-hooks` の警告経路は、`GIT_CONFIG_GLOBAL` を空のファイルへ向けて設定ベースフックが見えない状態を作り、Windows と WSL の双方で確認した。どちらも警告を出したうえで終了コード 0 を返し、apply を失敗させない。Windows 版は powershell.exe 5.1 で実行し、構文が通ることもあわせて確認した。

## 引き継ぐ検証

Dev Container と Codespaces では未検証である。ベースイメージが配る git は現時点で 2.54 に満たないため、設定ベースフックが有効になるかは `run_once_before_10-install-packages.sh.tmpl` の PPA 追加が効くかで決まる。コンテナを作成して `chezmoi apply` を実行したうえで、次を確認する。

1. `git --version` が 2.54 以降であること。満たさない場合は PPA の追加が失敗した理由を確認する。ベースイメージの sudo の扱い、apt のプロキシ設定、`software-properties-common` の有無が候補になる。
2. `git hook list pre-commit --show-scope` が `dotfiles-gitleaks` を含む行を返すこと。
3. 要件 1（作成時期を問わず走る）。`init.templateDir` 由来の hook を持たない状態を作って確認する。

   ```sh
   mkdir -p /tmp/gl1 && cd /tmp/gl1 && git init
   git config commit.gpgsign false
   rm -f "$(git rev-parse --git-path hooks)/pre-commit"
   printf -- '-----BEGIN OPENSSH PRIVATE KEY-----\n%s\n-----END OPENSSH PRIVATE KEY-----\n' \
     'NOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEYNOTAREALKEY' > fake_key
   git add fake_key && git commit -m t
   ```

   期待する結果は、出力に `leaks found: 1` が現れ、`git rev-list --count HEAD` が commit を数えないことである。本文を短くしてはならない。gitleaks の private-key ルールは本文の長さも見ており、33 文字では検出しなかった（macOS で実測）。上記の 55 文字は検出を確認した値である。

4. 走査が 1 回だけであること。手順 3 の削除をしない状態で commit し、`git commit -m t 2>&1 | grep -c 'no leaks found'` が 1 を返すこと。
5. git が 2.54 に満たないまま終わった場合、`chezmoi apply` が `run_after_40-check-git-hooks.sh` の警告を出し、かつ apply 自体は成功すること。この経路では `init.templateDir` 由来の hook だけが保護を担う。

### apply が途中で止まった場合

設定ベースフックは fail-closed である。`~/.gitconfig` が配られた後、`~/.local/bin/gitleaks-pre-commit` が配られる前に `chezmoi apply` が中断すると、その環境のすべての commit が拒否される。復旧は次の 1 コマンドで済む。

```sh
chezmoi apply ~/.local/bin/gitleaks-pre-commit
```

### 検証の対象外

Finder から起動した GUI アプリのように、shell の設定を読まない経路で解決される git のバージョンは検証しない。設定ベースフックが有効かどうかは、その経路で実行された git のバージョンに依存する。

## 関連

- ADR-018: `init.templateDir` による配布。本 ADR はこれを置き換えず、git 2.54 より前の環境での配布経路として残す。
