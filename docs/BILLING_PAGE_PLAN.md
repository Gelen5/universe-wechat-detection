# 账单页（/bill）策划 · 2026-10-31

## 1. 定位与入口

- 新增独立服务端渲染页 `/bill`，与 `/wallet`、`/pricing` 同级（`routes.js` 里标 `page: true`，不当 SPA view，避免白屏）。
- 入口放在「账号菜单」里「我的积分」下面一项：
  - `static/index.html` 的 `#settings-popover`：在 `#wallet-settings-button` 之后插入 `<button id="bill-button"><i data-lucide="receipt-text"></i>账单</button>`；
  - `static/sidebar.js` 里硬编码的弹出菜单同步补一项（该文件菜单文案是 `设置 / 我的积分` 两项，需一起改）；
  - `static/app.js` 里 `walletSettingsButton` 同款跳转逻辑复制一份为 `billSettingsButton → window.location.href = '/bill'`。
- 页面不新增侧边栏分组（「账户」组里已有「积分套餐」，账单属于账户菜单内的二级页，不占一级导航位置）。

## 2. 视觉与结构

沿用 `/wallet` 的既有语言：`max-width:880px` 单列、`wx-hero` 卡片、`wx-tabs` 胶囊筛选、`wx-row` 三栏行（图标 36px / 主副文案 / 右侧金额等宽数字）、`wx-day` 日期分组、`#0F5132` 主色、`font-variant-numeric: tabular-nums`。390px 下保持单列、无横向滚动。

页面自上而下：

1. 头部：`← 返回工作台` + 右侧「充值积分」CTA（跳 `/pricing`）。
2. 概览卡（4 个数字，一行、窄屏两行）：
   - 当前积分余额（+ 折合 ¥ 面值）
   - 本月支出（¥，充值实付 + 消费折价分开标注）
   - 累计充值（¥ / 笔数）
   - 累计获得积分（充值+赠送+试用，分桶）
3. 收益卡（见第 3 节，数据未就绪时降级为空态说明）。
4. 筛选条：类型（全部/充值/退款/消费/收益）+ 时间（本月/上月/近 30 天/近 90 天/自定义）+ 状态（全部/待支付/已支付/已关闭/已退款）+ 导出按钮。
5. 明细列表：按日分组，行内展开详情。

## 3. 收益模块（需要产品定义，先按两套口径设计）

现状事实：库里不存在任何收益类数据。`point_transactions` 只有积分进出，`alipay_*` 只有用户付款。所以收益区必须分两步走。

### 口径 A（推荐先做）· 站长视角：网站收入
- 数据：`alipay_recharges.status='CREDITED'` 的 `amount` 求和，按自然月/日聚合；退款从 `alipay_orders.refunded_amount` 扣减。
- 展示：本月收入、累计收入、待入账（PENDING 且订单 PAID）、退款冲减、净收入；下方按月表格（月份 / 笔数 / 金额 / 退款 / 净额 / 环比）。
- 权限：仅 `role=admin` 且 `email=OWNER_EMAIL`（与 `wallet_page.py` 里 `is_owner` 判定一致）可见，普通用户不渲染这一块。
- 数据现成，零新表，可以先上线。

### 口径 B（需新表）· 创作者视角：我赚到的钱
若要把「收益」做成用户可提现的创作分成（AI 超市技能售卖、代写接单、邀请返佣），需要新增：

```sql
CREATE TABLE earnings_ledger (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source TEXT NOT NULL,          -- market_sale | referral | order_share | manual
  source_ref TEXT,               -- 关联订单/技能/邀请码
  title TEXT NOT NULL,           -- 展示文案，如「AI 超市 · 选题助手 售出」
  amount_cents INTEGER NOT NULL, -- 正=赚到，负=冲正/退款
  status TEXT NOT NULL,          -- pending | settled | withdrawable | withdrawn | clawed_back
  settle_at TEXT,                -- 预计可提现时间（T+7 之类）
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE withdrawals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount_cents INTEGER NOT NULL,
  channel TEXT NOT NULL,         -- alipay | wechat
  account TEXT NOT NULL,         -- 脱敏后的收款账号
  status TEXT NOT NULL,          -- applied | processing | paid | failed
  out_biz_no TEXT,               -- 支付宝转账单号
  created_at TEXT NOT NULL,
  paid_at TEXT
);
```

- 收益区展示：待结算 / 可提现 / 已提现 三个数字 + 提现按钮（最低 ¥10、整数元、审核后 T+1 到账）+ 明细列表（时间、来源、标题、订单号、状态徽标、金额）。
- 提现走支付宝单笔转账，复用 `server/alipay_pay.py` 的 client 与签名封装，独立成 `server/withdrawals.py`。
- 上线前置：结算规则、分成比例、税务与提现风控都要先定，不建议和账单页第一版一起发。

