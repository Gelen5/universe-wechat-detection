#!/usr/bin/env bash
# 把上游 Skill 的指定提交同步进 vendor/，并回写 VENDORED.md 的提交号。
#
#   bash scripts/sync_vendored_skill.sh wechat            # 公众号创作，跟上 main
#   bash scripts/sync_vendored_skill.sh wechat 0d4cd85a   # 公众号创作，锁定提交
#   bash scripts/sync_vendored_skill.sh anti-ai           # 去 AI 味，跟上 main
#   bash scripts/sync_vendored_skill.sh anti-ai 8c9fecf   # 去 AI 味，锁定提交
#
# 只同步源码：排除 .git / .venv / __pycache__ / output / *.pyc。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
}

SKILL="${1:-}"
TARGET="${2:-}"
case "$SKILL" in
  wechat)
    UPSTREAM="https://github.com/Gelen5/weChat-autoCreate.git"
    DEST="$ROOT/vendor/skills/weChat-autoCreate"
    LABEL="公众号创作 Skill"
    ;;
  anti-ai)
    UPSTREAM="https://github.com/Gelen5/universe-delete-ai-skill.git"
    DEST="$ROOT/vendor/skills/universe-delete-ai-skill"
    LABEL="去 AI 味 Skill"
    ;;
  *)
    usage
    ;;
esac

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
if [ -f "$DEST/VENDORED.md" ]; then
  cp "$DEST/VENDORED.md" "$WORK/VENDORED.md"
fi

echo "== 拉取 $LABEL"
echo "   $UPSTREAM"
git clone --quiet --filter=blob:none --no-checkout "$UPSTREAM" "$WORK/repo"
if [ -n "$TARGET" ]; then
  git -C "$WORK/repo" checkout --quiet "$TARGET"
else
  git -C "$WORK/repo" checkout --quiet origin/HEAD
fi
SHA="$(git -C "$WORK/repo" rev-parse HEAD)"
SHORT="$(git -C "$WORK/repo" rev-parse --short HEAD)"
if [ -f "$WORK/repo/VERSION" ]; then
  VERSION="$(tr -d '[:space:]' < "$WORK/repo/VERSION")"
else
  VERSION="n/a"
fi
echo "   提交 $SHORT   版本 $VERSION"

echo "== 同步到 ${DEST#$ROOT/}"
mkdir -p "$DEST"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' \
    --exclude 'output/' --exclude '*.pyc' \
    "$WORK/repo/" "$DEST/"
else
  find "$DEST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  ( cd "$WORK/repo" && tar -cf - \
      --exclude='./.git' --exclude='./.venv' --exclude='__pycache__' \
      --exclude='./output' --exclude='*.pyc' . ) | ( cd "$DEST" && tar -xf - )
fi

if [ ! -f "$DEST/VENDORED.md" ] && [ -f "$WORK/VENDORED.md" ]; then
  # VENDORED.md is repository-owned metadata and may not exist upstream.
  cp "$WORK/VENDORED.md" "$DEST/VENDORED.md"
fi

if [ "$SKILL" = wechat ]; then
  PATCH="$ROOT/vendor/skill-extensions/weChat-autoCreate/native-node-rules.patch"
  if [ -f "$PATCH" ]; then
    echo "== 应用仓库节点规则扩展"
    if git -C "$ROOT" apply --reverse --check "$PATCH" 2>/dev/null; then
      echo "   扩展已经存在"
    else
      # Fail visibly on upstream hook drift instead of silently losing node rules.
      git -C "$ROOT" apply --check "$PATCH"
      git -C "$ROOT" apply "$PATCH"
    fi
  fi
fi

if [ ! -f "$DEST/VENDORED.md" ]; then
  echo "   !! 缺少 VENDORED.md，跳过回写（请先补一份再同步）" >&2
  exit 0
fi

echo "== 回写 VENDORED.md"
python3 - "$DEST/VENDORED.md" "$SHA" "$VERSION" <<'PY'
import datetime
import io
import re
import sys

path, sha, version = sys.argv[1], sys.argv[2], sys.argv[3]
text = io.open(path, encoding="utf-8").read()
text = re.sub(r"\| 固定提交 \| `[0-9a-f]+` \|", f"| 固定提交 | `{sha}` |", text)
text = re.sub(r"\| 版本 \| [^|]+ \|", f"| 版本 | {version} |", text)
text = re.sub(r"\| 版本文件 \| [^|]+ \|",
              f"| 版本文件 | {'`VERSION` = ' + version if version != 'n/a' else '上游没有 `VERSION`，以提交号为准'} |",
              text)
text = re.sub(r"\| 同步日期 \| [^|]+ \|",
              f"| 同步日期 | {datetime.date.today().isoformat()} |", text)
io.open(path, "w", encoding="utf-8").write(text)
print("   已更新")
PY

echo "== 完成：$SHORT（$VERSION）"
echo "   记得提交：git add vendor/skills && git commit"
