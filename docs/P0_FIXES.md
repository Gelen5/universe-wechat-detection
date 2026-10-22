# P0 修复：把公众号创作这条链路打通

实施日期：2026-10-23　基线：main / `b8ae36a`
范围：**只做 P0（止血 + 打通）**，不含「作品」tab、含配图、自由改写。

---

## 一、改了什么（5 件事）

### 1. 失败必须落进对话流（后端 + 前端）

**之前**：任一阶段失败只改 `runs.status`，不写任何消息；前端只把面板右上角一行灰字改成「本轮执行失败，已按规则退还积分」。用户看到的就是"没响应"。

**现在**：

| 文件 | 改动 |
| --- | --- |
| `server/agent/failures.py`（新） | `describe(exc)` 把异常归一成 13 种 `error_kind`（`provider_access` / `provider_balance` / `skill_missing` / `topic_source` / `topic_schema` / `timeout` / `tool_error` …）+ 一句人话原因 + 是否可重试；`fail_run()` 负责"转终态 + 写一条 assistant 消息"，靠 `transition_run` 的终态保护做到幂等，重复调用不会刷出多条 |
| `server/agent/orchestrator.py` | 两个 `except` 改为调用 `fail_run`，不再只 `transition_run` |
| `server/agent_tasks.py` | Celery 侧的重试耗尽 / 未捕获异常同样走 `fail_run` |
| `server/conversation_repository.py` | `_run_view` 暴露 `error_code`（有界枚举，**不暴露** `error_message`，避免 provider request id 泄漏）；`run.failed` 事件载荷同样只带 `error_code` / `error_kind`；终态 run 不能被二次转移（原来同状态可以再进一次，会二次退款 + 二次事件） |
| `static/conversation-workbench.js` | 失败消息渲染成红色卡片：原因 + 「重试这一步」+「查看作品」+ 折叠技术信息；`failureText` 按 `error_code` 出人话 |

失败文案示例：

```
「选题」这一步没有跑完。
原因：抓取热点的脚本超时或被网络拦截。
这通常是一次性的，直接重试即可。
本轮积分已自动退回，已完成的阶段不会丢。可以点下面的「重试这一步」。
```

### 2. 选题不再"一挂就整条死"

`server/workbench.py:_suggestions`

- 热点脚本失败 / 返回非列表 → **降级继续**（`hotspot_status=unavailable`），并在 audit 里记 `degraded`，不再抛 `ProviderError`；
- 10 条硬门槛 → **≥6 条即通过**，可用 `WECHAT_TOPIC_MIN` 调整（默认 6）；不足时报"模型只返回了 N 个选题，低于最低要求 M 个"；
- 空标题逐条丢弃而不是整批失败；
- 历史去重变成"能去就去"：去重后仍够数才替换，否则保留并给近似项打 `note`；
- 证据里新增 `hotspot_status`，前端/报告能区分"没热点"和"没生成"。

### 3. 输入框从"阶段参数框"变回聊天

**之前**：`stageInstruction()` 把用户输入重写成当前阶段的模板句，阶段被 localStorage 钉死；在排版阶段打"生成选题"实际发的是"重新排版"。

**现在**：

- 前端只发**用户原话**，`content_json` 带 `workflow_stage` / `topic_direction` / `selected_topic`；
- 阶段指令改由后端拼：`orchestrator.stage_contract()`（阶段名 + 必须调用的工具 + 用户方向 + 已确认选题 + 阶段要求）；
- `resolveStage()` 做意图路由：`排版 / 去AI / 大纲 / 正文 / 选题` 关键词命中且前置产物齐备就切阶段，否则落到"下一个该做的阶段"；
- 五个阶段都完成后，无法识别的话**不会**被误当成"再排一次版"，而是提示去作品区编辑；
- 附件：`index.html` 里输入框标签改成「想写什么 / 下一步做什么」，面板副标题去掉尚不可用的「配图」。

### 4. 一条链路在对话里走完

新增线程级 **下一步卡片**（`renderActionCard()`）：

| 状态 | 卡片内容 |
| --- | --- |
| 无选题 | 「先告诉我你想写什么」 |
| 有选题未选方向 | 6 个方向 chips（直接点） |
| 已有方向 | 「继续：大纲 / 写正文 / 去 AI / 排版」+「直接排版」 |
| 失败 | 「重试：<阶段>」 |
| 已排版 | 「复制 HTML」+「查看作品」 |

