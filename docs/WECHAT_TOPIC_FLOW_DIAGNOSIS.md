# 公众号创作助手：为什么会"点了选题没响应"，以及这套流程为什么不通顺

诊断时间：2026-10-22 23:2x　诊断对象：`Gelen5/universe-wechat-detection` main
证据形式：代码位置 + 本机实测 + 截图行为对齐（无线上日志权限，第 3 节给出 3 分钟定位法）

---

## 0. 先说代码版本，避免诊错对象

- `git clone https://github.com/...` 直连超时（github.com:443 不通），改走 codeload 拉 `main` 分支压缩包（9.88 MB），解包到 `universe-wechat-detection/`。
- 与本机已有的 clone `D:\Download\universe-qihaoshou-writer`（HEAD `b8ae36a`，工作区干净）逐文件比对：忽略 CRLF 后**零差异** →
  **我看的这份代码，就是你现在线上跑的那份。**
- 顺带发现：仓库里其实并存**三套**公众号引擎，见 §4.6。

---

## 1. 结论：不是"没响应"，是"响应被吞了三次"

一句话：**消息确实发出去了，run 也确实跑了，失败信息被后端吞一次、被 view 层吞一次、被前端吞一次，最后只剩右上角一行灰字。**

### 1.1 失败如何一路变成"沉默"

| 层 | 位置 | 做了什么 | 用户看到什么 |
| --- | --- | --- | --- |
| 工具 | `server/agent/tool_loop.py:147-150` | 工具抛错 → `finish_tool_call(error=...)` → 继续 `raise` | — |
| 编排 | `server/agent/orchestrator.py:218-222` | `transition_run(failed, error_code, error_message)` → `raise`。**全程没有 `add_message`** | 对话区一条新消息都没有 |
| 任务 | `server/agent_tasks.py:69-79` | 只 `log_event("agent.run.failed")`，同上不落消息 | — |
| 事件 | `server/conversation_repository.py:349-351` | `run.failed` 事件里**其实带了** `error_code` / `error_message` | 前端拿到了，但没用 |
| 视图 | `server/conversation_repository.py:738-756` | `_run_view()` 把 `error_code/error_message` **剥掉**，只映射 4 类 `error_kind`，其余 `None` | `GET /api/runs` 只有 `error_kind: null` |
| 前端 | `static/conversation-workbench.js:383-387` | 收到 `run.failed`：`closeEvents()` → `setBusy(false)` → `refresh()`。**不插消息、不提示、不重试** | 只有一个进度条消失 |
| 文案 | `static/conversation-workbench.js:122-133` | `error_kind` 匹配不上 → 兜底 | 面板头部一行小字：`本轮执行失败，已按规则退还积分`（`static/index.html:348` 的 `#workbench-status`） |

截图右上角那行灰字，就是整条链路的全部反馈。**对话区里"用户说了三句、AI 一句不回"是必然结果，不是偶发。**

### 1.2 还有一个形状 bug：两处 payload 字段不一致

- SSE 的 `run.failed`：`{error_code, error_message}`
- `GET /api/runs/{id}`：`{error_kind}`（无 message）

前端 `failureText(payload)` 读的是 `payload.error_kind`（SSE 里永远 `undefined`），所以 `kind === 'queue'` 分支**永远不可能命中**；而它其实拿到了 `payload.error_message`，却只用来做正则分类，**从不显示**。

> 修这一条只要 3 行：把 `error_message` 截断后渲染成"技术信息"折叠块，"为什么失败"立刻自解释。

---

## 2. 为什么偏偏是"选题"挂：它是全流程唯一"全或无"的节点

`vendor/skills/wechat_writer/adapter.py:19-38` → `server/workbench.py:388-444`，选题要走 **6 道硬门**，任何一道不过，整条 run 直接 failed：

| # | 硬门 | 位置 | 失败形态 |
| --- | --- | --- | --- |
| 1 | `_require_skill()` 要求 skill 目录 5 个脚本 + 4 个 toolkit 全在 | `workbench.py:110-132` | `RuntimeError: wechat-publisher-ultimate Skill 未完整安装` |
| 2 | `references/topic-selection.md` 必须存在 | `workbench.py:391` | `FileNotFoundError` |
| 3 | **子进程跑 `fetch_hotspots.py`，60 秒硬超时，非 0 退出即中断** | `workbench.py:393-396` + `skill_runtime.py:46-50` | `ProviderError: 选题 Skill 热点抓取未成功，已停止生成` |
| 4 | 一次必须返回**合法 JSON**，两次不合格就放弃 | `workbench.py:365-376` | `文本 API 连续两次未返回合法 JSON` |
| 5 | `topics` **必须 ≥ 10 条**，且标题非空 | `workbench.py:419-435` | `选题不足10个` / `返回了空选题` |
| 6 | **去重后仍必须 ≥ 10 条** | `workbench.py:436-438` | `去重后可用选题不足10个` |

