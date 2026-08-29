# 证据与数据边界

## 证据等级

- A：用户提供的自有账号后台或导出数据。
- B：有正文或详情的公开笔记、浏览器保存页或适配器记录。
- C：只有公开主页卡片、标题或可见点赞等元数据。
- 推断：根据已记录证据提出的待验证判断。
- 未知：没有数据，保留为待补充信息。

## 小红书采集

优先使用 Chrome 登录态和可验证的 Agent-Reach/OpenCLI 适配器。先运行 `agent-reach doctor --json`，再分别验证搜索、单条详情、作者后台和深度指标。OpenCLI 详情通常需要完整 signed URL；只有 note ID 不足时，不要无限重试。

公开样本只能支持主题、标题、结构和趋势判断，不能支持自有账号的播放、收藏、涨粉、私信、成交或收入归因。

## 持久化字段

自有内容至少记录：`content_id`、`platform`、`title`、`body`/`script`、`published_at`、`metrics`、`comments`、`conversions`、`review_status` 和 `lessons`。

小红书复盘节点固定为 `2h`、`24h`、`48h`、`7d`。缺少发布时间就不能生成可靠到期提醒。
