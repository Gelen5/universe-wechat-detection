# 扩展目录

这里放我们对第三方 Skill 的**增量**规则，由平台代码在加载时合并。

**为什么放在 `vendor/skills/` 之外**：`scripts/sync_vendored_skill.sh` 用
`rsync --delete` 同步上游仓库，放在里面会被下一次同步删掉。

| 文件 | 用途 |
|---|---|
| `references/anti-ai-methodology.md` | 复核节点的规则源（替换旧的“最小改动”规则） |
