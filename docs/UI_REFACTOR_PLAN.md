# UI Refactor Plan

## Phase 1 — Audit

已完成代码、Route、Tab、全局浮层、API、已有回归脚本与线上首页基线扫描；结论见 `UI_UX_AUDIT.md`。

## Phase 2 — App Shell

统一全局 token、字体、导航 active/focus、内容容器、浮层关闭和焦点管理；保留现有 URL 与 API。

## Phase 3 — Core Components

抽取 Button、IconButton、Input、Textarea、Select、Tabs、Panel、Modal、Toast、Loading、Empty、Error、Success 的统一状态；清理重复 CSS 覆盖。

## Phase 4 — Primary workflow

优先重构 `/workbench`：输入主题 → 选题 10 条 → 选择后生成框架 → 编辑正文 → 反 AI → 配图方案 → 排版预览 → 草稿写入。每一步只保留一个主动作，详情进入折叠面板。

## Phase 5 — Tool pages

按任务重构 `/diagnose`、`/hit-detector`、`/xiaohongshu`、`/tie-tu`、`/morning-generator`，不改变后端业务语义；工具页表单统一 label、帮助文案、校验、加载和错误反馈。

## Phase 6 — Responsive / Accessibility

在 375、390、768、1024、1280、1440 检查溢出、焦点、键盘、固定元素、图片尺寸、长文本和 reduced motion。

## Phase 7 — Final audit

用 Impeccable 复审信息层级和视觉噪声；用 Web Design Guidelines 逐文件输出 `file:line` 问题并修复；再执行已有 API、浏览器回归和真实线上冒烟测试。

