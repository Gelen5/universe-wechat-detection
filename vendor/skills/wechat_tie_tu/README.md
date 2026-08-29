# 微信贴图号内容生产工具

`wechat-tie-tu-publisher` 是一个独立的微信贴图号内容生产与草稿发布工具。

它面向“图片为主、文字为辅”的微信公众号内容，支持从选题策划、卡片规划、图片生成、图片验证、手机预览到草稿发布的完整流程。

本仓库与公众号长文工具完全分离，不包含公众号长文的 Markdown 转换、长文排版、反 AI 评分和长文发布逻辑。

## 主要能力

- 生成贴图号内容策划方案
- 支持 6 种内容类型
- 自动生成 `card_plan.json`
- 支持 1 张或多张图片，不设置图片数量上限
- 默认使用 `3:4` 竖版图片比例
- 支持人像、美女、模特、写真、穿搭等主题的人像增强
- 为多张图片生成统一的虚构成年模特设定
- 由当前宿主内置 Image 能力一次生成画面和准确中文标题
- 记录并验证宿主内置 Image 返回的图片
- 支持试生成和批量生成审批门禁
- 支持参考图尺寸、比例、色板和基础版式分析
- 检查图片路径、图片比例、卡片文案和来源记录
- 生成手机端预览 HTML
- 可选发布到微信公众号草稿箱

## 支持的内容类型

| 类型 | 适合内容 | 默认卡片结构 |
| --- | --- | --- |
| 教程步骤型 | 方法、教程、操作流程 | 封面 → 问题 → 步骤 → 步骤 → 总结 |
| 前后对比型 | 新旧变化、改造、升级 | 封面 → 过去 → 现在 → 对比 → 余味 |
| 清单推荐型 | 推荐、盘点、避坑、购买清单 | 封面 → 清单项 → 清单项 → 清单项 → 总结 |
| 行业观点型 | 行业现象、趋势、判断 | 封面 → 现象 → 证据 → 判断 → 结论 |
| 城市变化型 | 城市、街区、地标、旧景新貌 | 封面 → 旧景 → 今景 → 对比 → 记忆 |
| 情绪故事型 | 人物故事、回忆、情感表达 | 封面 → 场景 → 细节 → 转折 → 结尾 |

## 运行环境

- Python 3.10 或更高版本
- `requests`
- `Pillow`

贴图号的策划、生图、验证和预览不需要图片平台 API Key。图片由当前宿主会话的内置 Image 能力生成。

## 安装

### 直接安装依赖

```bash
python -m pip install -r requirements.txt
```

### 推荐：使用虚拟环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

检查命令是否可用：

```bash
python -m toolkit.cli --help
```

也可以安装为本地命令：

```bash
python -m pip install -e .
tie-tu --help
```

## 标准工作流程

### 第一步：生成贴图号策划

```bash
python -m toolkit.cli plan ^
  --industry "城市生活" ^
  --topic "长沙新老城区变化" ^
  --title "长沙，变了多少？" ^
  --content-type city_change ^
  --count 5 ^
  --style "真实纪实、自然光、生活化街拍" ^
  --audience "关注城市变化的中年读者" ^
  --output card_plan.json
```

PowerShell 可以写成一行：

```powershell
python -m toolkit.cli plan --industry "城市生活" --topic "长沙新老城区变化" --title "长沙，变了多少？" --content-type city_change --count 5 --style "真实纪实、自然光、生活化街拍" --audience "关注城市变化的中年读者" --output card_plan.json
```

如果不指定 `--content-type`，工具会根据行业、主题和标题进行关键词匹配，选择一个默认类型。

### 第二步：查看内容类型推荐

只想查看 6 种内容类型的匹配结果时：

```bash
python -m toolkit.cli plan --industry "女性时尚" --topic "复古美女街拍" --recommend
```

### 第三步：检查策划方案

```bash
python -m toolkit.cli validate card_plan.json
```

验证结果会区分：

- `errors`：必须修复的问题
- `warnings`：可以继续，但建议补充的问题
- `ok`：当前方案是否通过硬性检查

刚生成的策划如果还没有图片和来源，通常会有警告，这是正常的。

### 第四步：确认卡片策划

用户确认选题、卡片结构和图片方向后，执行：

```bash
python -m toolkit.cli approve card_plan.json --stage card_plan --status approved
```

没有通过这一关，工具不会进入试生成图片阶段。

### 第五步：使用宿主内置 Image 生成试图

