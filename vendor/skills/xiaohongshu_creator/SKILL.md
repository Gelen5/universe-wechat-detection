---
name: xiaohongshu-creator-skill
description: 独立执行小红书账号定位、数据接入、对标拆解、选题、图文或视频草稿、发布前检查、人工发布记录与发布后复盘。用户提到小红书运营、笔记、选题、封面、标题、对标、发布检查、数据复盘或小红书内容增长时使用。
---

# 小红书创作者链路

这个 Skill 把 CreatorBuddy 中的小红书链路独立出来，负责平台化判断和操作编排。CreatorBuddy 的 CLI 仍是统一执行核心；本 Skill 不复制评分、复盘或策略数据库，也不把公开样本当成自有账号事实。

## 总链路

```text
确认账号与目标
  -> 读取自有内容、指标、评论和转化证据
  -> 接入公开趋势与对标样本
  -> 标注证据等级
  -> 选题评分
  -> 小红书平台化草稿
  -> 发布前检查
  -> 人工发布
  -> 记录 content_id、发布时间和指标
  -> 2h/24h/48h/7d 复盘
  -> 生成待确认策略
  -> 用户确认后影响下一次选题
```

## 深度能力路由

本 Skill 按用户意图路由到一套完整的小红书能力层：账号诊断、对标账号质量闸门、单篇笔记拆解、对标框架原创改写、标题与关键词联动、4–7 页内容包、真人贴纸封面 Brief、发布前闸门和发布后漏斗复盘。

详细输入输出契约见 [references/deep-integration.md](references/deep-integration.md)。执行时优先复用 CreatorBuddy 的数据和命令，不复制第二套评分、发布数据库或策略状态。

## 执行规则

- 先确认工作区、账号、目标和交付物。
- 先读自有证据，再读公开样本；没有自有数据时，只能明确标注冷启动或待补充。
- 将证据区分为：自有、公开样本、推断、历史、未知。
- 不保证爆款，不编造曝光、点赞、收藏、评论、私信、成交或收入。
- 平台表达优先具体场景、搜索问题、步骤、清单、避坑和收藏价值。
- 每个草稿必须有具体对象：工具、Skill、产品、案例、工作流或已验证经历。
- 小红书发布目前由用户人工完成；本 Skill 只负责发布前准备和发布后记录，不声称已经发布。
- 发布后先记录事实，再解释原因；策略先进入待确认状态，不能自动成为永久规则。

## 标准操作

### 1. 初始化与取证

在 CreatorBuddy 仓库中执行：

```powershell
python scripts/creatorbuddy.py quickstart
python scripts/creatorbuddy.py onboarding-status
python scripts/creatorbuddy.py collect-platform --platform xiaohongshu --kind owned --json '[...]'
```

读取 `config/agent_config.json`、`data/published_content.jsonl`、`data/raw_signals.jsonl`、`data/normalized_signals.jsonl` 和 `reports/`。优先核对账号定位、近期内容、真实指标、评论、转化和已确认策略。

### 2. 对标与趋势

公开主页或笔记只能作为趋势证据：

```powershell
python scripts/creatorbuddy.py import-benchmark --platform xiaohongshu --url "完整主页链接"
python scripts/creatorbuddy.py segment-benchmark --benchmark-id "benchmark-id"
python scripts/creatorbuddy.py distill-creator --benchmark-id "benchmark-id"
python scripts/creatorbuddy.py collect-platform --platform xiaohongshu --kind xhs-note --file note.html --benchmark-id "benchmark-id"
```

优先使用已登录浏览器或适配器获得的完整签名链接；短链接、无登录态、验证码和私有接口失败时停止重试并说明缺口。对标分析重点是结构、主题、标题和可迁移形式，不能复制原文、图片、身份故事或数据。

