#!/usr/bin/env bash
# 唯一的部署入口：从 GitHub main 拉取指定提交，新 release 目录 + 重建镜像。
#
#   sudo bash deploy.sh              # 部署当前 main
#   sudo bash deploy.sh <sha>        # 部署指定提交
#   sudo bash deploy.sh --rollback <短sha>   # 回滚到某个已部署过的 release
#
# 设计约束：
#  - 永远新建 releases/<sha> 目录，绝不就地更新旧目录（旧目录可能是别的分支）
#  - 部署前给当前镜像打 <旧sha> 标签，回滚只需重新指向这个标签
#  - 只切换 web/worker/beat，不动 postgres/redis
#  - 失败时明确打印回滚命令，不留下半切换状态
set -euo pipefail

PROJECT="${PROJECT:-908c31a}"
REPO="${REPO:-Gelen5/universe-wechat-detection}"
RELEASES="${RELEASES:-/opt/universe-wechat-detection-releases}"
ENV_FILE="${ENV_FILE:-/etc/universe-wechat-detection.env}"
SERVICES=(web worker beat)
HEALTH_URL="http://127.0.0.1:8000/health/ready"

log()  { printf '\n== %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 root 运行：sudo bash $0"

# 全程留痕：部署失败时看 /var/log/universe-deploy.log 最后 50 行就够定位
LOG_FILE="${LOG_FILE:-/var/log/universe-deploy.log}"
exec > >(tee -a "$LOG_FILE") 2>&1
printf '\n===== %s | %s =====\n' "$(date '+%F %T')" "${*:-deploy main}"

remote_main() {
  local sha
  # 1) git 协议：快，但国内链路会间歇性超时
  sha=$(timeout 20 git ls-remote "https://github.com/${REPO}.git" refs/heads/main 2>/dev/null | cut -f1)
  if [ -n "$sha" ]; then printf '%s\n' "$sha"; return 0; fi
  # 2) REST API：实测这条一般 1 秒内返回
  sha=$(timeout 20 curl -fsS "https://api.github.com/repos/${REPO}/commits/main" 2>/dev/null \
        | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin)["sha"])
except Exception:
    pass' 2>/dev/null)
  if [ -n "$sha" ]; then printf '%s\n' "$sha"; return 0; fi
  # 3) 归档地址 302（有的网络只放行 codeload）
  timeout 25 curl -s -o /dev/null -w '%{redirect_url}' \
    "https://github.com/${REPO}/archive/refs/heads/main.zip" 2>/dev/null \
    | sed -n 's#.*/zip/\([0-9a-f]\{40\}\).*#\1#p'
}

wait_ready() {
  for _ in $(seq 1 45); do
    if curl -fsS -m 3 "$HEALTH_URL" >/dev/null 2>&1; then
      echo "ready: $(curl -fsS -m 3 "$HEALTH_URL")"
      return 0
    fi
    sleep 2
  done
  return 1
}

current_release_dir() {
  docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' \
    "${PROJECT}-web-1" 2>/dev/null || true
}

# ---------------------------------------------------------------- status
if [ "${1:-}" = "--status" ]; then
  echo "== 线上 release"
  current_release_dir
  echo "== 容器"
  docker ps --format '{{.Names}} | {{.Status}}' | grep "$PROJECT" || true
  echo "== 健康"
  curl -fsS -m 5 "$HEALTH_URL" || echo "health 不可用"
  echo
  echo "== 最近部署日志（$LOG_FILE）"
  tail -n 15 "$LOG_FILE" 2>/dev/null || echo "（还没有日志）"
  exit 0
fi

# ---------------------------------------------------------------- rollback
if [ "${1:-}" = "--rollback" ]; then
  TARGET="${2:-}"
  [ -n "$TARGET" ] || die "用法: $0 --rollback <短sha>"
  REL="$RELEASES/$TARGET"
  [ -f "$REL/docker-compose.yml" ] || die "没有找到 release: $REL"
  log "回滚到 $TARGET"
  for svc in "${SERVICES[@]}" migrate; do
    docker image inspect "${PROJECT}-${svc}:${TARGET}" >/dev/null 2>&1 \
      || die "缺少回滚镜像 ${PROJECT}-${svc}:${TARGET}（这个 release 部署时没有打标签）"
    docker tag "${PROJECT}-${svc}:${TARGET}" "${PROJECT}-${svc}:latest"
  done
  docker rm -f "${PROJECT}-migrate-1" >/dev/null 2>&1 || true
  ( cd "$REL" && docker compose -p "$PROJECT" --env-file "$ENV_FILE" up -d --no-build --no-deps "${SERVICES[@]}" )
  wait_ready || die "回滚后服务未就绪，查看 docker logs ${PROJECT}-web-1"
  log "已回滚到 $TARGET"
  exit 0
fi

# ---------------------------------------------------------------- resolve
# 同一时间只允许一个部署：多个 agent 并发时构建和容器切换会互相踩
exec 9>/var/lock/universe-deploy.lock
flock -n 9 || die "另一个部署正在进行（/var/lock/universe-deploy.lock）。等它结束再试，或先跑 deploy.sh --status"

SHA="${1:-}"
if [ -z "$SHA" ]; then
  SHA="$(remote_main)"
  [ -n "$SHA" ] || die "无法解析 main（服务器访问 GitHub 受限？可用 $0 <完整sha>）"
fi
[ "${#SHA}" -ge 7 ] || die "提交号太短: $SHA"
SHORT="${SHA:0:7}"
REL="$RELEASES/$SHORT"

