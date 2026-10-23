# AI 书架

## 实现与边界

沿用 FastAPI 路由与原生 HTML/CSS/JavaScript；无新增依赖、数据库表、登录或积分规则。`/bookshelf` 为公开书架，`/bookshelf/{id}` 为可刷新、可分享的书籍详情。原工作台导航新增普通链接，不加入旧 SPA 的付费功能状态机。书架复用 tokens.css、notion-workspace.css 与产品导航，新增样式仅作用于 library-body。

采用官方阅读模式：不抓取或代理全文、不嵌入第三方 iframe、不推断章节目录。详情显示作者、仓库、许可与快照日期。所有阅读地址来自作者 README；3D 手册 README 指向 book/index.html，本轮另行核实对应作者 GitHub Pages 地址。2026-10-23 检查 11 个阅读入口均返回 HTTP 200；这是连通性证据，不保证第三方今后可用、无需登录或内容不变。原仓库作为备用入口始终保留。

### 来源与许可

逐一读取了 11 个 README、可用的中文 README、实际 LICENSE（若存在）和仓库文件清单。不能将底层软件的 MIT 许可当成教程许可。

| 书籍 | 教程许可/声明 | 本站模式 |
|---|---|---|
| Hermes Agent、Loop Engineering | 实际 LICENSE 为 MIT（API 仅识别 NOASSERTION） | 官方阅读 |
| DeepSeek Harness、Codex、Claude Code、3D 手册 | README 明确 CC BY-NC-SA 4.0 | 官方阅读 |
| Obsidian + Claude Code | 学习交流、引用署名声明；未发现独立 LICENSE | 官方阅读 |
| 源码解析、Harness Engineering、OpenClaw | 教育/研究用途声明；未发现独立 LICENSE | 官方阅读 |
| Agent Skills | 个人及教育使用，商业转载需授权 | 官方阅读 |

`docs/bookshelf-source-audit.json` 保存逐项来源、默认分支、README SHA-256、许可位置和链接检查结果。Star 前八本来自 GitHub REST；后三本在 API 超时后读取 GitHub 仓库页面内的精确 stargazerCount，未使用四舍五入展示数。API 限流或超时不解释为仓库不存在。

封面为本站原创 CSS 排版，不冒称官方封面，不使用产品商标图形。检查过 MIT 两本的官方封面预览，但所示是 6 月版、README 当前中文书已更新到 10 月版，因此没有拿旧版预览当新版封面。受限书籍封面也未转载；不使用外部字体或随机图片。

## 数据维护

编辑 `static/bookshelf-data.json` 即可增减书目。字段包括 id/title/subtitle/author/description/category/tags/cover/githubUrl/readUrl/stars/starsUpdatedAt/license/readingMode/featured；首版 readingMode 必须为 official。`chapters` 留空不添加，不能凭空编造。新增书需人工核实来源、许可、作者与阅读地址。

离线 Star 快照按数量降序展示，页面不请求 GitHub。维护者可执行：

```powershell
python scripts/sync_bookshelf.py
# 明确需要在24小时缓存期内刷新时：
python scripts/sync_bookshelf.py --force
```

脚本仅访问 GitHub 仓库元数据，可在环境变量设置 GITHUB_TOKEN；任何一本失败均保留全部旧快照，不用零覆盖。脚本不判断或修改许可、不获取正文。更新后审查 JSON 并随代码部署，无需单独后端服务或定时任务。

收藏仅保存在当前浏览器 localStorage。记录最近阅读链接但不声称知道用户在第三方网站的阅读进度；跨域无法得知阅读进度，未伪造百分比。

## 开发与验证

在项目已有 Python 环境中运行，无需前端打包或 TypeScript 编译：

```powershell
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/bookshelf
node --check static/bookshelf.js
python -m pytest tests/test_bookshelf.py tests/test_bookshelf_browser.py -q
python -m pytest tests -q
git diff --check
```

浏览器测试沿用现有项目 Playwright 与本机 Chrome 路径；不访问付费 API。覆盖分类、搜索/空状态、Star 排序、详情和来源、收藏持久化、直接刷新、响应式列数、移动端菜单、加载失败重试。服务端检查公开页面、未知书籍 404、旧 API 仍受鉴权保护。

布局：390px 两列、768px 三列、1280px 四列、1440px 五列；详情手机居中、桌面双栏。封面固定比例避免跳动，200ms 悬停，reduced-motion、键盘焦点、真实链接和 44px 主要触控区域。

## 部署

沿用现有 Docker/FastAPI/Nginx，新增路由由通用反向代理承接；没有迁移、密钥或卷变更。只需更新代码并构建 Web。不要清空数据库、output 或 Docker 卷。

先核对线上 SHA 与 Git 工作区；若主分支还含未上线的其他功能，不应为上书架而把其他改动一并上线。可基于线上 SHA 应用本次独立提交，再复验原导航与写作入口。

验证 `/bookshelf`、11 本书及直接详情路径、`/static/bookshelf-data.json`、`/workbench`、`/qihaoshou` 和 `/health/ready`；用浏览器从旧导航真实进入新页面。页面 200 不能代替搜索与交互验收。
