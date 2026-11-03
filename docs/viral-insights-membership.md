# 爆款情报会员（viral_insights）上线与回滚

统一权益：`viral_insights`。低粉爆文（`/lowfans`）与低分爆图（`/image-board`）共用一份。

## 一、功能边界

| 能力 | 是否属于会员 | 说明 |
| --- | --- | --- |
| 查看低粉爆文完整榜单与详情 | 是 | 会员/试用有效即完整返回 |
| 查看低粉爆图完整格子、封面、原文 | 是 | 封面走 `/api/image-board/cover` 代理 |
| 导出 CSV | 否 | 仍按 20 积分单独计费，但**同样要求有效访问权益** |
| 实时刷新互动数 | 否 | 仍按 3 积分单独计费，同上要求权益 |
| 积分充值、邀请返积分、其他创作工具 | 不受影响 | 代码路径完全隔离 |

无权益时只能拿到服务端裁剪的预览：低粉 5 条、爆图 5 条，爆图预览可查看固定位置的封面；
低粉预览展示完整标题、账号、阅读数和爆发倍率；不含 `art_id`、原文 URL、账号基线及其他互动数据。预览忽略客户端的 `page` / `date` /
`sort` / `q`，无法靠翻页或换筛选条件把整榜拼出来。

`/api/lowfans/meta` 保持公开，只返回日期、赛道计数、总条数等聚合元数据。

## 二、开关与配置

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `VIRAL_INSIGHTS_PAYWALL_ENABLED` | `0`（关闭） | 总开关。关闭时接口行为与上线前完全一致，前端不显示会员入口 |
| `VIRAL_INSIGHTS_PREVIEW_LIMIT` | `5` | 无权益预览条数（1–10） |
| `IMAGE_BOARD_SYNC_ENABLED` | `0`（关闭） | 低分爆图定时同步开关；关闭时不注册 beat 调度项 |
| `IMAGE_BOARD_SYNC_PAGES` | `10` | 每次同步页数（1–10，每页 1 积分） |
| `IMAGE_BOARD_STALE_HOURS` | `48` | 超过该小时数未成功同步即标记 `degraded` |
| `IMAGE_BOARD_SYNC_HOURS_UTC` | `2,6` | 同步小时（UTC），仅在同步开关打开时生效 |

套餐由服务端固定定义，客户端不能改金额或天数：

| id | 名称 | 价格 | 天数 |
| --- | --- | --- | --- |
| `week` | 周卡 | 9.90 | 7 |
| `month` | 月卡 | 29.90 | 30 |
| `year` | 年卡 | 199.00 | 365 |

非自动续费。金额只取服务端定义，请求体里的 `total_amount` / `days` 一律忽略。

## 三、数据与迁移

- 业务表：`viral_insights_trials`（一次性试用）、`viral_insights_membership_orders`（会员订单）。
- 支付单据复用既有 `alipay_orders`，会员订单在 `viral_insights_membership_orders` 单独记录，
  **不写 `alipay_recharges`**，因此不会误充积分、不会触发邀请充值奖励。
- 版本化迁移：`db/alembic/versions/20261104_0013_viral_insights_membership.py`
  （`down_revision = 20261103_0012`）。
- **建表实际路径**：本仓库生产部署用 `up -d --no-deps`，compose 的 `migrate`
  服务不会执行；线上 `alembic_version` 实测停在 `20261025_0009`，而 `wechat_plus_*`、
  `referral_*` 等表实际由各模块 `init_schema()` 启动时创建。会员表沿用同一惯例
  （`create_all(checkfirst=True)`），否则开启开关会因缺表直接 500。
  Alembic 迁移保留为版本化真源，供真正执行迁移的环境使用。

试用时间一律取数据库服务器 `CURRENT_TIMESTAMP`（UTC），不使用客户端时间或应用进程时钟，
因此改本地时间、重登、清 Cookie 都不能重置或延长。

## 四、权益计算规则

- 新开启的试用：5 小时，同一 `user_id` 主键唯一，全站一次，两个模块共享。已开启的试用保留原到期时间。
- 购买过（含已退款）的账号不再具备试用资格。
- 试用期内购买：付费时长从试用结束时刻起算。
- 有效期续费：在既有有效期之后顺延。
- 每笔已支付订单固化 `started_at` / `expires_at`；退款后按剩余已支付订单重算，
  后续订单前移填补空档。
- 到期立即失效：每次请求实时比对数据库时间，不做本地缓存。

并发：发放、退款、试用激活都在同一事务内先锁用户行（PostgreSQL `FOR UPDATE`），
再重算窗口，避免并发续费互相覆盖。

## 五、接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/viral-insights/membership` | 本人会员状态；未登录返回 `logged_out` |
| GET | `/api/viral-insights/packages` | 套餐列表（公开只读） |
| POST | `/api/viral-insights/trial/activate` | 激活试用，幂等 |
| POST | `/api/viral-insights/orders` | 创建会员订单，返回支付宝表单 |
| GET | `/api/viral-insights/orders/{out_trade_no}` | 仅本人订单状态 |

无权益访问受保护接口统一返回：