对标账号第一轮最多推荐 5 个，并检查近期更新、粉丝区间、账号阶段和多条内容证明。单条偶然爆文只能标记为 `single-note-sample`，不能直接当作主对标。对单篇笔记按“标题/封面 → 开头/结构 → 证据/评论 → 传播机制 → 可学与不可复制 → 我的改写方向”拆解；对标文案先抽取槽位，再填入用户真实素材。

### 3. 选题与草稿

```powershell
python scripts/creatorbuddy.py run-daily
python scripts/creatorbuddy.py today
python scripts/creatorbuddy.py draft --platform xiaohongshu --topic "具体选题"
```

小红书草稿必须包含：主页 3 秒理解、选题功能、标题模式、封面短句、正文步骤、置顶评论、异议回复、低压 CTA、content_id 和 24h/48h/7d 指标字段。默认优先 1 张封面 + 5 张内容页；标题提供 3 个具体版本，封面主标题不超过两行。没有自有证据、产品/案例证据或对标结构时，输出缺失清单，不直接给最终稿。

当用户只给关键词、链接、截图或参考图时，默认进入内容包模式：输出 3 个标题、封面 Brief、4–7 页页面规划、正文、10 个关键词、置顶评论、异议回复和复盘字段，并显式列出假设与未知信息。标题每次默认只给 3 个强版本，每个版本说明关键词锚点、点击理由、正文交付要求和封面一致性。关键词最多 10 个并标注自然埋点位置。

封面或内容页生成前必须给出画幅、主题、人物动作、服装、背景、标题文字、卡片文字、配色和禁用元素。默认使用 README 记录的真人贴纸爆款教程风，同组至少 4 种不同人物动作；生成后检查乱码、裁切、重叠、重复人物、水印、二维码和未经证实的数据。

### 4. 发布前检查

```powershell
python scripts/creatorbuddy.py precheck --platform xiaohongshu --title "标题" --content "正文或脚本"
```

检查具体证据、夸大承诺、标题空泛词、搜索意图、步骤完整性、CTA、content_id 和平台表达。标题出现“天花板、宝藏、被问爆了、高级感、YYDS、封神、谁懂啊”等空泛词时要求重写。

额外检查标题点击理由、封面 3 秒识别、前三行问题、关键词自然度、主页承接和 CTA。输出 `ready / revise / blocked`，并给出 3 个精确修改，不只给分数。

### 5. 人工发布与回填

人工发布完成后立刻记录：

```powershell
python scripts/creatorbuddy.py add-content --platform xiaohongshu --status published --title "已发布标题" --content-id "xhs-..." --published-at "2026-08-15T20:00:00" --metrics-json '{"views":0,"likes":0,"saves":0,"comments":0}'
```

缺少的指标保留为空或写入“待补充信息”，不能用公开样本或早期播放数补齐。

### 6. 复盘与策略

```powershell
python scripts/creatorbuddy.py review-due
python scripts/creatorbuddy.py post-review --content-id "xhs-..."
python scripts/creatorbuddy.py self-growth
python scripts/creatorbuddy.py approve-strategy --candidate-id "candidate-id"
```

复盘输出必须先列事实，再给判断，再给下一次测试。重点观察曝光、点赞率、收藏率、评论质量、关注、私信、咨询和成交；没有字段就标记为未知。

优先定位漏损环节：曝光对应选题/关键词，点击对应标题/封面，阅读对应开头/结构，收藏对应实用价值，评论对应互动设计，关注对应主页承接。一次复盘只建议测试一个变量。

## 与 CreatorBuddy 的边界

CreatorBuddy 负责统一的账号数据模型、评分、内容资产、复盘和策略状态。本 Skill 负责小红书平台规则、内容结构和操作顺序。不要在本 Skill 中另建评分器、发布数据库或第二套策略系统。

详细证据边界、数据字段和 Web/CLI 注意事项见：

- [references/evidence-and-data.md](references/evidence-and-data.md)
- [references/content-and-precheck.md](references/content-and-precheck.md)
- [references/creatorbuddy-commands.md](references/creatorbuddy-commands.md)
- [references/deep-integration.md](references/deep-integration.md)
