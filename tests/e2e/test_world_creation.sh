#!/usr/bin/env bash
# ============================================================
# 世界创建四档位并发 E2E 测试
# 用法: bash tests/e2e/test_world_creation.sh
# ============================================================
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
TITLE="入间同学入魔了"
SCALES=(standard detailed deep all)

POLL_INTERVAL=10
CREATION_TIMEOUT=1800
GEN_TIMEOUT=600

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${CYAN}[$(date +%H:%M:%S)]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
fail() { echo -e "${RED}  ✗${NC} $*"; }

# JSON 解析工具（不依赖 jq）
pyjson() { python3 -c "import sys,json; d=json.load(sys.stdin); print(d$1)"; }
pyjson_raw() { python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d$1))"; }

# api_curl: curl 包装函数，去掉 -f 以保留 HTTP 错误响应体
# HTTP 状态码写入 $TMP_DIR/.api_curl_code（因为 $() 子 shell 中变量无法传回父 shell）
# body 输出到 stdout
api_curl() {
  local _tmp
  _tmp=$(curl -s -w "\n%{http_code}" "$@" 2>/dev/null) || true
  printf '%s' "${_tmp##*$'\n'}" > "$TMP_DIR/.api_curl_code"
  printf '%s' "${_tmp%$'\n'*}"
}
# 读取上次 api_curl 的 HTTP 状态码
_curl_code() { cat "$TMP_DIR/.api_curl_code" 2>/dev/null; }
# 判断上次 api_curl 调用是否返回 2xx
http_ok() { [[ "$(_curl_code)" =~ ^2[0-9][0-9]$ ]]; }

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# ── Step 1: 并发创建四个世界 ─────────────────────────────────
# 开源单人自托管版本无需登录，所有请求默认以固定管理员账号处理。
log "并发创建 4 个世界: ${SCALES[*]}"

for scale in "${SCALES[@]}"; do
  (
    RESP=$(curl -s -X POST "$API_URL/api/worlds" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$TITLE\",\"scale\":\"$scale\",\"fast_path\":true}" \
      -w "\n%{http_code}" 2>/dev/null) || RESP=$'{"error":"curl failed"}\n000'

    HTTP_CODE="${RESP##*$'\n'}"
    BODY="${RESP%$'\n'*}"

    if [[ "$HTTP_CODE" == "202" ]]; then
      echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['world_id'])" > "$TMP_DIR/$scale.id"
    else
      echo "$HTTP_CODE" > "$TMP_DIR/$scale.err_code"
      echo "$BODY" > "$TMP_DIR/$scale.err_body"
    fi
  ) &
done
wait

declare -A WORLD_IDS
CREATE_OK=()
for scale in "${SCALES[@]}"; do
  if [[ -f "$TMP_DIR/$scale.id" ]]; then
    WORLD_IDS[$scale]=$(cat "$TMP_DIR/$scale.id")
    CREATE_OK+=("$scale")
    ok "$scale → ${WORLD_IDS[$scale]}"
  else
    CODE=$(cat "$TMP_DIR/$scale.err_code" 2>/dev/null || echo "?")
    BODY=$(cat "$TMP_DIR/$scale.err_body" 2>/dev/null || echo "")
    fail "$scale → HTTP $CODE"
    [[ -n "$BODY" ]] && echo "      $BODY" | head -2
  fi
done

[[ ${#CREATE_OK[@]} -eq 0 ]] && { fail "全部创建失败"; exit 1; }

# ── Step 2: 并发轮询 creation-status ─────────────────────────
log "轮询世界内容创建状态..."

declare -A CREATION_DONE
declare -A CREATION_READY
for scale in "${CREATE_OK[@]}"; do CREATION_DONE[$scale]=false; CREATION_READY[$scale]=false; done

ELAPSED=0
while [[ $ELAPSED -lt $CREATION_TIMEOUT ]]; do
  ALL_DONE=true
  for scale in "${CREATE_OK[@]}"; do
    [[ "${CREATION_DONE[$scale]}" == "true" ]] && continue

    RESP=$(api_curl "$API_URL/api/worlds/${WORLD_IDS[$scale]}/creation-status")
    if ! http_ok; then
      log "  $scale → creation-status HTTP $(_curl_code)"
      ALL_DONE=false
      continue
    fi
    STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || { ALL_DONE=false; continue; }

    case "$STATUS" in
      ready|active) ok "$scale → 内容就绪"; CREATION_DONE[$scale]=true; CREATION_READY[$scale]=true ;;
      failed)       fail "$scale → 内容创建失败"; CREATION_DONE[$scale]=true ;;
      creating)     ALL_DONE=false ;;
      *)            log "  $scale → 未知状态: '$STATUS'"; ALL_DONE=false ;;
    esac
  done
  [[ "$ALL_DONE" == "true" ]] && break
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
  if (( ELAPSED % 60 == 0 )); then log "  等待中... (${ELAPSED}s)"; fi
done

# 超时后检查未完成的档位
for scale in "${CREATE_OK[@]}"; do
  [[ "${CREATION_DONE[$scale]}" == "true" ]] || fail "$scale → 内容创建轮询超时 (${CREATION_TIMEOUT}s)"
done

# 只有 creation-status 就绪（ready/active）的档位才进入角色生成轮询
READY_SCALES=()
for scale in "${CREATE_OK[@]}"; do
  [[ "${CREATION_READY[$scale]}" == "true" ]] && READY_SCALES+=("$scale")
done