右侧画布的按钮仍然可用，但不再是唯一路径；窄屏也能走完全流程。

### 5. 方向不再被"继续"污染

`conversation-workbench.js`

- 删掉 `brief`（原来把"会话第一条 topic 消息"永久当成方向）；
- 方向只来自显式 `topic_direction`，并按会话存 localStorage；
- 输入「换一批 / 换个方向 / 再换」等再生成语句时**沿用**原方向，不会把这句话当方向；
- 「换一批方向」按钮现在会先切回选题阶段再重跑（原来只往输入框塞一句话）。

---

## 二、验证

```bash
# 全量（除浏览器用例）
python -m pytest tests -q --ignore=tests/test_workbench_stages_browser.py
# → 246 passed

# 浏览器用例（需要 playwright + 本机 Chrome）
python -m pytest tests/test_workbench_stages_browser.py tests/test_workbench_failure_browser.py \
                 tests/test_workbench_chat_chain_browser.py -q
# → 3 passed
```

新增用例：

| 文件 | 覆盖 |
| --- | --- |
| `tests/test_run_failures.py` | 失败分类；`fail_run` 写入 thread；重复调用不重复写；已完成 run 不被降级；**不泄漏 provider 细节**；orchestrator 真实失败路径写消息；重试生成新 run |
| `tests/test_topic_resilience.py` | 热点超时/返回异常 → 降级；6 条通过；不足时报可行动文案；历史重合不阻断；空标题丢弃 |
| `tests/test_workbench_failure_browser.py` | 失败卡片出现在对话流 + 点重试复用原方向 |
| `tests/test_workbench_chat_chain_browser.py` | 从对话流一路点到「复制 HTML」，不碰右侧画布 |

---

## 三、上线注意

1. **必须重启 worker**：`failures.py` / `orchestrator.py` / `workbench.py` 都在 worker 里执行。
2. **web 也要重启**：`conversation_repository.py`（run 视图与事件载荷）在 web 进程。
3. **无数据库迁移**：没有新表/新列；`error_code` 只是既有字段的新取值。
4. 静态资源已加版本号 `?v=20261023-p0`，浏览器会拿到新 JS/CSS。
5. 可选环境变量：`WECHAT_TOPIC_MIN`（默认 6）。
6. 行为变化：终态 run 不能再被 `transition_run` 二次写入（这是修复重复退款/重复事件的必要约束）；如有脚本依赖"同状态重复转移"，需要改。
7. 老会话兼容：历史消息没有 `topic_direction`，方向会从第一条带该字段的消息恢复；没有的话为空，此时"重试选题"会用默认句作为方向（一次性，之后会被新方向覆盖）。

---

## 四、这轮**没做**的（以及为什么）

| 项 | 原因 |
| --- | --- |
| 一键写入公众号草稿箱 | 现有发布脚本要三样输入：`article.md`（过推荐质量门禁）+ 封面图 + base64 内联图片的 `approved.html`。新链路只有 HTML 片段与文章正文，硬接会在用户账号里造出坏草稿。P1 里补"从 artifact 组装 + 预检"，并与「作品」tab 一起做 |
| 配图阶段 | `generate_image` 工具存在，但 5 段导航没有位置、工具白名单按阶段收窄到 1 个。需要一起改 UI 与 orchestrator，属于 P1 |
| 自由改写（"改第三段"） | `revise_article` 同样被白名单挡住。P2 计划用"意图 + 动作"两段式路由放开 |
| 全局任务 dock / 作品 tab | P1，依赖 `documents` 数据模型 |
| 删旧引擎（`/api/workflows`、`app.js` 旧 workbench） | P2，改动面大，先不动 |

---

## 五、改动清单

```
server/agent/failures.py                      +147  (新)
server/agent/orchestrator.py                   +38  -10
server/agent_tasks.py                           +5   -8
server/conversation_repository.py              +37   -8
server/workbench.py                            +38  -20
vendor/skills/wechat_writer/adapter.py          +1
static/conversation-workbench.js              +222  -40
static/conversation-workbench.css              +45
static/index.html                               +4   -4
tests/test_run_failures.py                    +167  (新)
tests/test_topic_resilience.py                 +73  (新)
tests/test_workbench_failure_browser.py       +101  (新)
tests/test_workbench_chat_chain_browser.py    +110  (新)
                                    合计     +988  -90
```
