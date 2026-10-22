# 起号兽写作工作台：部署与验收

## 页面和实现

首页新增“起号兽写作”菜单，直接访问 `/qihaoshou`。此页使用站内登录 Cookie、管理员模型设置、积分账本和数据库；不调用 qihaoshou.com 私有接口，不需要起号兽账号。

- `server/qihaoshou.py`：会话、真实模型 SSE、排版、标题、表达优化、配图、素材权限和微信草稿。
- `static/qihaoshou.*`：响应式三栏页面、编辑工具栏、流式客户端、复制与导出。
- `/api/qihaoshou/generate`：真实转发模型流，不把一次性响应切成假 token。生成完成并确认模型正常结束后，才替换数据库内原稿。
- 原稿与历史会话保存于现有 `workbench_sessions`，使用 `writer_` ID 前缀和 `kind=qihaoshou` 区分；没有新增必需数据库迁移。
- 图片存放于 `output/qihaoshou/<会话ID>`，沿用现有 output 持久化挂载。图片读取校验登录用户和会话归属。

## 配置

1. 管理员在现有后台配置文字、图片 API Key、Base URL 和模型。文字模型支持 OpenAI-compatible `/v1/chat/completions` SSE（`finish_reason=stop`）；沿用现有供应商配置约定，Base URL以 `/responses` 结尾时，切换为 Responses API SSE（`response.output_text.delta` / `response.completed`），并以low推理档位执行。配置只在服务端读取。
2. 缺少模型时，对应按钮显示不可用，不返回样例假装生成成功。已有设置中出现“已配置”仅说明存在配置，并非健康探测结论。
3. 公众号草稿箱使用服务器环境变量：

```dotenv
WECHAT_APPID=公众号AppID
WECHAT_SECRET=公众号AppSecret
# 也兼容现有 WECHAT_APP_ID / WECHAT_APP_SECRET 名称
```

4. 服务器公网出口IP需要加入公众号后台白名单，公众号需具备素材/草稿权限。该部署目前使用服务器级共享公众号凭证，因此**仅站点所有者管理员可以同步**；普通用户仍可写作、排版、导出。多用户各自绑定公众号不在本次实现中。
5. 模型供应商若启用IP白名单，也需放行服务器出口IP和所选模型的权限。曾经出现过的供应商问题不代表当前已修复，需部署后实测。
6. 正式页面使用 HTTPS，带格式剪贴板依赖浏览器权限。普通文字和格式可以复制；本地受保护配图不保证在公众号后台直接粘贴成功。完整图文建议使用草稿同步；HTML导出会将自有配图内嵌，避免文件离开站点后图片地址失效。

## 积分与任务

新安装规则在应用初始化时插入，已有规则不覆盖管理员修改：

| 动作 | 默认积分 |
|---|---:|
| 生成文章 | 10 |
| 候选标题 | 3 |
| 表达优化 | 5 |
| 生成一张配图 | 30 |
| 保存、排版、导出、复制、同步草稿 | 0 |

生成流自己保留/结算积分，避免“HTTP 200已发送但后面生成失败”仍扣费。失败和客户端中止都会退款；进程重启时通过现有 workbench_jobs 恢复机制处理未完成记录。相同生成 request_id 不重复执行。成功生成但客户端未收到最后事件时，应重新加载最近草稿查看结果，不盲目重新提交。

生成同进程最多4个同时进行，超过时失败并退款；同一会话的生成、编辑、排版和扩展使用数据库租约互斥，revision 防止旧窗口覆盖新稿。

## 部署

使用项目现有 PostgreSQL/Redis/Worker 部署流程，保留原数据库和 output 挂载。无需重建数据卷。

1. 拉取本次代码，正常安装 `requirements.txt`（没有引入新的运行依赖）。
2. 确认 output 卷持久化；配置或复用现有模型与公众号环境变量。
3. 正常重建并重启 Web 服务，使用项目原有迁移/发布步骤。不要用清空卷的命令。
4. Nginx 应对 `/api/qihaoshou/generate` 关闭代理缓冲、缓存和 gzip，并给足读取超时。仓库 `deploy/nginx-universe-wechat-detection.conf` 已加入示例 location；已有线上HTTPS配置请合并该 location，不要直接覆盖证书和域名配置。
5. 检查 `/health/ready`、首页菜单、`/qihaoshou` 和下面的真实链路。

## 上线验收

- 登录后写一篇虚构测试主题，确认 token 在完成前逐步出现；随后刷新草稿，标题和正文仍存在。
- 切换主题、编辑/加粗文字、保存、复制到编辑器、导出HTML，检查移动端不横向溢出。
- 配图生成成功才出现图片；重新加载后图片仍可访问，其他账号无法读取。
- 测试标题与表达优化；表达优化的规则检查涵盖数字、段落顺序、标题和改动比例，**不是完整语义等价证明，也不保证任何AIGC检测结果**。未通过则保留原稿并退款。
- 停止一次尚未完成的生成，检查旧稿保留和余额恢复；极靠近完成时中止可能文章已经保存，应重新加载查看。
- 仅管理员点击并确认同步，微信返回 `media_id` 才显示“已写入草稿箱”，不会群发。网络结果不确定时先核对公众号后台，避免人工重试造成重复草稿。
- 公号配置缺失、权限不足、模型401/403、超时、积分不足都应看到明确失败信息；配置未完成不能作为完整可用验收通过。

## 自动验证

```powershell
python -m unittest tests.test_qihaoshou -v
python -m unittest discover -s tests -p "test_*.py"
```

浏览器测试（使用独立临时数据库和本地HTTP模型fixture；不会连接真实模型或微信）：

```powershell
# 窗口1：项目虚拟环境
python scripts/qihaoshou_browser_fixture.py
# 窗口2：安装了 playwright 和 Microsoft Edge 的测试Python
python scripts/qihaoshou_browser_check.py
```

脚本默认端口8894（Web）与8895（模型fixture）。浏览器脚本当前选择Windows的 `msedge` channel；其他系统可改为本机已安装的Chromium channel。图片/微信fixture仅用于测试，**部署时不要运行该fixture脚本**。截图和导出结果位于 `output/qihaoshou-qa/`，不入库。

本次验证记录：基于最新主分支的228项回归测试通过；22项写作/供应商定向测试通过；浏览器实测登录、真实HTTP SSE传输、主题、标题、表达优化、配图、剪贴板、HTML内嵌导出、模拟微信成功响应、历史恢复、生成中止退款与手机宽度布局。模型和微信上游是测试fixture，真实供应商和真实草稿箱仍须上线配置后验收。本次按用户要求只推送代码，不操作线上部署。
