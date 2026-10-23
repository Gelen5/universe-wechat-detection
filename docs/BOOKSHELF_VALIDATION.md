# AI 书架验证记录

日期：2026-10-23（Asia/Shanghai）。

## 发布基线

线上基线 0eb9838。为避免夹带尚未上线的主分支更新，在同一 Git 仓库建立 release/ai-bookshelf 分支，仅加入书架模块；既有业务代码仅 main.py 两行注册路由、index.html 一条导航、notion-workspace.js 五行导航分组。数据库、鉴权规则、钱包、写作及 Worker 逻辑均未改动。

## 本地结果

- 生产基线加书架的完整 `pytest tests -q`：258 passed，12 subtests passed。1 项既有 Starlette/httpx 弃用提示。
- 将 WorkBuddy 主入口替换为公开 PDF 后，再跑书架路由与浏览器专项：4 passed。
- `node --check static/bookshelf.js`、`git diff --check` 通过。项目为原生 JS，无 TypeScript 构建步骤，无新增依赖。
- 实际启动 FastAPI，在浏览器查看桌面书架、手机书架和详情页；390px 无横向溢出，封面英文长词无溢出。
- Playwright 测试检查 390/768/1280/1440px 对应 2/3/4/5 列，分类、搜索、空结果、排序、收藏持久化、直接刷新、菜单键盘关闭、网络错误重试。
- 来源、Star 快照、许可证和阅读地址逐项记录于 bookshelf-source-audit.json。七个主入口 HTTP HEAD=200，其余四本的 PDF 原文件 HEAD=200；3D 网页包含在前七个中。GitHub blob 页的四次 TLS 超时保留在审计记录，未当成书籍失效。
- WorkBuddy 实际浏览器打开会要求登录，故只作为明确标注需登录的次要入口。

## 与最新主分支的区别

另在 eb0276b 上验证同一功能增量：281 passed、12 subtests passed，但有两个基线问题，未混入书架发布修复：

1. test_frontend_has_account_wallet_and_six_tabs 仍断言 7 个 data-view，而 eb0276b 原文件已经有 8 个；本次书架链接不使用 data-view，因此没有增加该数量。
2. test_missing_settings_still_produce_a_usable_url 在全套运行受到其他测试遗留的 WECHAT_TEXT_API_BASE_URL 影响；该测试单独运行通过。其 patch.dict(clear=False) 未隔离所有配置环境变量。

发布使用已全套通过的生产基线，不以最新主分支的部分通过结果替代发布验收。

## 人工证据边界

没有付费模型调用、教程镜像、爬取受限正文或微信发布测试。本任务不改变这些能力。外站暂时可用不保证将来稳定；用户始终能从详情中的原始 GitHub 地址找到作者最新入口。


## 线上验收

生产发布提交：4206748（以 0eb9838 为基线的书架独立增量）。只重建 Web，未执行数据库迁移或清空卷。Docker 构建通过。

- /bookshelf、/bookshelf/codex、/workbench、/qihaoshou 均返回 200。
- /health/ready 返回 ready，database=true、redis=true；Web、Worker、PostgreSQL、Redis healthy。
- 实际 HTTPS 浏览器检查：11 本书、知识管理分类、Codex 搜索、详情许可、公开 PDF 地址、直接刷新、手机菜单通过；无 JS pageerror；390px 无横向溢出。
- 现有工作台未登录弹窗仍覆盖原导航；验证沿用真实 AI 书架链接地址跳转，没有登录、创建用户或调用受保护/付费接口。新书架本身无登录弹窗。
- 线上截图保存在 release worktree 的 output/bookshelf-qa/：desktop.png、mobile.png、detail-desktop.png、detail-mobile.png（不入库）。
- 主分支开发期间新增了 6a58409，已保留并合并书架代码，不覆盖该更新。生产未夹带该选题功能更新。

## 修改文件清单

- server/main.py、server/bookshelf.py：注册公开书架与详情路由，未知书籍 404、详情 SEO。
- static/index.html、static/notion-workspace.js：现有导航新增书架链接及分组。
- static/bookshelf.html、static/bookshelf.css、static/bookshelf.js：独立界面、响应式、搜索分类排序、详情和本地收藏。
- static/bookshelf-data.json：11 本书目及 Star 快照。
- scripts/sync_bookshelf.py：带 24 小时缓存的维护者 Star 更新命令。
- tests/test_bookshelf.py、tests/test_bookshelf_browser.py：公开路由、数据边界及浏览器回归。
- README.md、docs/AI_BOOKSHELF.md、docs/bookshelf-source-audit.json、docs/BOOKSHELF_VALIDATION.md：入口、维护说明、来源证据和验证记录。
