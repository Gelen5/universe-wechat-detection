# 内容工厂 V3 验收记录

状态日期：2026-11-07（Asia/Shanghai）

生产 release：`c76fcef`。上一回滚点：`dad42f0`。生产地址：
`https://yuzoudiyigongzuotai.cn/content-factory`。

本记录区分已部署的基础设施、真实付费调用、质量门禁结果和仍未通过的交付项；
测试替身或供应商返回成功都不能替代完整成品验收。

## 生产验收

已验证：

- 发布前数据库备份：`/opt/universe-backups/universe_pre_v3_20261107_153143.dump`。
- 备份 SHA-256：`0a8c7aff6d7aa69ee0d41d4899693c1bafb8b580011ed29f06c9995ea83ed919`。
- 备份可由 `pg_restore --list` 读取；隔离副本恢复、增量安装连续执行两次、列和旧商品数据核对均通过，副本已删除。
- 生产 Alembic 标记仍为 `20261025_0009`；V3 通过只增不删的
  `python -m scripts.install_content_factory_v3_schema` 安装，当前 7 张表齐全。
- Web、Worker、Beat、Auth、Postgres、Redis 正常；`/health/ready` 返回
  `database=true`、`redis=true`、`better_auth=true`。
- Worker 已注册 `content_factory.v3_titles`、`content_factory.v3_produce` 和
  `content_factory.v3_schedule`；Beat 注册北京时间 `08:00`、`15:00` 两个 V3 定时项。
- 匿名访问管理员自动化 API 返回 `401`；成品库页面和 V3 管理脚本均返回 `200`。
- 最终状态为紧急停止，自动选题、定时、文章/图片生产及自动上架全部关闭。

## 自动运行设置

管理员进入成品库后点击“管理成品”，在“自动化控制”中：

1. 勾选“自动生成文章”和/或“自动生成图片”。
2. 图片需要人物时选择“一定要有人物”；人物可能不合主题时保留“自动判断”；
   纯物品或风景选择“不要人物”。
3. 填写每天文章和图片数量，勾选“质量通过后自动放进成品库”和
   “每天早晚自动运行”。
4. 点击“保存并启动全自动”。系统会依次打开选题、生产、自动上架和定时任务。
5. 任何时候点击“立即全部停止”都会关闭所有自动开关。

“一定要有人物”要求原创虚构成年人物，不复刻真实人物、明星或公众人物，
也不生成未成年人。质量、版权、安全或视觉检查未通过的图片仍不会自动上架。

真实付费调用：

1. 文章 Run `bc3a39015929455bacb23d8194485a88` 已真实生成标题和正文。
   标题输入/输出为 `1458/475` token，正文为 `18051/3104` token。
   正文数据库字符数为 `1014`，去掉空白为 `998`，未达到 `1000–1200`
   门禁，因此没有调用朱雀，Run 和商品均正确保留为 `held` / `draft`。
2. 图片 Run `da2cf7a0f5224e539ec62ff26d35d737` 使用真实低粉图文来源，
   标题输入/输出为 `12498/493` token；图片供应商调用成功返回约 `2.96 MB`，
   记录 1 张生成图。后续确定性排版/交付阶段失败，Run 为
   `held` / `production_failed`，没有生成可购买商品。
3. 图片 Run `561a620d5abb4e51b92c8db5ec6c8c3b` 已完成真实标题、图片和视觉复核。
   商品 `bf219414f74b4f5bae709a906de954cc` 已自动上架，标题为
   “特殊身形如何选到合适的工作装备？”，售价 5 积分。
4. 成品图片为 `1080×1440` RGB PNG，大小 `1,300,830` 字节，预览接口返回 `200`。
   事实、安全、版权、标题一致性、编辑质量、图片解码、尺寸、文字和视觉质量
   全部为 `true`，质量报告结论为 `eligible`，原因列表为空。
5. 前两条 Run 没有触发自动上架；第三条 Run 成功写入成品库。

图片来源：

- 修复后从 200 个近期图片候选中识别出 30 条
  `verified_lowfans_image`。此前“0 条”是候选先截断再分类造成的分页缺陷。
- 图片联调来源为“礼簿写成这样太丢脸了！”：2026-11-04，阅读 `78,535`，
  账号基线 `809`，爆发倍数约 `97.08`。
- 该来源严格机会分为 `50.52`，低于配置的最低分 `60`；这是一次受控联调记录，
  不代表来源已通过最终选题评分。
