---
name: wechat-tie-tu-publisher
description: 独立的微信贴图号内容工作流，与公众号长文流程完全分离。
---

# 微信贴图号

触发词：`贴图号`、`贴图`、`小绿书`、`图文笔记`、`图片消息`。

流程：选题研究 → 内容类型 → `card_plan.json` → 用户确认 → 试生成图 → 用户确认 → 批量图片 → 验证 → 手机预览 → 明确确认后发布。

支持教程步骤型、前后对比型、清单推荐型、行业观点型、城市变化型、情绪故事型。默认 3:4 竖幅；生图和中文标题必须由同一次当前宿主 Image 模型调用完成，不拆成无字底图与本地叠字两个阶段。

封面和标题生成必须遵循 [封面与标题设计规范](references/cover-and-title-design.md)：先确定受众、选题承诺、标题层级和文字安全区，再在同一次 Image 模型调用中生成带中文标题的完整成品；封面要在手机缩略图中一眼说清主题，适配40-50岁受众的成熟、温暖、清晰审美。封面最多使用小标签、主标题、副标题三个文字层级，主标题只保留一个承诺。

人像主题自动启用成年虚构模特一致性提示词。默认图片生成和标题排版使用当前宿主内置的 Image 模型，不区分 WorkBuddy、CodexGPT、ChatGPT 或其他 Agent 宿主。除非用户明确要求，否则不得再用 Pillow、HTML、Canvas 或其他本地工具替换标题排版。`publish` 才需要微信草稿配置。

## 宿主原生生图强制规则

- Agent 必须直接调用当前会话已经提供的内置 Image / image generation 能力，一次生成画面和准确中文标题；一张图片对应一次宿主生图调用。
- 图片生成不允许询问、检查或要求用户配置 `OPENAI_API_KEY`、第三方图片平台 Key 或任何图片 API 凭证。
- 图片生成不允许把 CLI/API、外部图片平台、让用户另行生图后提供路径，作为内置生图不可用时的备用方案。
- 不要运行不带 `--image` 的 `pilot` 或 `batch` 来尝试生图。Python CLI 只负责计划、记录、验证和预览，不能替代宿主的内置 Image 能力。
- 宿主返回图片文件后，才用 `pilot card_plan.json --index N --image "<本地图片路径>"` 记录结果。
- 如果当前会话没有暴露内置生图能力，停止图片阶段，并只说明：`当前宿主会话未开放内置生图能力，请切换到支持图片生成的会话后继续；本 Skill 不需要也不会索要 API Key。` 不得继续推荐任何密钥或外部生成方案。

```bash
python -m toolkit.cli plan --industry "城市生活" --topic "长沙新老城区变化" --count 5 --output card_plan.json
python -m toolkit.cli validate card_plan.json
python -m toolkit.cli preview card_plan.json
python -m toolkit.cli approve card_plan.json --stage card_plan --status approved
python -m toolkit.cli pilot card_plan.json --index 1 --image "<宿主内置 Image 返回的本地图片路径>"
python -m toolkit.cli approve card_plan.json --stage pilot_image --status approved
# 后续图片由宿主内置 Image 逐张生成，并分别用 pilot --index N --image 记录
python -m toolkit.cli batch card_plan.json
```
