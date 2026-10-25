# 内置的去 AI 味 Skill（vendored）

`universe-delete-ai-skill` 是「去 AI 味」节点依赖的第二个外部 Skill。和公众号 Skill 一样
收进仓库，让仓库自包含、版本可查。

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/Gelen5/universe-delete-ai-skill |
| 固定提交 | `8c9fecf6cb40340ddbea69e75959b9c82b676d18` |
| 版本文件 | 上游没有 `VERSION`，以提交号为准 |
| 同步日期 | 2026-10-25 |
| 文件数 / 体积 | 78 个 / 约 0.41 MB |

## ⚠️ 必须保留 `THIRD_PARTY_NOTICES.md`

本 Skill 融合了第三方内容，`THIRD_PARTY_NOTICES.md` 是合规声明。
**同步、改造、精简目录时都不能删除它**，也不能删除它在 `references/` 里指向的来源文件。

## 平台用到哪些

`server/workbench.py` 的 `_review()` 与 `_anti_ai_audit()` 直接调用本目录的脚本：

| 文件 | 用途 |
|---|---|
| `scripts/check_ai_tone_signals.py` | AI 痕迹检测（子进程） |
| `scripts/check_natural_prose.py` | 自然语感 / 可读性检测（子进程） |
| `scripts/audit_revision.py` | 改稿前后信号对比 + 保护片段核对 |
| `references/empirical-minimal-edit-rules.md` | 复核提示词里的规则 |
| `references/chinese-content-signals.md` | 中文内容信号定义 |

这些是**硬依赖**：路径不存在会直接 `FileNotFoundError`，节点整步失败。

## 规则

1. **不要手改这里的文件**，一律通过
   `bash scripts/sync_vendored_skill.sh anti-ai [sha]` 同步。
2. 同步时排除 `.git`、`.venv`、`__pycache__`、`output`、`*.pyc`。
3. 不要在本仓库 CI 里跑 `tests/` 和 `eval/`；那是 Skill 自己的评测，依赖和失败原因与平台无关。

## 本地试用

```bash
printf '值得注意的是，在当今时代，这是非常重要的。\n' > /tmp/sample.txt
python vendor/skills/universe-delete-ai-skill/scripts/check_ai_tone_signals.py /tmp/sample.txt --mode standard
```