```json
{"detail": {"code": "INSIGHTS_MEMBERSHIP_REQUIRED", "reason": "membership_required"}}
```

HTTP 403，与积分不足的 402 严格区分。受保护接口：`GET /api/lowfans`、
`GET /api/lowfans/{art_id}`、`GET /api/image-board`、`GET /api/image-board/cover`、
`POST /api/lowfans/export`、`POST /api/lowfans/refresh`。

## 六、支付链路

复用既有支付宝基础设施：`_page_pay_form` 下单、`/api/pay/alipay/notify` 严格验签、
`/api/pay/alipay/orders/{no}/query` 主动查询、`reconcile_pending_orders` 对账、退款接口。

会员订单在验签通过后走 `apply_paid`，充值订单仍走 `_credit_recharge`：

- 异步通知重复投递：`apply_paid` 幂等，权益只发一次。
- 漏通知：主动查询 / 对账扫描到 `TRADE_SUCCESS` 后补发。
- 退款：`apply_refund` 撤销整单（金额无法切分权益），重复退款返回 `False` 不重复处理。

## 七、上线状态与顺序

### 前置条件核对（2026-11-04）

| 条件 | 状态 | 说明 |
| --- | --- | --- |
| 微小榜数据源商业授权/转售许可 | **已确认** | 已由产品方确认取得授权，解除“禁止开启”限制 |
| 支付宝商户与生产凭据 | **就绪** | 服务器已配置 `ALIPAY_APP_ID` / `ALIPAY_APP_PRIVATE_KEY` / `ALIPAY_ALIPAY_PUBLIC_KEY`，网关为生产 `openapi.alipay.com` |
| 会员价目与退款政策 | 由运营确认 | 服务端固定：周 9.9 / 月 29.9 / 年 199 |
| 真实支付链路验证 | 未验证 | 仍需一笔真实小额订单验证下单→通知→权益→退款 |

已知待加固项：服务器 `ALIPAY_SELLER_ID` 为空，`_seller_matches` 因此跳过卖家校验。
签名与金额校验仍然生效，但建议补上 seller_id 以增加一层防串单能力。

### 开启顺序

```bash
# 1. 部署包含会员功能的提交（见 DEPLOY.md）
# 2. 打开访问控制（先只做权限，观察一天）
VIRAL_INSIGHTS_PAYWALL_ENABLED=1
# 3. 观察：试用激活正常、预览裁剪生效、老用户登录不受影响、导出/刷新仍按积分
# 4. 如需图榜自动更新，再单独打开采集
IMAGE_BOARD_SYNC_ENABLED=1
```

注意：`VIRAL_INSIGHTS_PAYWALL_ENABLED=1` 同时控制**访问控制**与**销售入口**。
若想“只挡权限、暂不开卖”，当前版本需额外改代码；MVP 按需求以单一开关上线。

开关关闭时（默认）不展示入口、不销售、接口行为与旧版完全一致。

## 八、回滚

1. **只关会员（推荐，最快）**：`VIRAL_INSIGHTS_PAYWALL_ENABLED=0` 并重启 web/worker。
   立即恢复旧行为：榜单公开全量、导出/刷新仍按原积分计费、会员入口消失。
   已支付订单数据保留，不产生退款。
2. **回滚代码**：部署上一个提交。迁移 `20261104_0013` 的 `downgrade()` 故意不删表，
   试用与订单流水保留，可用于人工核对与后续补偿。
3. **定时同步**：如需停采集，`IMAGE_BOARD_SYNC_ENABLED=0` 并重启 beat。
   已同步快照继续只读展示，页面按 `freshness` 标记数据陈旧。

## 九、尚未验证（上线前必须补）

- 真实支付宝沙箱/生产环境的会员下单、通知、查询、退款全链路（本次仅用本地 RSA 模拟验签）。
- PostgreSQL 下的并发续费行锁（本次并发用例跑在 SQLite，未验证真实行锁竞争）。
- 浏览器端完整交互（本次只做服务端与脚本语法验证，未跑真实浏览器点击流程）。
- 微信图片域名白名单之外的新图源，封面代理会返回 502。
- 数据源授权与经营资质（非技术验证项，但属于开启收费的前置条件）。

## 十、2026-11-04 可用性修正

- 试用由用户主动开启；未开启不开始计时，也不扣费。预览状态禁用无法使用的筛选控件并说明原因，登录使用站内账号弹窗。
- 图榜默认展示已采集的全部数据，最多 200 条；定时采集以目标页数对应条数为完成条件，仍受每日尝试次数上限约束。上游不足、去重或失败时可能少于 200 条；较少的新快照不会覆盖较完整的旧快照。
- 图榜同时按采集时间和榜单日期提示旧数据；内容来源为资源库 book，含图文，不代表全部是低粉账号。只有匹配低粉榜时才显示倍率。
- 会员支付单和会员权益在同一个事务发放；对账补偿旧版留下的已支付未发放订单，退款对账会重放会员撤权。
- 本地模拟及浏览器试用流程不能代替真实支付宝生产订单和退款验收，真实支付链路仍需实际验证。