MAIN_SHA="$(remote_main || true)"
log "目标提交 $SHORT（$SHA）"
if [ -n "$MAIN_SHA" ] && [ "$MAIN_SHA" != "$SHA" ]; then
  warn "$SHORT 不是当前 main（main=${MAIN_SHA:0:7}），将按你指定的提交部署"
fi

# 预检：这台机器只有 1.6G 内存，构建期最容易被打爆
MEM_AVAIL=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
DISK_AVAIL=$(df -Pk / 2>/dev/null | awk 'NR==2 {print int($4/1024)}')
[ "${MEM_AVAIL:-0}" -lt 350 ] && warn "可用内存仅 ${MEM_AVAIL}MB，构建可能被 OOM 杀掉（可先 docker builder prune）"
[ "${DISK_AVAIL:-0}" -lt 3000 ] && warn "根分区剩余 ${DISK_AVAIL}MB，可能不够构建"

PREV_DIR="$(current_release_dir)"
PREV_SHORT="$(basename "${PREV_DIR:-}" 2>/dev/null || true)"
[ -n "$PREV_SHORT" ] && log "当前线上: $PREV_SHORT"

# ---------------------------------------------------------------- fetch
if [ -f "$REL/docker-compose.yml" ]; then
  log "复用已存在的 release 目录 $REL"
else
  log "下载 $SHORT 源码"
  TMP="$(mktemp -d)"
  trap 'if [ -n "${TMP:-}" ]; then rm -rf "$TMP"; fi' EXIT
  ok=0
  for attempt in 1 2 3; do
    if curl -fsSL --retry 2 --retry-delay 3 --connect-timeout 20 --max-time 300 \
        -o "$TMP/src.zip" "https://codeload.github.com/${REPO}/zip/${SHA}"; then ok=1; break; fi
    warn "第 ${attempt} 次下载失败，重试…"
    sleep $((attempt * 3))
  done
  [ "$ok" = 1 ] || die "下载失败（已重试 3 次）：https://codeload.github.com/${REPO}/zip/${SHA}"
  SRC="$(python3 - "$TMP/src.zip" "$TMP/unpack" <<'PY'
import pathlib, sys, zipfile
zip_path, dest = sys.argv[1], sys.argv[2]
pathlib.Path(dest).mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(zip_path) as zf:
    zf.extractall(dest)
roots = [p for p in pathlib.Path(dest).iterdir() if p.is_dir()]
if len(roots) != 1:
    raise SystemExit(f"unexpected archive layout: {roots}")
print(roots[0])
PY
)"
  [ -d "$SRC" ] || die "解包失败"
  rm -rf "$REL"
  mv "$SRC" "$REL"
  chown -R root:root "$REL"
fi
[ -L "$REL/.env" ] || ln -s "$ENV_FILE" "$REL/.env"
[ -f "$REL/docker-compose.yml" ] || die "$REL 缺少 docker-compose.yml"
[ -f "$REL/server/main.py" ] || die "$REL 缺少 server/main.py"

# ---------------------------------------------------------------- images
if [ -n "$PREV_SHORT" ] && [ "$PREV_SHORT" != "$SHORT" ]; then
  log "为回滚保留当前镜像（标签 $PREV_SHORT）"
  for svc in "${SERVICES[@]}" migrate; do
    docker tag "${PROJECT}-${svc}:latest" "${PROJECT}-${svc}:${PREV_SHORT}" 2>/dev/null || true
  done
fi

log "构建镜像（约 3 分钟）"
( cd "$REL" && docker compose -p "$PROJECT" --env-file "$ENV_FILE" build "${SERVICES[@]}" migrate )

# ---------------------------------------------------------------- switch
log "切换服务"
# 一次性 migrate 容器可能残留，名字冲突会让 up 直接失败；web 的 depends_on 已经不再需要它
docker rm -f "${PROJECT}-migrate-1" >/dev/null 2>&1 || true
( cd "$REL" && docker compose -p "$PROJECT" --env-file "$ENV_FILE" up -d --no-deps "${SERVICES[@]}" )

if ! wait_ready; then
  docker ps --format '{{.Names}} | {{.Status}}' | grep "$PROJECT" || true
  [ -n "$PREV_SHORT" ] && warn "回滚: sudo bash $0 --rollback $PREV_SHORT"
  die "服务未就绪；查看 docker logs ${PROJECT}-web-1"
fi

# ---------------------------------------------------------------- verify
log "验收"
check() { docker exec "${PROJECT}-web-1" sh -c "$1" >/dev/null 2>&1 && echo "  ok   $2" || echo "  MISS $2"; }
check 'test -f server/agent/intent.py' '阶段路由（intent）'
check 'grep -q topic_queries server/workbench_research.py' '真搜索（多查询+抓正文）'
check 'grep -q chat-steps static/conversation-workbench.js' '进度卡'
check 'grep -q bookshelf server/main.py' 'AI 书架'
echo "  版本 $(docker exec ${PROJECT}-web-1 grep -o 'conversation-workbench.js?v=[0-9a-z-]*' static/index.html | head -1)"
curl -fsS -m 5 -o /dev/null -w "  /health/ready -> %{http_code}\n" "$HEALTH_URL" || true
curl -fsS -m 8 -o /dev/null -w "  /bookshelf    -> %{http_code}\n" http://127.0.0.1:8000/bookshelf || true
docker ps --format '{{.Names}} | {{.Status}}' | grep "$PROJECT" || true

log "完成"
echo "  线上: $SHORT  ($REL)"
[ -n "$PREV_SHORT" ] && [ "$PREV_SHORT" != "$SHORT" ] && echo "  回滚: sudo bash $0 --rollback $PREV_SHORT"
