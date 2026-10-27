# 公众号创作链路与质量升级审计

本次基线是 `d4fba11b0d807492f5e8724a796d7369d335804e`。经 fetch 确认远端 HEAD 相同；本地还保留上一轮去 AI 修复，未覆盖。旧的线上证据见 `deai-execution-investigation-20261027.md`。本文件描述源码和测试，不代表所有路径都已完成线上人工验收。

## 真实路径

```text
公众号创作页面
  → /api/conversations/{id}/messages → Agent Run / Celery
  → AgentOrchestrator → wechat_writer.write_article
  → _framework（无大纲才调用；检索） → workbench._draft（模型一次成稿）
  → article Artifact
  → review_article → workbench._review（检测、诊断、局部替换、审计）
  → 新 article Artifact + report Artifact
  → typeset_article（读取该任务提交时的文章快照）→ html Artifact
  → 网页复制排版到公众号后台

旧持久工作流：workflow_engine → workbench.step → 相同的 _draft/_review
  → ArticleState 合并状态 → 排版/预览 → workbench.publish 草稿箱

一键成文：qihaoshou.draft_prompt → 流式生成与保存 HTML
  → 可选 qihaoshou/deai（独立的 HTML 文本节点改写与保意复核）
  → 可选 qihaoshou/wechat-draft
```

普通 Agent 页没有通过 `workbench.publish` 自动写入草稿箱的证据，页面交付入口是富文本复制。旧持久工作流的草稿箱发送前检查 `typeset_article_sha256`，一键成文发送当前保存的 `data['html']`。不得把这两条链路的校验当作 Agent 复制入口已有的保护。

创建 Agent Run 时保存输入 Artifact ID；`run_inputs` 用这些 ID 加当前 Run 已成功产生的作品构造输入。`write_article` 从大纲构建 `_draft`；`review_article` 和 `typeset_article` 优先读取输入快照的文章，而不是信任模型工具参数。保存为新版本不会改写先前 ID。运行中用户再保存了正文，该次任务仍消费提交时的快照，这是隔离而非动态追最新。

`_draft` 当前会加载 Skill 的 `SKILL.md`、`writing-protocol.md`、平台规则、黑名单及 `node_rules('draft')`，并提供用户需求、框架、写作策略与精简检索材料；两个生成入口共享 `writing_guidance.GUIDANCE`。文件存在不等于每个内部节点都调用：`toolkit.article_workflow` 的 `AuthorProfile` 是数据结构和宿主请求的一部分，当前 Agent 入口没有按用户／公众号自动读取一个历史文章风格档案。传入的 `persona` 是语气字符串，不等于经过授权的作者画像。

## 已有证据与风险

在用户授权的公众号创作样本中，去 AI 的成功 Run 确实调用了模型并保存正文 V2、V3。V1→V2 字符相似度 97.28%，唯一的局部替换删去三个末节选项却留下冒号引导句，旧审计仍给出 passed。V3 和后续 HTML 的来源另见已有调查。说明规则已经进上下文，仍不能保证模型自然、内容充分或语义无损；也不能据此推断所有题材及用户。

此外，Agent 页面在正文更新后仍可从行动卡复制旧 HTML；旧页面已有阶段时间提示，但复制入口没有阻止旧产物。此次为新排版记录正文 ID、版本与摘要，并在页面当前已加载版本不匹配时提示重新排版；旧 HTML 使用时间戳回退判断。历史作品保留查看，明确选择更早的 HTML 仍可复制。**这些判断依赖页面已加载的版本，不能证明跨标签页并发修改期间一定不会复制旧稿；线上浏览器尚未验收。**

## 开源项目选择和边界

核查时四个 GitHub 仓库声明 MIT。仅吸收适用原则，没有把四个项目或其脚本串入运行时；未引入新的第三方软件包。

| 项目 | 已核查的 main 版本 | 结论 |
| --- | --- | --- |
| [Human Writing](https://github.com/KKKKhazix/human-writing) | `4fda173f3fef7fb808f3eba991eeb2528ea4b189` | 参考材料支撑、段落推进、文体适配；不采用材料不够就阻塞出稿、禁用冒号等与产品要求冲突的规则。 |
| [Humanizer-zh](https://github.com/op7418/Humanizer-zh) | `f4518a8eab97b8bfebc66a89d34320a89bef6930` | 保意、只修改有依据的问题、检查上下文，已有去 AI 节点继续负责；不增加全文精修步骤。 |
| [antiAI-skill](https://github.com/SoeyMoner/antiAI-skill) | `27d29232f10124db904ca9c0536d0b67cb3b2833` | 规则命中仅是编辑线索，不输出 AI 来源概率；暂不合入依赖或固定阈值。 |
| [Writing DNA](https://github.com/larashero3-dotcom/writing-dna-skill) | `ee3d97ee27268004b5187d97711161f44fc4aae4` | 上游要求至少 20 篇且写作时读取相关文章；不能把它等同于已有 3–20 篇的缓存画像系统，暂未集成。 |

## 本批实现与限制

- `server/writing_guidance.py` 增加按材料、读者问题和文体组织的短规则；公众号和一键成文初稿均直接拼接，不追加一次模型请求。`WECHAT_WRITING_QUALITY_V1=0` 关闭新增规则；空值及默认开启。旧有共享约束仍存在。
- `_draft` 记录不含正文的 `writing.draft` 日志，包括 Run、模型、规则版本、输入／输出哈希、耗时和状态。token 用量仍由原有 `provider_calls` 负责；不是全链路所有节点的新日志方案。
- 沿用上一轮局部去 AI 安全修复、审计失败保留原文及差异说明。拦截特定悬空列表和新增整段重复，并非一般语义保真保证。
- `typeset_article` 的 HTML 元数据记录本次输入正文 ID、版本和 SHA-256，网页对于已加载的过期最新排版提示重新生成，保留历史查看。
- 没有增加新必填选项、独立模型节点、外部检测、数据库表或用户文章额外留存。没有自动让原文生成任何画像。
- 本批定向回归 133 passed、6 subtests passed，包含两条初稿入口、回退开关、去 AI 原稿保护、快照来源、JS 过期判断、会话持久化与积分；Node 语法检查通过。测试使用隔离数据库和替身模型，不等于浏览器或线上验收。

P2 的多用户多公众号作者画像导入、生成、编辑、禁用、缓存与回滚尚未实现；P3 的统一覆盖所有质量问题的诊断也未完成；P4 要求的 20 题四组、人工盲评及真实性评估尚未执行。不能以测试通过、单次真实调用、规则命中或检测器结果宣称质量提升。

两种合成素材使用同一 gpt-6.1-sol 和相同的框架、要求与上下文，随机排列顺序，对新增规则开／关各调用一次；绕过用户账本，不修改线上稿件：

| 合成题材 | 旧规则：秒 / 输入 token / 输出 token | 新规则：秒 / 输入 token / 输出 token | 每篇调用 |
| --- | --- | --- | --- |
| 会议纪要教程 | 33.79 / 25845 / 1234 | 34.30 / 26044 / 1243 | 各 1 次 |
| 虚构故事 | 67.75 / 25807 / 1917 | 64.16 / 26006 / 1829 | 各 1 次 |

没有人工盲评；单次耗时不证明性能差异或质量提升。教程输出仍有重复说明，故事只说明该题材下模型可以继续生成。完整合成样本及计量位于仓库外 `D:\Download\workbench-audit-20261027\quality-draft-ab-results.json`，不含客户文章。