对比同一份代码里的**排版**（`workbench.py:1072-1155`）：只要一次小 JSON（4 个字段）+ 本地转换器，**不碰热点、不碰搜索、不要求条数**。

→ 所以"排版能成、选题怎么都不成"是**结构决定的**，不是模型偶然抽风。

**本机实测**（用和服务器完全一样的调用方式）：

```text
python -X utf8 scripts/fetch_hotspots.py --source all --limit 30 --json
exit=0  elapsed=7.47s     微博 403 被内部容忍，头条/百度返回 ~50 条
```

本地 7.5 秒成功 ⇒ 你本机不挂；但这段代码在生产上是**最脆的一环**：服务器一旦出网受限（境外 VPS 打不通微博/头条/百度、容器无出网、代理抖动），或首轮就超过 60 秒，`fetch_hotspots.py` 直接让**整条选题 run 失败**——它不是降级，是中断。这与你"排版正常、选题不动"的现象完全吻合。

### 2.1 还有一个只在选题出现的 bug：`brief` 被第一条消息永久污染

`static/conversation-workbench.js`:

```js
// 96-98：每次刷新，都把"第一条 topic 消息"整段当成 brief
const firstBrief = messages.find(m => m.role === 'user' && m.content_json?.workflow_stage === 'topic');
if (firstBrief) brief = firstBrief.content;

// 302-305：选题指令 = brief + 固定模板 + 补充要求
if (stage === 'topic') return `${brief || extra}\n只生成公众号选题，不写正文，不生成图片。${addition}`;

// 406：只在 brief 为空时赋值，之后永不清空、永不更新
if (stage === 'topic' && !brief) brief = content;
```

你截图里三条消息的第一行都是「继续」，正是因为**这个会话的第一条选题消息就是"继续"**，从此方向被死钉成"继续"。后面无论你补"我准备写一篇关于 AI 的文章"，模型收到的方向仍然是 `继续` + 模板 + 补充要求。

而"继续"恰恰是这个聊天式界面里最容易被敲出来的词——上一句 AI 说的是"当前阶段已完成，请查看作品区。"

> 所以严格说，这里有两个独立问题叠加：
> **① 方向传不进去（brief 污染）**；**② 即便方向传进去了，选题节点也可能整条失败（6 道硬门）**。
> 只看截图无法区分是哪一个先发生——用 §3 的方法 60 秒就能确认。

### 2.2 为什么能连发三条一模一样的

每次失败后 `setBusy(false)` 立刻解锁输入框，界面没有任何"失败卡片 / 重试 / 已提交过同样内容"的痕迹，用户只能重复发。三条消息 = **3 条独立 run、3 次工具尝试、3 次预留积分 + 3 次退回**（`conversation_repository.py:347-348`），并且三条都各自失败。

---

## 3. 3 分钟确认到底是哪道门（你在服务器上执行）

### 方式 A：直接用我加的排查脚本（只读）

```bash
python scripts/diagnose_agent_runs.py --conversation <对话id> --limit 20
python scripts/diagnose_agent_runs.py --all --limit 30     # 含卡在 queued/running 的僵尸 run
python scripts/diagnose_agent_runs.py --run <run_id>        # 单条完整时间线
```

它会把 `runs.error_code / error_message`、触发消息的 `workflow_stage`、`tool_calls` 的报错、`run_events` 全部打出来，并给出"下一步"对应的判断。

### 方式 B：直接查库（PostgreSQL）

```sql
-- 最近 20 条失败的 run，看真正的原因
SELECT r.id, r.status, r.error_code, left(r.error_message, 300) AS err,
       m.content_json ->> 'workflow_stage' AS stage,
       left(m.content, 80) AS user_msg, r.created_at
FROM runs r LEFT JOIN messages m ON m.id = r.trigger_message_id
ORDER BY r.created_at DESC LIMIT 20;

-- 失败码分布：选题是不是系统性全挂
SELECT error_code, count(*) FROM runs
WHERE created_at > now() - interval '7 days'
GROUP BY error_code ORDER BY 2 DESC;

-- 工具级报错（能区分"没调工具"和"工具内部炸了"）
SELECT tool_name, status, left(error_message, 200), count(*)
FROM tool_calls WHERE status <> 'completed' GROUP BY 1,2,3 ORDER BY 4 DESC;
```

