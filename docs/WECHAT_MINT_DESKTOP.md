# 公众号创作：薄荷绿桌面 UI

基线：2026-10-25 获取的 GitHub main / af0620b。用户指定尽可能贴近参考图，只实现公众号创作桌面端。

## 实现

- static/wechat-mint.css：薄荷绿环境背景、浅绿奶白面板、白色高光边缘、柔和投影、绿色品牌块、圆角选中项、白色助手气泡与绿色用户气泡。
- static/wechat-mint.js：仅在公众号工作区可见且视口大于 1100px 时设置 mint-wechat 类；离开模块立即恢复原主题。步骤底部进度条读取现有状态文字，不生成假的完成状态。
- static/index.html：在现有主题之后引入两份新文件。
- 空态直接呈现真实对话区与输入框，Folio 原引导页在该桌面主题下隐藏；Folio 文档阅读/编辑逻辑保留。
- 左侧全站导航在公众号模块中采用参考图的材质。右侧沿用真实文章产物、版本、编辑、复制、下载和排版预览。
- 既有 DOM ID、顺序、事件、接口、模型调用、计费和数据表没有变更。不新增依赖，不重构其他模块。
- 移动端不启用新主题。本次没有设计手机界面，仅检查新样式在窄屏不产生影响。

历史样式存在多层 !important，本次通过独立主题选择器和局部变量明确优先级，未删除或覆盖其他主题源文件。回退只需取消这两个资源的引入，不涉及数据回滚。

## 验证

```powershell
node --check static/wechat-mint.js
git diff --check
python -m pytest tests/test_wechat_mint_browser.py tests/test_ui_shell_browser.py tests/test_workbench_chat_chain_browser.py tests/test_workbench_failure_browser.py tests/test_workbench_stages_browser.py -q
python -m pytest tests -q
```

新增桌面验证覆盖 1101、1280、1440、1920px：侧栏/对话/输出互不遮挡，输入框位于面板内，无横向溢出，历史对话可打开，切换模块恢复主题。更新旧布局断言以符合新的双栏桌面；书架数量断言从固定 11 改为实际数据量，兼容基线已增加到 21 本的变更。

浏览器预览截图输出到 output/mint-ui/（不入库）。对话示例截图使用本地 fixture 文本展示真实组件，不代表完成真实付费写作；不会将示例内容或参考图中的统计数字写入用户会话。

## 发布

按 DEPLOY.md 使用 /opt/universe-deploy/deploy.sh 指定提交部署，保留旧版本作为回滚点。不得在旧 release 目录直接构建，以免回退其他模块。发布后检查 ready、实际提供的 CSS/JS 字节、登录边界及桌面浏览器渲染。


## 2026-10-25 本次验收结果

- 桌面主题、全站导航、五步创作链路、失败重试、产物与历史专项：29 passed。
- 最终全量回归：348 passed、33 subtests passed；1 项既有 Starlette/httpx 弃用提示。
- node --check static/wechat-mint.js、git diff --check 通过。
- 1600×1000、1440×1000 已进行截图复核，1101/1280/1440/1920px 均验证无横向溢出、无面板重叠。
- 截图：output/mint-ui/desktop-empty.png、desktop-conversation.png、desktop-writing.png、desktop-1440.png。对话/写作截图使用明确的本地测试数据；生产不会预填这些内容。


## 2026-10-25 宽屏与积分栏修正

用户截图指出步骤栏高度不兼容、积分重复及侧栏底部纵向排列。

- 步骤栏移除继承的固定高度，明确最小高度与边框盒模型；五个步骤及进度线完整处于标题面板边界内。
- 隐藏公众号页头的重复积分，仅保留侧栏余额。
- 侧栏底部改为积分卡与44px齿轮设置按钮同一行。新按钮复用原头像触发器和原设置菜单，支持键盘Enter开启、Escape关闭并返回焦点。
- 菜单向上展开，右侧锚定，避免越出侧栏或视口；退出公众号模块后恢复原头像入口。
- 消除工作区旧最小高度造成的空态整页多余滚动。
- 1280/1440/1920/2560宽度回归，包含99,859积分显示；34项相关浏览器测试通过，JS语法及diff检查通过。此轮没有重复运行后端全量套件。
- 资源版本更新为mint-2，避免旧缓存。
