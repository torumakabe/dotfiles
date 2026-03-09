#!/bin/bash
set -euo pipefail

# fail-open 緩和: 異常時にデフォルト deny を出力し、exit 0 で正常終了させる
# （exit 0 がないと set -e により非ゼロ終了し、Hooks の fail-open で deny が無視される）
# ⚠️ jq がインストールされていない環境ではスクリプト全体が失敗し、trap ERR で deny が返る。
# これ自体は fail-safe だが、jq 依存を認識し、実行環境に jq を事前インストールすること。
trap 'echo "{\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Hook script error - fail-safe deny\"}"; 
exit 0' ERR

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.toolName // empty')
TOOL_ARGS_RAW=$(echo "$INPUT" | jq -r '.toolArgs // empty')

# toolArgs は JSON 文字列の場合があるため再パース
if echo "$TOOL_ARGS_RAW" | jq -e 'type == "string"' > /dev/null 2>&1; then
  TOOL_ARGS=$(echo "$TOOL_ARGS_RAW" | jq -r '.' | jq '.')
else
  TOOL_ARGS="$TOOL_ARGS_RAW"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOKS_DIR="$(dirname "$SCRIPT_DIR")"
BLOCKED_FILES="$HOOKS_DIR/blocked-files.txt"
ALLOWED_URLS="$HOOKS_DIR/allowed-urls.txt"

if [[ ! -f "$BLOCKED_FILES" ]]; then
  echo '{"permissionDecision":"deny","permissionDecisionReason":"blocked-files.txt not found - fail-safe deny"}'
  exit 0
fi

# --- ブロックファイルパターン検査 ---

# パス引数向け（厳密な部分文字列マッチ）
check_blocked_path() {
  local target="$1"
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    [[ "$pattern" =~ ^#.*$ || -z "$pattern" ]] && continue
    pattern=$(echo "$pattern" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [[ -z "$pattern" ]] && continue
    local short="${pattern##\*\*/}"
    short="${short##\*}"
    short="${short%%\*}"
    if [[ -n "$short" && "$target" == *"$short"* ]]; then
      echo "{\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Blocked pattern: $pattern\"}"
      exit 0
    fi
  done < "$BLOCKED_FILES"
}

# コマンド文字列向け（パス境界・シェルメタ文字を考慮した一致）
# パス区切り/空白/引用符/シェルメタ文字/代入演算子/文字列先頭を境界として
# パターンの出現を検査する。os.environ のようなコード内の部分一致による誤検知を防ぐ。
check_blocked_command() {
  local target="$1"
  while IFS= read -r pattern || [[ -n "$pattern" ]]; do
    [[ "$pattern" =~ ^#.*$ || -z "$pattern" ]] && continue
    pattern=$(echo "$pattern" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [[ -z "$pattern" ]] && continue
    local short="${pattern##\*\*/}"
    short="${short##\*}"
    short="${short%%\*}"
    local clean="${short//\*/}"
    clean="${clean//\?/}"
    if [[ -z "$clean" ]]; then continue; fi
    local escaped
    escaped=$(printf '%s' "$clean" | sed 's/[.[\^$*+?(){}|]/\\&/g')
    local sq="'"
    local boundary="(^|[\\\/[:space:]\"${sq};|&()\$\`=])"
    if [[ "$target" =~ ${boundary}${escaped} ]]; then
      echo "{\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"Blocked pattern: $pattern\"}"
      exit 0
    fi
  done < "$BLOCKED_FILES"
}

# ⚠️ check_blocked_path / check_blocked_command は以下の手法で迂回される可能性がある:
# - Base64 エンコード: bash -c "$(echo Y2F0IC5lbnY= | base64 -d)"
# - 変数間接参照: F=.val; cat $F（= 境界により代入時点で検知可能だが、cat $F は検知不可）
# - グロブ展開: cat .en*, cat ./.e?v
# - サブシェル/プロセス置換: $(cat file), `cat file`
# - シンボリックリンク: ln -s file link && cat link
# - パスエンコード: cat ./$'\x2e'file
#
# したがって、Hooks は「正直なエージェント」（プロンプトインジェクションが成功していない状態）に対する
# ガードレールとして機能するが、侵害されたエージェント（プロンプトインジェクション成功後）による
# 意図的な迂回には耐性がない。Hooks は多層防御の一層として位置づけ、サンドボックス環境や
# --deny-tool による補完を前提とした運用設計が必要である。


# --- ツール引数の抽出と検査 ---

# パス系プロパティ: 厳密検査
for prop in path file uri glob; do
  VAL=$(echo "$TOOL_ARGS" | jq -r ".$prop // empty" 2>/dev/null || true)
  if [[ -n "$VAL" ]]; then
    check_blocked_path "$VAL"
  fi
done

# コマンドプロパティ: 境界考慮検査
COMMAND=$(echo "$TOOL_ARGS" | jq -r '.command // empty' 2>/dev/null || true)
if [[ -n "$COMMAND" ]]; then
  check_blocked_command "$COMMAND"
fi

# --- URL 許可リスト検査 ---

check_url_allowed() {
  local url="$1"
  local url_host
  url_host=$(echo "$url" | sed -E 's|https?://([^/:]+).*|\1|')
  while IFS= read -r domain || [[ -n "$domain" ]]; do
    [[ "$domain" =~ ^#.*$ || -z "$domain" ]] && continue
    domain=$(echo "$domain" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [[ -z "$domain" ]] && continue
    if [[ "$url_host" == "$domain" || "$url_host" == *".$domain" ]]; then
      return 0
    fi
  done < "$ALLOWED_URLS"
  return 1
}

has_allowed_domains() {
  [[ -f "$ALLOWED_URLS" ]] || return 1
  grep -qvE '^\s*#|^\s*$' "$ALLOWED_URLS" 2>/dev/null
}

if has_allowed_domains; then
  if [[ -n "$COMMAND" ]]; then
    while IFS= read -r URL; do
      if ! check_url_allowed "$URL"; then
        echo "{\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"URL not in allowlist: $URL\"}"
        exit 0
      fi
    done < <(echo "$COMMAND" | grep -oE 'https?://[^ "]+' || true)
  fi

  if [[ "$TOOL_NAME" == "web_fetch" ]]; then
    URL=$(echo "$TOOL_ARGS" | jq -r '.url // empty' 2>/dev/null || true)
    if [[ -n "$URL" ]]; then
      if ! check_url_allowed "$URL"; then
        echo "{\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"URL not in allowlist: $URL\"}"
        exit 0
      fi
    fi
  fi
fi

# デフォルト: 通過
echo '{"permissionDecision":"allow"}'
exit 0