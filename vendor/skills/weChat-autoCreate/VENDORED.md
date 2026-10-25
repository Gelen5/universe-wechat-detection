# 内置的公众号创作 Skill（vendored）

这里放的是 `weChat-autoCreate` 的源码副本，目的是让仓库自包含：本地能跑、部署可复现、
线上跑的版本可以从仓库里直接查。

| 项 | 值 |
|---|---|
| 上游仓库 | https://github.com/Gelen5/weChat-autoCreate |
| 固定提交 | `0d4cd85a51e8289944ad05c9dfb43125fe38dd2a` |
| 版本 | 2.1.0 |
| 同步日期 | 2026-10-25 |
| 许可证 | 见本目录 `LICENSE`（仓库自有，无第三方授权问题） |
| 文件数 / 体积 | 140 个 / 约 0.74 MB |

## 规则

1. **不要手改这里的文件。** 所有变更都必须来自上游仓库，通过
   `scripts/sync_vendored_skill.sh wechat [sha]` 同步，它会同时更新本文件的提交号。
   手改会让这份副本和上游分叉，也就失去了 vendoring 的意义。
2. 同步时排除 `.git`、`.venv`、`__pycache__`、`output`、`*.pyc`。
3. 不要在本仓库的 CI 里跑 `tests/`；那是 Skill 自己的测试，依赖和失败原因都与平台无关。
   验证只需要冒烟：能 import `toolkit.article_workflow`，能建空 `ArticleState`。

## 为什么需要它

同步时线上服务器 `/opt/universe-skills/weChat-autoCreate` 停在 `124d325`，而 GitHub
已经到 `0d4cd85`——没有人知道线上真正跑的是哪一版。这正是要收进仓库的原因。

## 怎么用

- 本地开发：把 `WECHAT_PUBLISHER_SKILL_DIR` 指向本目录。
- 生产切换：把该环境变量指到镜像内的 `/app/vendor/skills/weChat-autoCreate`，
  即可删掉 `/opt/universe-skills` 的只读挂载。切换前先按第 2 步的验收用例跑一遍。
