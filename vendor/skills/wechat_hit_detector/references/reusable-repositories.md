# 可复用开源仓库审计

> 最近核验：2026-08-13
> 原则：先核对许可证，再判断代码质量和适用边界。星标数只反映关注度，不证明方法有效。

## 建议吸收

### imraywang/wewrite

- 仓库：https://github.com/imraywang/wewrite
- 核验时状态：MIT；2026-08-10 仍有推送；约 3,068 stars / 491 forks。
- 可吸收：五维编辑门槛、事实来源账本、修改前后差异、真实后台数据回写、重复反馈学习。
- 本 Skill 已采用的思想：阻断项不能被总分抵消、逐项事实声明账本、修改后逐项复核。
- 边界：当前实现为本仓库独立代码，没有复制其代码文件。

### partyfly/wechat-handbook

- 仓库：https://github.com/partyfly/wechat-handbook
- 可吸收：区分官方事实、合理推断和第三方经验。
- 本 Skill 已采用的思想：`official-rules-evidence.md` 的 A/B/C 证据等级。
- 边界：内容型资料，不把其中算法推断写成微信官方规则。

### cyberxiaowan/xiaowan-wechat-layout-skill

- 仓库：https://github.com/cyberxiaowan/xiaowan-wechat-layout-skill
- 核验时状态：AGPL-3.0-or-later；约 73 stars / 6 forks。
- 可吸收：移动端首屏信息预算、装饰预算、断行检查、配图证据表、反馈路由。
- 边界：只吸收方法，不复制实现；排版能力由专门的布局 Skill 负责，本检测器只输出内容和证据要求。

## 不建议复用为核心评分

### jiji262/wechat-publisher

- 仓库：https://github.com/jiji262/wechat-publisher
- 核验时状态：GitHub API 未返回标准许可证；约 204 stars / 51 forks。
- 问题：其 AI 味评分大量依赖句长波动、标点变化和结构“不完美”等弱信号，容易鼓励人为制造噪声。
- 结论：可以参考发布管线，但不复用其 AI 来源判断和硬发布阈值。

### yanwuyou/wechat-compliance-checker-skill

- 仓库：https://github.com/yanwuyou/wechat-compliance-checker-skill
- 核验时状态：未发现明确标准许可证；约 1 star。
- 问题：部分规则摘要缺少逐条官方出处，不能直接作为判罚依据。
- 结论：只保留为线索，所有进入检测器的规则必须重新回溯到官方或明确标为第三方经验。

## 可选基础能力

- `textlint/textlint`：可借鉴规则 ID、严重度和忽略机制；当前 Python 单文件规模不需要引入 JavaScript 运行时。
- `xmj-project/pycorrector`：可作为独立错别字模块候选；中文纠错可能误改专有名词，不应进入发布阻断层。
- `tw93/Waza`：可参考确定性的中文标点和空格检查，不作为内容质量分。
- `op7418/guizang-social-card-skill`：可参考 Playwright 渲染后检查溢出、字号和密度；适合后续移动端视觉验收。

## 复用判断标准

1. 有明确、兼容的许可证。
2. 解决的是事实、编辑或验证问题，而不是增加看似精确的分数。
3. 能通过失败样例和对照测试证明减少误报或提高建议可执行性。
4. 不把第三方经验包装成平台算法。
5. 不增加无法维护的运行时和依赖。