### 方式 C：worker 日志

```bash
docker compose logs worker --since 24h | grep -E "agent\.run\.failed|agent\.run\.provider_error|tool\.failed"
```

结构化事件里有 `error_code`，会直接对应到 `_suggestions` 的哪一道门。

---

## 4. 整体流程审计：为什么"还是不太通顺"

按严重度排序，每条都给证据和改法。

### P0-1　输入框长得像聊天，其实不是聊天

- 阶段被 `localStorage` 钉死（`conversation-workbench.js:37, 449`），用户打的字**从不原样上送**，而是被 `stageInstruction()`（302-309）重写成"当前阶段"的固定指令。
- 你在「排版阶段」打"生成选题"→ 实际发出的是"用当前最新正文重新排版…"，你根本没法用自然语言切阶段。
- 「换一批方向」（517-519）只往输入框塞一句话，**不切阶段**：在排版阶段点它 = 再跑一遍排版。
- 页面上写的是「选题、检索、写作、审校、配图与排版」，输入框标签却是「当前阶段的要求」——两套预期。

**改**：输入框做意图路由（选题/大纲/正文/去AI/排版/配图 → 命中即切阶段并回显"即将执行：选题"），未命中才走自由对话；「换一批方向」先 `selectStage('topic')`。

### P0-2　失败无痕、无重试、无错误码（§1 已展开）

### P0-3　两个能力在新链路里**永远调不到**

`orchestrator.py:164-174`：

```python
required_tool = WECHAT_STAGE_TO_TOOL.get(stage) ...
if required_tool:
    tools = {required_tool: tools[required_tool]}   # 白名单收窄成 1 个
```

新 UI 永远带 `workflow_stage`（5 个之一）⇒ 工具永远只剩 1 个 ⇒

- `generate_image` **不可达** ⇒ 5 个阶段里没有"配图"，排版时 `image_artifacts` 恒为空（`workbench.py:113-116`）。
- `revise_article` **不可达** ⇒ 用户说"第三段改短点"时，只能重跑整个当前阶段，改不动局部。
- 但页头还写着"配图与排版"，`skill.json` 里 `capabilities` 也含 `image`。

### P0-4　5 段 UI vs 8 步 Skill，两套阶段模型

| UI（`conversation-workbench.js:38-44`） | Skill（`workbench.py:46 STEPS`） |
| --- | --- |
| 选题 / 大纲 / 写作 / 去AI / 排版 | 选题 / 框架 / 写作 / 反AI / **配图** / 排版 / **预览** / **发布** |

缺的两个（预览、发布）在新 UI 无入口：`#publish-draft`、`#open-preview` 仍只被 `static/app.js:1066-1073` 的旧分支绑着，而那两个节点所在的 `.flow-actionbar` 已被 `conversation-workbench.js:585` 整块 `hidden`。**写作→排版之后流程就断了**，用户只能自己复制 HTML。

### P1-5　三套引擎并存，旧 handler 还挂在同一批 DOM 上

- `/api/workflows/*`（`workflow_api.py`，`workflow_sessions/nodes/decisions` 那套）
- `/api/workbench/*`（`main.py:931-1114`，8 步 session 那套）
- `/api/conversations/*` + `/api/runs/*/events`（新，真正在跑的这套）

`static/index.html:778` 先加载 `app.js`，它仍在给 `#start-workbench`（983）、`#workbench-topic`（1029）绑旧逻辑；现在靠 `conversation-workbench.js:471-477` 的 capture + `stopImmediatePropagation` 把旧 handler 压住。**哪次加载顺序或某处提前 `preventDefault` 变了，就会双发/抢发**——这是"有时候点了没反应"的潜在来源，也是排查时最容易误判的地方。

### P1-6　「去 AI」是最贵的一段，但长得和别的阶段一样

`workbench.py:534-613`：最多 **4 轮**，每轮 2 个脚本 + 1 次 JSON 诊断，还要做保护片段核对；且强依赖**第二个** skill 目录 `ANTI_AI_SKILL_DIR`（`workbench.py:39-42`）。UI 上它和其它阶段同样一个按钮，用户对"为什么这一步要等 3 分钟"没有预期。

