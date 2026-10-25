# 实证轻清理层

本参考用于已经成稿、只需要小范围降低模板感的文章。它吸收了
[`lieflat-less-ai-tone`](https://github.com/larashero3-dotcom/lieflat-less-ai-tone)
的白名单式改稿思想，并按本技能的事实边界、中文可读性和三档路由重新整理。

目标是减少误杀，不是增加禁词。公开仓库报告的语料统计无法由本仓库独立复现，
因此所有频率和倍率只作为规则候选的来源，不作为朱雀参数或作者身份判定。

## 使用条件

- `minimal`：必须读取本文件。原稿结构和未命中文字锁定。
- `standard`：用本文件定位句级风险，再处理局部重复和段尾闭环。
- `deep`：本文件只负责最后的句级清理，结构重排仍按 V4 参考执行。

如果用户提供目标作者的风格说明，先读取风格说明。作者长期稳定使用的破折号、
冒号、长句、问句或排比不能仅因本文件而删除。

## 可定位规则

| 规则 ID | 复核对象 | 处理边界 |
|---|---|---|
| `flip_rhetoric` | 虚立误解后翻案 | 材料确有判断修正时保留 |
| `dense_enumeration` | 一个分句内三项以上顿号罗列 | 法规、参数和必要清单不改 |
| `adjacent_isomorphic_sentences` | 相邻句逗号、成分和长度骨架近似 | 叙事动作链和有意排比不改 |
| `revelation_dash` | 普通判断用破折号揭晓或强调 | 服从作者原有标点习惯 |
| `prompt_colon` | “核心是：”“结论：”等提示语 | 前半句承担衔接时只换标点 |
| `empty_list_intro` | 空转一句只宣布下方有列表 | 列表内容不得删 |
| `ordered_headings` | 连续三个以上中文编号小标题 | 步骤、法规和交叉引用不改 |
| `idealized_role_metaphor` | 把工具写成全能导师、秘书、管家 | 普通比喻和具体人物喻体不改 |
| `nominalized_action` | 原稿已有动作却写成“完成了对……的优化” | 只恢复已有动作，不补新细节 |
| `banned_opener` | “说白了”“说穿了”“先说结论”起手 | 删除后不得改变语气强度 |
| `translation_*` | 五类可定位翻译腔 | 只处理脚本列出的五类，不扩大词表 |
| `paragraph_zero_subject_comment` | 非首段评论句没有回指对象 | 补回指或写明评论对象 |

运行：

```powershell
python scripts/check_ai_tone_signals.py <稿件> --mode minimal --json
```

脚本输出 `rule_id`、置信度、原文位置、理由和是否允许自动修复。高置信度也不等于
必须改；引用、法规、代码、对话和风格说明优先。

## 明确不作为单独改写理由

- 句长和段落长度是否参差。
- 正文中的“首先、其次”和普通序数词。
- 问句、设问和问句小标题。
- 被动句、长句和名词化本身。
- 句内排比、普通比喻和比喻独立成段。
- 重复人物全称、代词多少和虚词多少。
- 冒号、破折号的总数量。

这些项目可以作为节奏观察，不能单独授权改字。尤其不能把“不会因此”里的“因此”
当作句首路标，也不能把人物引语中的冒号当作提示性冒号。

## minimal 模式不变量

1. 标题层级、章节顺序、段落顺序、列表、表格、引文和代码块位置不变。
2. 未被 `check_ai_tone_signals.py --mode minimal` 标出的文字逐字保留。
3. 命中句也只修改解决该问题所需的最小部分。
4. 数字、日期、人物、机构、原话、链接、限定词、因果和判断强度不变。
5. 完成后运行：

```powershell
python scripts/verify_minimal_diff.py <原稿> <改稿> --json
python scripts/check_protected_spans.py <原稿> <改稿> --manifest <事实账.json> --json
```

任一脚本要求复核时，不得以黑盒分数为理由跳过。

## 内部事实账

长文或历史、法律、医学、商业数据稿在改写前建立事实账。最小格式：

```json
{
  "required": {
    "人物与机构": ["李清照", "张汝舟"],
    "关键动作": ["告发", "履历作假"],
    "限定词": ["可能", "据现有史料"]
  },
  "forbidden_additions": ["孩子", "博物馆"]
}
```

事实账采用文字存在性检查，只能发现显式丢失或补造；主体互换、因果反转和判断强度
仍需人工回读。

## 研究和许可边界

- 上游研究说明：<https://github.com/larashero3-dotcom/lieflat-less-ai-tone/blob/main/RESEARCH.md>
- 上游规则集：<https://github.com/larashero3-dotcom/lieflat-less-ai-tone/blob/main/SKILL.md>
- 上游采用 MIT License。本仓库对规则进行了重新组织和独立实现，归属信息见
  `THIRD_PARTY_NOTICES.md`。
