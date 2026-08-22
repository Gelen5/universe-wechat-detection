# Universe WeChat Detection

公众号账号诊断的 FastAPI 可视化网页版本。

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

服务端环境变量：

```text
REDFOX_API_KEY=你的红狐 API Key
```

不要把真实 API Key 写进前端、Git 仓库或 `.env` 提交记录。

## 部署

可部署到任何支持 Python Web 服务的平台，启动命令：

```bash
uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

部署平台只需要配置 `REDFOX_API_KEY` 环境变量。

## API

### `GET /health`

健康检查。

### `POST /api/diagnose`

请求：

```json
{"account_name": "滚去睡"}
```

返回 `report_data.json` 的结构化数据，前端负责可视化展示。

## 数据边界

- 所有账号数据来自红狐数据接口。
- 查询不到账号时不会生成估算报告。
- 报告只作为运营参考，不代表微信官方结论。
- 当前测试版使用请求级临时目录，避免不同用户的报告文件互相覆盖。
- 报告页包含一句话判断、综合评分环、四维体检、账号画像、阅读走势、行业对标、作品证据和分级行动建议。