### P1-7　陈旧判定与产物映射靠时间戳

`isStale()`（174-179）用 `updated_at` 比较；改一个字就让下游全部"需更新"，但没有"从此处批量重跑"。`stageArtifact('writing')`（167）用 `run_id !== report.run_id` 排除修订稿，逻辑能跑但读起来很绕，容易在改动时出错。

### P1-8　SSE 一抖动就像"没反应"

`watchRun` 的 `onerror`（389-400）只在 run 已终态时收尾；run 还在跑就什么都不做（靠 EventSource 自动重连 + 事件重放）。代理/网关一缓冲，用户看到的就是"进度条不动、也不再出现新消息"。

### P2-9　运营侧也看不见原因

`agent_metrics()`（`conversation_repository.py:660-712`）只有 `failed_runs` 计数，**没有 error_code 聚合、没有阶段维度**。所以"选题是不是全挂了"这个问题，后台也答不出来。

---

## 5. 建议的修法（按性价比排序）

### 第一期（半天，止血，改完"没响应"永久消失）

1. **失败落进对话流**：`orchestrator.py` 的 `except` 里补一条 `add_message(assistant, …)`，文案含阶段名 + 人话原因 + "积分已退"，并同步写 `error_code`。
2. **前端失败卡片**：`run.failed` 不只改 `status`，要在 thread 里插红色卡片（原因 / 技术信息折叠 / **重试本阶段**）。重试复用同一个 `workflow_stage`。
3. **统一 payload**：`_run_view` 与 SSE 事件都带上 `error_code` + 截断脱敏的 `error_message`；前端 `failureText` 改为读 `error_code`，显示 message 摘要。
4. **选题降级而不是中断**：
   - `fetch_hotspots.py` 失败 → 继续，artifact 里标 `search_status=unavailable`（现在的 prompt 已经支持"没有实时热点"这种说法，只是代码不让它发生）。
   - 10 条 → **≥6 条即通过**，不足时让用户"再补 4 个"而不是整条失败。
   - 去重阈值 0.6 只在有 `published.json` 历史时启用。
5. **brief 不要从消息里猜**：`content_json` 增加显式 `topic_direction` 字段；`brief` 不再由 `renderMessages` 回填。
6. 「换一批方向」先 `selectStage('topic')`。

### 第二期（1-2 天，让流程真的"顺"）

7. 输入框 → 意图路由 + 自由对话（放开工具白名单，允许 `revise_article` / `generate_image`）；每条消息回显"将执行：<阶段>"。
8. 阶段与 Skill 对齐：要么补上「配图」「发布」，要么把 Skill 收敛到 5 步。别两套并行。
9. 每阶段一张状态卡（排队/进行中/耗时/产出/失败/重试），替代右上角一行小字。

### 第三期（结构）

10. 删 `/api/workflows` 与 `app.js` 里的旧 workbench 分支，单引擎单入口。
11. `error_code → 用户可执行文案` 映射表下沉到后端，前端只渲染。
12. `agent_metrics` 增加 `errors: {code: n}` 与按阶段的成功率。

---

## 6. 验收标准（现在缺的测试）

- `tests/test_agent_orchestrator.py`：工具抛错 → 断言**存在 assistant 失败消息** + `run.error_code` 落到事件 payload。
- `tests/test_workbench_stages_browser.py`：目前只 mock `run.completed`，**失败路径零覆盖** → 补一个 `run.failed` 用例，断言 thread 里出现错误卡片。
- 选题：`fetch_hotspots.py` 抛异常时 run 仍 `completed`，且 artifact 标注 `search_status=unavailable`。
- 选题：模型只返回 7 条时，run 不失败（走"补齐"提示）。

---

## 7. 一句话总结

不是"选题模型不行"，而是：**选题把 4 个外部依赖（skill 目录、热点脚本、搜索、严格 10 条 JSON）串成了一条全或无的门，失败信息又被后端、view 层、前端各吞了一次；再叠上"输入框其实是阶段参数框"的设计和 `brief` 被"继续"这类消息永久污染，用户就只能看到一句"本轮执行失败，已按规则退还积分"。**

先跑 `scripts/diagnose_agent_runs.py` 把 `error_code` 拿出来，就能在第 2 节那张表里对上具体是哪道门；剩下的都是上面第 5 节的活。