- 最终成功来源为“大个子警官，衣服帽子得特别定制呀”：2026-11-04，阅读 `100,001`，
  账号基线 `1069`，爆发倍数约 `93.55`，严格机会分 `75.29`。

费用口径：

- 当前 `cost_micros` 是预算预留上限，不是供应商已结算账单。
- 三条文章预留和三条图片预留均仍为 `reserved`，`actual_micros` 为空。
- 新增 `content_factory_v3_provider_calls` 持久化标题、文章、图片和视觉调用的
  token、图片数量和延迟；现阶段仍不写猜测价格，实际账单核对应作为后续操作。
- 图片交付失败发生在供应商成功返回之后，不能声称没有产生图片费用。
- 最后一次修复使用原 Run 和原供应商幂等键 `factory-v3:image:561a…:0` 重放，
  没有增加 attempt；供应商仍返回了新的图片调用耗时和一条调用明细，因此不能
  在账单核对前断言只发生了一次图片计费。

仍未完成：

- 本地管理页浏览器自动化受当前代理/Chrome 网络路径阻塞；已通过生产只读 API、
  release 文件、数据库和匿名权限边界完成替代核对，仍缺一次真实登录后的截图复核。
- 图片因视觉配置缺失首次失败后，已增加配置继承和阶段诊断；最终成功路径已验证。

## 实现范围

- 只从已有低粉榜、图文榜和历史热点快照中选题；不重新抓取上游，不把历史选题库当作阅读效果证据。
- 标题、文章、图片、朱雀检测和图片视觉复核各走有界调用；失败不自动重试。
- 每日预算与每个环节的费用上限在派发前保存，完整流程的预留不足会优先暂缓。
- 每次 Run 保存证据、标题、尝试次数、质量报告和异常原因；正文不会写入朱雀检测记录。
- 文章必须同时通过来源、事实边界、版权、安全、标题一致性、编辑质量、存储和朱雀检测门禁；图片还必须通过技术检查、文字排版检查和全布尔视觉复核。
- 自动上架默认关闭，并受紧急停止、生产开关、自动上架开关、质量结论和内容指纹唯一约束共同控制。
- 最后一次数据库事务先写草稿、质量报告和 Run 状态，再在同一事务内尝试将合格草稿改为已上架。失败后保留草稿，不删除已有商品或购买记录。
- 发送到消息队列的结果不确定时，预算和排队状态保留，只允许管理员手动重新派发，不自动补发。
- `production_running` 不会被 Worker 按时间阈值自动重新认领。超时任务只能由管理员标记为异常，再显式手动重试；新的尝试号使用新的供应商幂等键。

## 本地测试证据

已执行：

```powershell
& 'D:\Download\content-factory-test-venv\Scripts\python.exe' -m pytest `
  tests/test_content_factory_detector.py `
  tests/test_content_factory_gates.py `
  tests/test_content_factory_image.py `
  tests/test_content_factory_opportunities.py `
  tests/test_content_factory_quality.py `
  tests/test_content_factory_titles.py `
  tests/test_content_factory_api.py `
  tests/test_content_factory_v3_provider.py `
  tests/test_content_factory_v3_publish.py `
  tests/test_content_factory_v3_schema.py `
  tests/test_content_factory_v3_store.py `
  tests/test_content_factory_purchase.py `
  tests/test_content_factory_app.py -q