if [[ ${#READY_SCALES[@]} -eq 0 ]]; then
  fail "所有档位内容创建超时或失败，跳过角色生成轮询"
fi

# ── Step 3: 并发轮询角色生成 ─────────────────────────────────
log "轮询角色生成状态..."

declare -A GEN_DONE
for scale in "${READY_SCALES[@]}"; do GEN_DONE[$scale]=false; done

ELAPSED=0
while [[ $ELAPSED -lt $GEN_TIMEOUT ]]; do
  ALL_DONE=true
  for scale in "${READY_SCALES[@]}"; do
    [[ "${GEN_DONE[$scale]}" == "true" ]] && continue

    RESP=$(api_curl "$API_URL/api/worlds/${WORLD_IDS[$scale]}/generate-characters/status")
    if ! http_ok; then
      log "  $scale → generate-characters/status HTTP $(_curl_code)"
      ALL_DONE=false
      continue
    fi
    STATUS=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || { ALL_DONE=false; continue; }

    case "$STATUS" in
      completed)       ok "$scale → 角色生成完成"; GEN_DONE[$scale]=true ;;
      failed)          fail "$scale → 角色生成失败"; GEN_DONE[$scale]=true ;;
      generating|idle) ALL_DONE=false ;;
      *)               log "  $scale → 未知状态: '$STATUS'"; ALL_DONE=false ;;
    esac
  done
  [[ "$ALL_DONE" == "true" ]] && break
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

# 超时后检查未完成的档位
for scale in "${READY_SCALES[@]}"; do
  [[ "${GEN_DONE[$scale]}" == "true" ]] || fail "$scale → 角色生成轮询超时 (${GEN_TIMEOUT}s)"
done

# ── Step 4: 验证并汇报 ──────────────────────────────────────
log "验证结果..."

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║                      测试结果汇报                           ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║  档位       状态      元素      角色      关系             ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"

TOTAL_PASS=0
TOTAL_FAIL=0

for scale in "${SCALES[@]}"; do
  if [[ -z "${WORLD_IDS[$scale]:-}" ]]; then
    printf "║  %-10s  ${RED}%-8s${NC}  %-8s  %-8s  %-8s  ║\n" "$scale" "创建失败" "-" "-" "-"
    TOTAL_FAIL=$((TOTAL_FAIL+1))
    continue
  fi

  WID="${WORLD_IDS[$scale]}"

  WORLD=$(api_curl "$API_URL/api/worlds/$WID")
  if ! http_ok; then
    printf "║  %-10s  ${RED}%-8s${NC}  %-8s  %-8s  %-8s  ║\n" "$scale" "HTTP$(_curl_code)" "-" "-" "-"
    TOTAL_FAIL=$((TOTAL_FAIL+1))
    continue
  fi

  ELEM_COUNT=$(echo "$WORLD" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('elements',[])))" 2>/dev/null || echo 0)

  CHAR_RESP=$(api_curl "$API_URL/api/worlds/$WID/characters")
  if http_ok; then
    CHAR_COUNT=$(echo "$CHAR_RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
  else
    CHAR_COUNT="HTTP$(_curl_code)"
  fi

  REL_RESP=$(api_curl "$API_URL/api/worlds/$WID/relations")
  if http_ok; then
    REL_COUNT=$(echo "$REL_RESP" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
  else
    REL_COUNT="HTTP$(_curl_code)"
  fi

  if [[ "$ELEM_COUNT" =~ ^[0-9]+$ && "$CHAR_COUNT" =~ ^[0-9]+$ && $ELEM_COUNT -gt 0 && $CHAR_COUNT -gt 0 ]]; then
    printf "║  %-10s  ${GREEN}%-8s${NC}  %-8s  %-8s  %-8s  ║\n" "$scale" "成功" "$ELEM_COUNT" "$CHAR_COUNT" "$REL_COUNT"
    TOTAL_PASS=$((TOTAL_PASS+1))
  else
    printf "║  %-10s  ${RED}%-8s${NC}  %-8s  %-8s  %-8s  ║\n" "$scale" "失败" "$ELEM_COUNT" "$CHAR_COUNT" "$REL_COUNT"
    TOTAL_FAIL=$((TOTAL_FAIL+1))
  fi
done

echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  通过: ${GREEN}${TOTAL_PASS}${NC}  失败: ${RED}${TOTAL_FAIL}${NC}"
echo ""

# ── Step 5: 清理 ─────────────────────────────────────────────
log "清理测试数据..."
DELETE_OK=0
DELETE_FAIL=0
for scale in "${CREATE_OK[@]}"; do
  WID="${WORLD_IDS[$scale]}"
  DELETED=false
  for attempt in 1 2 3; do
    RESP=$(api_curl -X DELETE "$API_URL/api/worlds/$WID")
    if [[ "$(_curl_code)" == "204" || "$(_curl_code)" == "200" ]]; then
      ok "已删除 $scale (HTTP $(_curl_code))"
      DELETED=true
      break
    fi
    # 404 = 已经不存在，视为成功
    if [[ "$(_curl_code)" == "404" ]]; then
      ok "已删除 $scale (404，世界已不存在)"
      DELETED=true
      break
    fi
    if [[ $attempt -lt 3 ]]; then
      log "  删除 $scale 第 $attempt 次失败 (HTTP $(_curl_code))，重试..."
      sleep 2
    fi
  done
  if [[ "$DELETED" != "true" ]]; then
    fail "删除失败 $scale → HTTP $(_curl_code) body=${RESP:0:200}"
    DELETE_FAIL=$((DELETE_FAIL+1))
  else
    DELETE_OK=$((DELETE_OK+1))
  fi
done
log "清理完成: 成功=$DELETE_OK 失败=$DELETE_FAIL"

echo ""
[[ $TOTAL_FAIL -eq 0 ]] && echo -e "${GREEN}${BOLD}全部通过!${NC}" || echo -e "${RED}${BOLD}${TOTAL_FAIL} 个档位失败${NC}"
exit $TOTAL_FAIL
