# 扩展目录

这里放我们对第三方 Skill 的**增量**规则，由平台代码在加载时合并。

**为什么放在 `vendor/skills/` 之外**：`scripts/sync_vendored_skill.sh` 用
`rsync --delete` 同步上游仓库，放在里面会被下一次同步删掉。

| 文件 | 用途 |
|---|---|
| `references/anti-ai-methodology.md` | 用户原文存档，保留原样；不直接当作运行时强制协议 |
| `references/human-writing-strategy.md` | 策略节点：文章类型、表达路径、材料与缺口 |
| `references/human-writing-draft.md` | 首次成稿：具体表达与事实边界 |
| `references/human-writing-review.md` | 复核：局部修订、语境判断与保真 |

三份短规则统一由 `../node_rules.py` 读取，工作台适配器与 Skill 原生 host request 使用同一内容和 SHA-256。原生接入点由 `../native-node-rules.patch` 记录；同步脚本同步上游后重新应用，若上游结构变化导致无法应用则显式失败，不静默丢失扩展。独立使用未安装扩展的上游 Skill 时仍保持原流程。