## 4. 充值记录（数据现成）

数据源：`alipay_recharges` ⟕ `alipay_orders`（`out_trade_no` 关联）。每行：

- 主文案：套餐名（`package_id` → 入门/进阶/专业，未知则显示「自定义金额」）
- 副文案：`下单 2026-10-31 13:42 · 已支付 13:43 · 1000 积分`，订单号 `out_trade_no` 可点击复制（复用 `wx-copy` 的 `navigator.clipboard` 写法）
- 金额：`-¥98.00`
- 状态徽标（文案+颜色双通道，不靠颜色单独表意）：
  - `CREATED`/`PENDING_PAYMENT` → 待支付（灰）
  - `PAID` + `alipay_recharges.status='CREDITED'` → 已到账（绿）
  - `PAID` 但未 `CREDITED` → 已支付待入账（橙，附「刷新状态」按钮，触发 `POST /api/pay/alipay/orders/{no}/query`）
  - `CLOSED` → 已关闭（灰）
  - `REFUNDED` → 已退款（蓝）；`PARTIAL_REFUNDED` → 部分退款 ¥X（蓝）
- 展开详情：支付方式（支付宝网页支付）、支付宝交易号 `trade_no`（中间脱敏 `2026****8801`）、积分入账时间 `credited_at`、退款金额。

## 5. 消费明细（数据现成）

数据源：`point_transactions where kind='consume'`。每行：

- 主文案：`feature`（如「公众号完整工作流」），缺失回落到 `note`
- 副文案：时间 + 扣减桶（付费/赠送/试用，按 `allocation_json` 展示实际扣的是哪个桶）
- 金额：`-30 积分`
- 展开：`request_id`、对应 `usage_records` 的 `provider/model`、`duration_ms`、最终状态（预留/已结算）。
- 追加「按功能汇总」小表（功能 / 次数 / 积分），让用户看清钱花在哪。

## 6. 退款记录

数据源：`point_transactions kind='refund'` + `alipay_orders.refunded_amount > 0`。展示退款金额、原订单号、退款时间、冲正积分。文案统一为「退款冲正」，不要和「退款到账」混淆（积分回滚 ≠ 现金退回）。

## 7. 导出

`GET /api/bill/export.csv?from=&to=&type=`，服务端生成 CSV（UTF-8 BOM，Excel 直接可开），列：时间、类型、说明、订单号、积分变动、金额（¥）、状态。前端用普通 `<a download>`，不额外上 JS 库。

## 8. 交互与状态

- 筛选与当前 tab 写进 `sessionStorage`（沿用 `wx-filter` 惯例，键名 `bill-filter` / `bill-range` / `bill-status`），刷新后保持。
- 服务端一次读齐数据内嵌 JSON（与 `/wallet` 一致），首屏不发额外请求；「刷新状态」这类动作才走接口。
- 空态三分支：未登录（401 页，沿用 `_login_required_page`）、无任何记录（引导去 `/pricing`）、筛完为空（提示换筛选）。
- 金额与积分永远成对出现（`-¥98.00 / +1000 积分`），避免用户混淆「积分」与「钱」。

## 9. 不做的事

- 账单页不发起任何扣款或充值，只读。
- 不改动 `accounts.reserve_points` / 扣费顺序（paid → bonus → trial）。
- 不在账单页展示完整支付宝交易号、不在前端拼 SQL 口径的“结余”，余额一律取 `wallets` 表。
- 第一版不碰提现与分成（口径 B），先只发口径 A + 明细，避免把财务规则和 UI 一起压上线。

## 10. 实施顺序

1. `server/bill_page.py`（照 `wallet_page.py` 结构：`_STYLE` / `_page()` / `router.get('/bill')`），先只做概览 + 充值 + 消费 + 退款四个块。
2. 入口三处改动（`index.html` / `sidebar.js` / `app.js`）。
3. `GET /api/bill/export.csv` + 测试。
4. 管理员收入块（口径 A）。
5. 收益表 + 提现（口径 B，单独排期）。

## 11. 验收清单

- `tests/test_nav_single_source.py` 仍通过（`/bill` 为 `page: true`，不进 `shellRoutes` 的 view 映射）。
- 新增 `tests/test_bill_page.py`：未登录 401、有数据渲染行数、状态徽标文案、CSV 列头与 BOM。
- 桌面 1440 / 平板 768 / 手机 390 三档截图，`/bill` 无横向滚动，行高 ≥44px 可点。
- 与 `/wallet` 的「充值 / 消费 / 退款」口径交叉核对：同一账号同月，两页金额必须一致（同一个 SQL 来源，不允许各算一套）。
