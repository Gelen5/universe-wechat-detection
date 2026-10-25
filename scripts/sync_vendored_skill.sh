#!/usr/bin/env bash
# 把上游 weChat-autoCreate 的指定提交同步进 vendor/，并更新 VENDORED.md 的提交号。
#
#   bash scripts/sync_vendored_skill.sh              # 同步上游当前 main
#   bash scripts/sync_vendored_skill.sh 0d4cd85a...   # 同步指定提交
#
# 只同步源码：排除 .git / .venv / __pycache__ / output / *.pyc。
set -euo pipefail

UPSTREAM="${SKILL_UPSTREAM:-https://github.com/Gelen5/weChat-autoCreate.git}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/vendor/skills/weChat-autoCreate"

TARGET="${1:-}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== 拉取 $UPSTREAM"
git clone --quiet --filter=blob:none --no-checkout "$UPSTREAM" "$WORK/repo"
if [ -n "$TARGET" ]; then
  git -C "$WORK/repo" checkout --quiet "$TARGET"
else
  git -C "$WORK/repo" checkout --quiet origin/HEAD
fi
SHA="$(git -C "$WORK/repo" rev-parse HEAD)"
SHORT="$(git -C "$WORK/repo" rev-parse --short HEAD)"
VERSION="$(tr -d '[:space:]' < "$WORK/repo/VERSION" 2>/dev/null || echo unknown)"
echo "   提交 $SHORT   版本 $VERSION"

echo "== 同步到 vendor/skills/weChat-autoCreate"
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

echo "== 更新 VENDORED.md 的提交号"
python3 - "$DEST/VENDORED.md" "$SHA" "$VERSION" <<'PY'
import io, re, sys, datetime
path, sha, version = sys.argv[1], sys.argv[2], sys.argv[3]
text = io.open(path, encoding="utf-8").read()
text = re.sub(r"\| 固定提交 \| `[0-9a-f]+` \|", f"| 固定提交 | `{sha}` |", text)
text = re.sub(r"\| 版本 \| [^|]+ \|", f"| 版本 | {version} |", text)
text = re.sub(r"\| 同步日期 \| [^|]+ \|",
              f"| 同步日期 | {datetime.date.today().isoformat()} |", text)
io.open(path, "w", encoding="utf-8").write(text)
print("   VENDORED.md 已更新")
PY

echo "== 完成：$SHORT（$VERSION）"
echo "   记得提交：git add vendor/skills/weChat-autoCreate && git commit"
