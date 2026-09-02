# Universe Creator Studio

面向中文内容创作者的 FastAPI 工作台。当前页面把公众号账号诊断、公众号创作、小红书创作、微信贴图号、爆文检测和早安祝福放在同一个操作入口中。

当前版本先实现免费测试闭环，并提供一份面向客户的可视化报告：

```text
输入公众号名称 → 服务端调用红狐 API → 提取证据与洞察 → 网页可视化展示
```

支付、用户账号、历史报告和订阅功能暂未接入，但 `db/schema.sql` 已预留订单与报告字段。

## 项目结构

```text
server/
  main.py                 FastAPI 入口
  wechat_analyzer.py      内置公众号诊断核心代码
static/
  index.html              页面结构
  style.css               Apple 式浅色信息产品视觉
  app.js                  报告渲染、指标解释与建议卡片
  morning-blessing.html   早安祝福生成器
server/
  creator_tools.py        小红书、贴图号和爆文检测 Web 适配层
vendor/skills/            固定版本的三个开源 Skill 运行时
db/schema.sql             后续订单/报告数据库结构
references/               Skill 工作流文档
assets/                   原 Skill 报告资源
```

## 本地启动

Python 3.10+：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:REDFOX_API_KEY = "ak_xxx"
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000
```

浏览器打开：<http://127.0.0.1:8000>

## 测试

完整测试环境包含 FastAPI `TestClient` 所需的 `httpx2`：

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
$env:PYTHONPATH = (Resolve-Path vendor\skills\wechat_tie_tu).Path
python -m unittest discover -s vendor\skills\wechat_tie_tu\tests -v
Remove-Item Env:PYTHONPATH
python -m unittest discover -s vendor\skills\wechat_hit_detector\tests -v
```

服务端环境变量：

```text
REDFOX_API_KEY=你的红狐 API Key
WECHAT_TEXT_API_KEY=可选的服务端文字模型 Key
WECHAT_IMAGE_API_KEY=可选的服务端图片模型 Key
CREATOR_OWNER_EMAIL=gelen5@163.com
CREATOR_ADMIN_PASSWORD=首位管理员初始密码
CREATOR_COOKIE_SECURE=1
CREATOR_NEW_USER_TRIAL_POINTS=30
```

文字和图片 API Key 只由服务器环境变量托管，浏览器不再保存或传递生产密钥。公开部署应使用 HTTPS，并设置 `CREATOR_COOKIE_SECURE=1`。新注册账号默认获得一份试用积分，可通过 `CREATOR_NEW_USER_TRIAL_POINTS` 调整，设置为 `0` 可关闭注册赠送。`CREATOR_OWNER_EMAIL` 是唯一允许执行管理员操作的邮箱；系统启动时会把其他邮箱全部校正为普通用户。可以让所有者直接注册，也可以通过 `CREATOR_ADMIN_PASSWORD` 在首次启动时预创建所有者账号。

### 账号与积分

- 用户注册后获得统一积分钱包，所有创作模块共享余额。
- 管理员可以给指定账号充值试用、赠送或付费积分，并必须填写备注。
- 收费请求在执行前预扣积分，成功后结算，失败自动退还。
- `point_transactions` 是积分账本，`usage_records` 保存功能、耗时、状态和成本字段。
- 基础锚点为 `1 积分 = 0.1 元`，积分只用于平台功能，不可提现或转账。
- 运行数据库默认位于 `data/creator_accounts.db`，可用 `CREATOR_ACCOUNTS_DB` 指定持久化路径。

## 部署

可部署到任何支持 Python Web 服务的平台，启动命令：

```bash
uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

账号诊断使用 `REDFOX_API_KEY`。创作工具统一使用服务器环境变量中的文字与图片模型配置。

## API

### `GET /health`

健康检查。

### `POST /api/diagnose`

请求：

```json
{"account_name": "滚去睡"}
```

返回 `report_data.json` 的结构化数据，前端负责可视化展示。

### 创作工具接口

- `POST /api/providers/test`：分别验证文字和图片供应商。
- `POST /api/xiaohongshu/package`：生成小红书完整内容包。
- `POST /api/tie-tu/plan`：生成微信贴图号卡片计划。
- `POST /api/creator-tools/image`：根据已确认卡片逐张生图。
- `POST /api/hit-detector/analyze`：执行公众号发布前编辑复核。
- `POST /api/hit-detector/rewrite`：按复核结果进行最小必要改稿。

除注册、登录和健康检查外，所有 `/api/` 接口都需要有效登录会话。账号与运营接口包括：

- `POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/logout`
- `GET /api/auth/me`、`GET /api/wallet`、`GET /api/pricing`
- `GET /api/admin/users`、`GET /api/admin/overview`、`POST /api/admin/recharge`

火星 API 的 OpenAI 兼容 Base URL 应为 `https://huoxingapi.com/v1`，模型 ID 必须从该账号当前模型广场复制。HTTP 403 通常表示 Key 分组不允许访问所选模型；HTTP 401 表示凭据未通过鉴权。

## 数据边界

- 所有账号数据来自红狐数据接口。
- 查询不到账号时不会生成估算报告。
- 报告只作为运营参考，不代表微信官方结论。
- 当前测试版使用请求级临时目录，避免不同用户的报告文件互相覆盖。
- 报告页包含一句话判断、综合评分环、四维体检、账号画像、阅读走势、行业对标、作品证据和分级行动建议。
