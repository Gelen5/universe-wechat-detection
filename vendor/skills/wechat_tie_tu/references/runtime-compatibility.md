# 宿主兼容与凭证边界

本 Skill 在 WorkBuddy、Codex、ChatGPT 或其他 Agent 宿主中运行时，图片必须由当前会话已经开放的内置 Image 能力生成。Python 工具包只负责计划、记录、验证和预览，不连接任何图片 API。

## 无密钥执行路径

1. Agent 完成选题、卡片文案和提示词。
2. Agent 直接调用当前会话的内置 Image 能力，一次生成画面与准确中文标题。
3. 宿主返回本地图片后，运行 `tie-tu pilot card_plan.json --index N --image "<图片路径>"` 记录。
4. 全部图片记录后运行 `tie-tu batch card_plan.json` 检查完整性，再验证和预览。

图片阶段不得询问、读取或要求用户配置 `OPENAI_API_KEY`、第三方平台 Key 或其他图片 API 凭证，也不得把 CLI/API、外部图片平台或让用户另行生图作为备用方案。

## 宿主没有生图能力时

“当前模型”只有在宿主会话同时开放了 Image 工具时才能输出图片文件。如果当前会话没有暴露该能力，Agent 必须停止图片阶段，并只告知用户：

> 当前宿主会话未开放内置生图能力，请切换到支持图片生成的会话后继续；本 Skill 不需要也不会索要 API Key。

不要生成 `.request.json`，不要建议 CLI/API，不要要求用户提供外部生成图片的路径。

微信公众号草稿发布是独立步骤，只有用户明确要求 `publish` 时才可能需要公众号 AppID 和 Secret；它与图片生成凭证无关。