node --check static/content-factory-v3.js
```

测试覆盖：选题匹配与来源时效、标题合同、质量门禁、朱雀结果归一化、图片技术检查和全布尔视觉门禁、预算预留、每日名额、自动上架前置条件、紧急停止、最多两次人工重试、旧草稿复用、重复执行、Provider 尝试幂等键、消息队列重派发、超时人工处置、部分表结构补列及 API 权限。

验证结果：`61 passed`，只有既有 Starlette/httpx 和 FastAPI `on_event`
弃用警告。`node --check static/content-factory-v3.js` 通过，
`git diff --check` 通过。

前端使用 Mock API 在浏览器验收：

- 桌面 `1440x1100`、移动 `390x844`；
- 指标、异常池、预算表单和任务按钮可渲染；
- 程序化检查未发现横向溢出；
- 截图位于 `qa-content-factory-v3-desktop.png` 和 `qa-content-factory-v3-mobile.png`。

这些截图是部署前的 Mock UI 证据，不替代真实管理员会话截图。

## 未验证范围

- 未执行 10 篇真实文章和 10 张真实图片的低粉来源端到端联调。
- 文字和图片供应商已发生真实调用；朱雀与图片视觉复核尚未在本轮完整成功路径中验证。
- 生产配置中的费用上限已由管理员填写并标记核实；实际账单仍未回填，因此不能把预留额当作结算额。
- 生产路径只按预留上限占额；`settle_budget()` 有单元测试，但尚未接供应商实际账单。当前 `cost_micros` 是预留占额，不是已结算账单。
- Alembic 历史标记仍与生产实际表结构不一致，本轮已通过备份后增量安装避开整链升级；该历史漂移仍需单独治理。
- 已在生产 PostgreSQL、Redis、Celery Worker 和 Beat 运行 V3，但未做多 Worker 竞争、Worker 强杀和 Redis 故障演练。
- 未验证被标记异常的旧 Worker 是否仍能完成远端调用；人工重试前应结合 Worker 日志、供应商账单或幂等响应判断。系统不会用时间阈值宣称旧任务已经结束。

## API

管理员鉴权沿用现有 `accounts.require_admin`。路径前缀为 `/api/content-factory`。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/admin/opportunities` | 从已有快照列出候选 |
| GET | `/admin/opportunities/topics?title=&track=` | 匹配历史选题灵感 |
| GET | `/admin/opportunities/images` | 分类图文来源，只有匹配低粉基线才是已验证低粉爆图 |
| GET | `/admin/opportunities/hotspots?title=` | 精确标题匹配近期热点 |
| POST | `/admin/opportunities/{source_id}/stage` | 保存可追溯候选；不调用模型 |
| GET | `/admin/automation` | 读取自动化设置 |
| PUT | `/admin/automation/limits` | 保存预算、单次上限、数量、赛道和费用核实状态 |
| POST | `/admin/automation/enable-title-planning` | 只开启有界标题调用 |
| POST | `/admin/automation/enable-production` | 开启文章/图片草稿生产，不自动上架 |
| POST | `/admin/automation/enable-publishing` | 仅对已启用且具备必要检测预算的生产通道开启自动上架 |
| PUT | `/admin/automation/schedule` | 开关每日定时选题；定时只选已有快照 |
| GET | `/admin/automation/runs` | 最近 100 个 Run |
| GET | `/admin/automation/metrics` | 当日候选、生成、质量、检测、上架、异常和成本占额 |
| GET | `/admin/automation/exceptions` | 暂缓/失败异常池 |
| GET | `/admin/automation/runs/{run_id}/detections` | 朱雀检测历史 |
| POST | `/admin/automation/runs/{run_id}/generate-titles` | 为候选预留下限并派发标题任务 |
| POST | `/admin/automation/runs/{run_id}/produce` | 预留完整流程并派发草稿生产 |
| POST | `/admin/automation/runs/{run_id}/retry` | 对暂缓/失败任务做最多两次显式重试 |
| POST | `/admin/automation/runs/{run_id}/dispatch` | 对仍处于排队状态的任务手动重派 |
| POST | `/admin/automation/runs/{run_id}/mark-stale` | 超时运行标记异常，不自动再调用 |
| PUT | `/admin/automation/runs/{run_id}/titles` | 管理员审阅或替换标题方案 |
| POST | `/admin/automation/emergency-stop` | 立即关闭所有自动选题、生产、定时和上架开关 |

## 成本配置

`daily_budget_micros`、`title_call_bound_micros`、`article_call_bound_micros`、`image_call_bound_micros`、`detector_call_bound_micros` 和 `vision_call_bound_micros` 使用同一计价单位。

当前实现按整数微单位计算，但尚未绑定具体币种、汇率或供应商账单。费用核实必须把文字、图片、朱雀和视觉调用换算到同一计价口径，例如人民币微元或美元微元；不能把不同币种的数字直接相加。

必须满足：

1. 每项实际启用的调用都有正的已验证上限；
2. 每日预算覆盖同一 Run 的标题、内容生成和独立质检预留；
3. 只有核对供应商币种与计价、换算倍数和潜在重试成本后，才设置 `cost_bound_verified=true`；
4. 图片生产需要单独配置视觉复核预算，文章生产需要单独配置朱雀预算；
5. 人工重试会使用新尝试号并单独预留预算，不自动释放未知费用；
6. 视觉复核当前使用文字模型通道，必须按其文字模型的实际 token 计价核实 `vision_call_bound_micros`，不能当作图片生成价格。

