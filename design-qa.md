# Design QA

Viewport: 1440x1024
Reference: selected Apple-minimal UI direction and existing mobile product screens.

## Verification evidence

- 首屏保留公众号诊断入口，并新增“公众号诊断 / 内容工作台”产品级 Tab。
- 工作台首屏明确说明用途、输入方式、三种模式和 8 步流程。
- 交互模式 API 返回 10 个选题候选；点击候选后返回框架和可编辑文章区。
- 全自动模式完成到第 8 步，生成可编辑文章、反 AI 评分和 Skill 原生预览文件。
- 单步模式可从指定步骤继续；浏览器检查了输入、Tab、选题点击和主按钮交互。
- 浏览器错误检查无页面脚本错误；`/health` 返回 `status: ok`。

## Final result: passed

Remaining follow-up: 接入真实宿主模型后，可将当前无模型时的可编辑降级初稿替换为模型生成；微信草稿箱发布仍需配置 `WECHAT_APPID` 与 `WECHAT_SECRET` 并经过显式确认。

---

## Creator Studio redesign - 2026-08-30

Viewports: 1440x980 and 390x844.
Reference: user-provided API settings screenshot plus the requested Apple/App Store operational style.

### Verification evidence

- Six tools are visible as stable sidebar tabs on desktop and a fixed bottom navigation on mobile.
- The unified settings dialog keeps text and image providers separate, removes hidden enable switches, shows saved state, and provides an explicit connection test for each provider.
- The shared request payload includes both saved keys without depending on a checkbox; account diagnosis remains isolated from these credentials.
- Xiaohongshu renders a six-card content package; Tie-Tu renders card planning and batch-image controls; the hit detector renders the vendored Skill's editorial gate and findings.
- Image calls now accept direct image payloads and asynchronous task URLs.
- Desktop and mobile screenshots have no horizontal overflow, the console has no page errors, and the settings modal remains usable at 390x844.
- Side-by-side settings comparison was inspected in `qa-settings-comparison.png`; the new layout preserves every required field while making the two provider roles scannable.

### Final result: passed

External provider status is credential-dependent: the previously supplied text key reached Huoxing but lacks permission for its assigned group, while the previously supplied image key returned HTTP 401. Those are provider-account failures, not local routing failures.