Agent 直接调用当前 WorkBuddy、Codex、ChatGPT 或其他宿主会话已经开放的内置 Image 能力，一次生成 3:4 画面和准确中文标题。不要先运行裸 `pilot`，不要生成 `.request.json`，不要配置图片 API。

### 第六步：记录试生成图片

宿主内置 Image 返回图片后，使用真实本地路径记录：

```bash
python -m toolkit.cli pilot card_plan.json --image "C:\\path\\to\\pilot.png"
```

回填后查看状态：

```bash
python -m toolkit.cli status card_plan.json
```

### 第七步：确认试生成图片

确认第一张图片的真实性、构图、服装、人物一致性和整体风格后：

```bash
python -m toolkit.cli approve card_plan.json --stage pilot_image --status approved
```

没有通过试生成审核，批量生成会被阻止。

### 第八步：依次生成并记录后续图片

由当前宿主内置 Image 能力逐张生成，每张图片都用 `pilot --index N --image` 记录。全部记录后执行：

```bash
python -m toolkit.cli batch card_plan.json
```

`batch` 只检查图片是否齐全，不调用图片 API，也不生成请求文件。

### 第九步：生成手机预览

```bash
python -m toolkit.cli preview card_plan.json --output tie-tu-preview.html
```

用浏览器打开 `tie-tu-preview.html`，检查：

- 图片是否完整显示
- 图片比例是否统一
- 文字是否位于安全区域
- 卡片顺序是否正确
- 短文案是否自然
- 图片来源是否记录

## 人像增强

当主题包含以下意图时，会自动启用人像增强：

- 人像
- 美女
- 模特
- 写真
- 复古女性
- 穿搭
- 妆容
- 街拍

人像增强会为整组图片生成统一的 `model_bible`，并为每张卡片生成独立的 `portrait_spec`，用于保持：

- 同一个虚构成年模特
- 稳定的年龄范围
- 稳定的脸部方向
- 稳定的发型和肤色
- 统一的镜头和光线风格
- 自然的皮肤和服装材质

输出人像提示词：

```bash
python -m toolkit.cli portrait-prompt card_plan.json
```

只查看第 1 张卡片：

```bash
python -m toolkit.cli portrait-prompt card_plan.json --index 1
```

关闭人像增强：

```bash
python -m toolkit.cli plan --industry "城市生活" --topic "长沙街景" --portrait-mode off --output card_plan.json
```

强制启用人像增强：

```bash
python -m toolkit.cli plan --industry "生活方式" --topic "日常穿搭" --portrait-mode required --output card_plan.json
```

## 参考图分析

可以测量参考图的尺寸、方向、比例、主色和亮度信息：

```bash
python -m toolkit.cli reverse-image card_plan.json --image "C:\\path\\to\\reference.png"
```

该功能只记录可测量信息，不会自动识别或编造图片中的文字、来源和事实。

## 来源记录

### 记录网络来源

```bash
python -m toolkit.cli source card_plan.json \
  --source-id source-1 \
  --kind web \
  --title "来源标题" \
  --url "https://example.com" \
  --status verified
```

### 记录 AI 生成图片

```bash
python -m toolkit.cli source card_plan.json \
  --source-id image-ai-1 \
  --kind ai \
  --title "宿主模型生成底图" \
  --status illustrative
```

来源类型包括：

- `web`：网页来源
- `user`：用户提供的图片或资料
- `ai`：AI 生成内容
- `reference`：参考图
- `claim`：需要核验的事实主张

## 查看流程状态

```bash
python -m toolkit.cli status card_plan.json
```

状态包括：

- 选题、策划、试生成、批量生成、预览和发布审批状态
- 试生成图片状态
- 批量生成状态
- 每张卡片的图片路径和生成状态
- 质量门禁结果

## 发布到微信公众号草稿箱

发布是可选步骤。只有在图片、文案、预览和质量检查都确认后，才执行：

```bash
python -m toolkit.cli approve card_plan.json --stage publish --status approved
python -m toolkit.cli publish card_plan.json
```

发布时需要提供微信公众号配置。可以通过环境变量提供：

PowerShell：

```powershell
$env:WECHAT_APPID="你的公众号 AppID"
$env:WECHAT_SECRET="你的公众号 Secret"
python -m toolkit.cli publish card_plan.json
```

也可以创建本地 `config.json`：

```json
{
  "wechat": {
    "appid": "你的公众号 AppID",
    "secret": "你的公众号 Secret"
  }
}
```

`config.json` 已加入 `.gitignore`，不会被提交到 GitHub。