启动顺序不可倒置：先完成标题规划费核实，再启用内容生产，再启用自动上架，最后才考虑定时选题。

## 数据库迁移

新表全部在独立 `content_factory_v3_*` 命名空间中，当前共 7 张：

- `content_factory_v3_settings`
- `content_factory_v3_runs`
- `content_factory_v3_detections`
- `content_factory_v3_budget_reservations`
- `content_factory_v3_product_details`
- `content_factory_v3_quality_reports`
- `content_factory_v3_provider_calls`

迁移文件为 `db/alembic/versions/20261107_0018_content_factory_v3.py`；它只创建新表，并补齐已知新增列 `vision_call_bound_micros` 和 `attempt`，不删除表、不重写购买记录。

已知历史 Alembic 标记曾落后于实际生产表结构。正式迁移前：

1. 备份数据库和当前 `.env`；
2. 记录 `alembic current` 与实际表结构；
3. 在数据库副本演练迁移；
4. 确认 `20261107_0017` 及 V3 前序表存在且不被重复错误创建；
5. 生产标记无法安全沿用整个 Alembic 链时，使用 `python -m scripts.install_content_factory_v3_schema` 只增量建表和补列；
6. 再次执行安装脚本，确认可重复执行，并检查 `v3_ready()` 返回正常。

`scripts/install_content_factory_v3_schema.py` 只增不删，不修复未知的迁移漂移。生产 V3 安装和回滚不得删除已有购买或审计记录。

## 启动顺序

1. 完成数据库备份和迁移；
2. 启动 Redis 和 PostgreSQL；
3. 启动 Celery Worker，确保队列包含 `text`、`image`、`chat`、`external` 和 `workflow`；
4. 启动 Beat；V3 定时任务在数据库开关关闭时无副作用；
5. 启动 Web，检查 `/health/live` 和 `/health/ready`；
6. 以管理员打开 `/content-factory`，确认自动化设置仍为紧急停止；
7. 核对供应商配置、费用上限和赛道；
8. 使用无发布权限的试运行做人工验收，再决定是否开启标题规划、生产和自动上架。

## 紧急停止

Web 控制页的“紧急停止”或 `POST /api/content-factory/admin/automation/emergency-stop` 会关闭选题、定时、文章/图片生产和自动上架。已经排队或执行中的付费任务可能无法撤销，远端调用仍可能完成；只能通过任务异常池审核，不能声称已经取消。

紧急停止后，新的生产调用和自动上架会失败关闭，但已保存的草稿与审计记录保留。

## 重试与异常

- 自动派发失败不会自动重试；
- 排队任务在提交结果不确定时仍保留预算，管理员先检查消息队列，再使用“重新派发”；
- 超过标题 `900` 秒或生产 `1800` 秒的运行任务可以被管理员标记异常；
- “标记异常”不等于取消远端请求，也不代表已退款或已确认零费用；
- 人工重试前核对 Worker 日志和供应商账单；重试最多两次；
- 相同内容指纹不能第二次自动上架；
- 已有草稿重试复用同一 `product_id`，不另建第二件商品。

## 回滚

1. 先执行紧急停止；
2. 保留 V3 表和审计记录，停止新的 V3 Worker/Beat 调度；
3. 将 Web/Worker 回退到上一发布版本；
4. 已知 V3 功能在旧版本不可见时，确认旧版访问入口和购买、钱包路径正常；
5. 检查旧版本是否忽略 V3 表；不要删除新表或购买数据；
6. 若新表导致问题，只前向修正或隔离，不执行破坏性降级；
7. 恢复已改动的应用版本前，核对 `/health`、管理员权限、钱包余额、商品购买和完整内容授权。

回滚前必须确认哪些 V3 草稿或商品已进入生产数据。生产回滚不能把新写入反向同步到旧数据库。

## 验收结论

生产部署、数据库备份与增量安装、Web/Worker/Beat、健康检查、匿名权限边界、
文章生成失败门禁、图片供应商调用、异常池失败路径和一张图片成品自动上架均已验证。

本轮图片成品已真实写入成品库；文章仍因 998 个非空白字符被质量门禁拦截。
扩大真实调用前，应完成真实登录后的管理员页面截图复核，并核对供应商账单，
尤其是最后一次幂等键重放是否产生额外图片费用。