## 图片生成凭证说明

### 不需要 API Key 的功能

- 选题策划
- 内容类型推荐
- 卡片方案生成
- 人像提示词生成
- 参考图分析
- 图片验证
- 手机预览
- 当前宿主内置 Image 生图

图片生成永远不要求 `OPENAI_API_KEY` 或第三方图片平台 Key，也不提供 CLI/API 生图回退。只有明确发布到微信公众号草稿箱时，才需要微信公众号 AppID 和 Secret。

如果当前会话没有开放内置 Image 能力，请切换到支持图片生成的会话；不要配置图片 API Key。

## 项目结构

```text
wechat-tie-tu-publisher/
├── SKILL.md                         # Agent 使用说明
├── README.md                        # 项目文档
├── pyproject.toml                   # Python 项目配置
├── requirements.txt                 # 运行依赖
├── toolkit/
│   ├── cli.py                        # 独立 CLI
│   ├── contracts.py                  # 工作流数据协议
│   ├── briefs.py                     # 贴图号 Brief
│   ├── config.py                     # 配置加载
│   ├── wechat_api.py                 # 微信 API 最小封装
│   └── tie_tu/
│       ├── planner.py                # 卡片策划
│       ├── models.py                 # 数据模型
│       ├── generation.py             # 宿主内置 Image 提示词和记录门禁
│       ├── portrait_router.py        # 人像路由
│       ├── portrait_prompt.py        # 人像提示词
│       ├── image_reverse.py          # 参考图分析
│       ├── validator.py              # 质量验证
│       ├── render.py                 # 手机预览
│       └── publisher.py              # 贴图号草稿发布
├── references/                       # 流程和兼容性文档
└── tests/                            # 自动化测试
```

## 自动化测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- 六类内容类型推荐
- 卡片数量边界
- `card_plan.json` 数据结构
- 人像自动、强制和关闭模式
- 旧计划加载兼容
- 参考图分析
- 试生成和批量生成门禁
- 禁止请求文件和图片 API 回退的宿主原生流程
- 手机预览生成

## 与公众号长文的关系

本仓库不负责公众号长文。两套工具的边界如下：

| 功能 | 公众号长文仓库 | 本仓库 |
| --- | --- | --- |
| 长文选题与写作 | 支持 | 不包含 |
| 反 AI 评分 | 支持 | 不包含 |
| 长文 HTML 排版 | 支持 | 不包含 |
| 图片主导贴图号 | 不包含 | 支持 |
| 贴图号卡片策划 | 不包含 | 支持 |
| 人像增强 | 不包含 | 支持 |
| 贴图号预览 | 不包含 | 支持 |
| 贴图号草稿发布 | 不包含 | 支持 |

## 常见问题

### 运行命令时报 `No module named requests` 或 `No module named PIL`

安装依赖：

```bash
python -m pip install -r requirements.txt
```

### 为什么 `pilot` 没有直接生成图片？

`pilot` 的职责只是记录当前宿主内置 Image 已经生成的图片，不负责生图。Agent 应先直接调用当前会话的 Image 能力，再执行：

```bash
python -m toolkit.cli pilot card_plan.json --image "图片的绝对路径"
```

### 为什么批量生成被阻止？

必须按顺序完成：

```text
卡片策划确认
→ 试生成图片
→ 试生成图片确认
→ 批量生成
```

对应命令：

```bash
python -m toolkit.cli approve card_plan.json --stage card_plan --status approved
python -m toolkit.cli pilot card_plan.json --index 1 --image "图片的绝对路径"
python -m toolkit.cli approve card_plan.json --stage pilot_image --status approved
python -m toolkit.cli batch card_plan.json
```

如果宿主未开放内置生图能力，停止图片阶段并切换到支持生图的会话；不要询问或配置任何图片 API Key。

### 为什么验证结果有 warnings？

`warnings` 不一定会阻止流程，常见原因是：

- 尚未记录来源
- 尚未回填图片
- 图片比例不是接近 `3:4`
- 卡片文字较长

`errors` 才是必须处理的硬性问题。

### 微信发布失败怎么办？

检查：

1. `WECHAT_APPID` 和 `WECHAT_SECRET` 是否正确。
2. 公众号后台是否允许当前服务器 IP。
3. 图片是否存在且可以正常读取。
4. 图片是否已经全部回填。
5. 是否已经通过贴图号质量验证。

## 许可证

当前仓库未单独声明开源许可证。使用前请根据你的组织和发布需求补充许可证文件。
