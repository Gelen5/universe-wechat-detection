# 封面与标题设计规范

本参考用于微信贴图号的封面生成和标题设计。它吸收小红书生图规范中的“先定平台、受众、主题和页面信息，再生成图片”原则，但保留贴图号的独立传播特点：情绪表达、场景转发、视觉记忆和手机端快速理解。

## 一、总原则

- 先确定平台、受众、选题、封面承诺和每页信息，再写生图提示词。
- 图片服务于点击、理解、收藏和转发，不做只有氛围没有信息的装饰图。
- 默认比例为 3:4；封面通常是 1 张封面加 4-5 张正文卡。
- 一张图只承担一个核心信息，正文卡不堆多个观点。
- 默认使用当前宿主内置的生图模型。不要主动切换外部图片 API、第三方平台或要求 API Key。
- 生图和中文标题必须在同一次当前宿主 Image 模型调用中完成；不要先生成无字底图，再用 Pillow、HTML、Canvas 或其他本地工具叠加标题。
- WorkBuddy、CodexGPT 或其他 Agent 宿主都遵循同一原则：使用当前宿主可用的内置 Image 模型一次生成完整成品。
- 只有用户明确指定外部模型、服务商或 API 路径时，才改变默认执行方式。

## 二、40-50岁受众的封面审美

目标读者是正在进入人生后半程、规划退休或重新安排生活的人，不要把他们处理成缺乏活力的“老年人”。

优先使用：

- 稳重、温暖、真实、有生活感的场景
- 清楚的大字和高对比度
- 成熟但自然的人物形象
- 有用的清单、判断或生活方式承诺
- 米白、深青、墨绿、暖红、金色等克制配色
- 留白充足、信息层级少、手机缩略图仍能读懂的构图

避免：

- 过度霓虹、网红滤镜、廉价促销风
- 老年病弱、孤独、被照顾者形象
- “保证”“最适合所有人”“养老天堂”等绝对化承诺
- 过多小字、复杂边框、满版装饰和无意义标签
- 把“中老年”直接放在主标题里造成被标签化感
- 没有真实依据的价格、气候、医疗、宜居和排名结论

## 三、封面标题结构

封面最多设置三个文字层级：

1. 小标签：说明人群、系列或场景，例如“给40+的慢游清单”。
2. 主标题：一眼说清主题和点击理由，通常 2-3 行。
3. 副标题：补充具体价值或行动方向，控制为一行短句。

主标题优先使用以下结构：

- 人群 + 变化：40岁以后，旅行要换一种玩法
- 时间节点 + 行动：退休前，先去看看
- 数字 + 具体结果：5座慢生活城市
- 痛点 + 反常识：退休前最该准备的，不只是存款
- 场景 + 情绪：夫妻一起退休，先谈清楚这5件事

标题设计规则：

- 主标题只保留一个承诺，不在封面解释完整内容。
- 每行尽量保持短而有节奏，避免把一句话机械切成很多行。
- 数字、动作和核心名词要形成视觉重音。
- 标题必须与正文兑现，不能用夸张标题吸引点击后换成泛泛内容。
- 正文标题、封面标题和副标题不要重复说同一句话。
- 生成前准备 2-3 个标题版本，优先选择手机缩略图下最容易读懂的版本。

## 四、封面构图规则

生图前先指定文字区和视觉主体：

- 文字区与人物、建筑、地标分开，避免文字压在脸部和主体上。
- 默认让文字区占画面约 30%-45%，不让文字覆盖整张图。
- 主体只保留一个视觉中心；封面不要同时塞入五座城市的五个地标。
- 文字区使用天空、墙面、水面、浅色地面或轻微渐变遮罩作为干净背景。
- 人物或景观最好位于右下、下方或侧边，给标题留下稳定留白。
- 生成提示词必须写明“预留标题安全区”、标题的准确文字、行数、层级和排版位置；禁止生成额外文字、Logo 和水印。

## 五、推荐的宿主生图提示词骨架

~~~
Use case: ads-marketing
Asset type: WeChat Tie-Tu vertical cover background, 3:4 portrait
Primary request: Create a clear, shareable complete cover for {topic}, aimed at {target_user}. The topic should be understandable within one second from the generated image and title.
Scene/backdrop: {scene_or_background}, with no real brand logos or unverifiable landmarks.
Subject: {main_subject_or_persona}; keep people natural, mature and non-stereotyped.
Composition/framing: vertical 3:4, one main visual focus, reserve a clean text-safe area in {text_zone}, keep the subject away from the text area.
Lighting/mood: {mood}; practical, warm and visually calm.
Color palette: {palette}.
Text (verbatim): "{cover_text}"
Typography: render the exact Chinese title in the image, with clear hierarchy, large sharp characters, intentional line breaks and mobile readability.
Constraints: complete image and title must be generated in this single Image model call; clean margins, no extra text, no fake metrics, no guaranteed results, no medical or financial promises.
Avoid: dense UI, tiny labels, multiple competing subjects, influencer-style exaggeration, elderly frailty.
~~~

## 六、一次性生成规则

- 不生成无字底图，也不再使用本地工具后期叠加标题；完整图片和标题必须由同一次 Image 模型调用产出。
- 提示词必须同时给出小标签、主标题、副标题的准确文字，并要求模型保持正确字形、行距、字号层级和安全边距。
- 主标题使用最大字号，副标题和标签明显低一级；不要把所有文字做成同样大小。
- 文字与背景必须有足够对比度，必要时要求模型生成局部半透明渐变或克制色块，但不要覆盖大面积画面。
- 同一组卡片统一字体、字号逻辑、标签位置、边距和颜色。
- 文字安全区至少保留四周边距；不要贴边，不要压住人物脸部。
- 生成后必须检查错别字、标点、断行、数字和城市名；如果 Image 模型文字错误，重新发起一次完整生成，不得用本地叠字修补。
- 生成缩略图检查：缩小到手机信息流大小后，主标题仍能在 1 秒内读懂。

## 七、贴图号与小红书的差异

可以共享提示词骨架和清晰度规则，但不要把两种平台做成同一套图：

- 小红书更强调点击、收藏、搜索和步骤解释；贴图号更强调情绪、场景、转发和视觉记忆。
- 小红书正文可以使用页码和较多流程；贴图号正文卡应更像独立可传播的短句。
- 小红书封面可以更强营销；贴图号应减少促销感，增加生活判断和可转发表达。
- 小红书适合“痛点—方法—产品”链路；贴图号应先提供公共价值，不把 Skill 或产品硬塞进封面。
- 贴图号默认不强制显示 1/5 等页码，除非用户明确需要系列导航。

## 八、封面质量门禁

封面进入 pilot 或 preview 前必须检查：

- 主题是否一眼可见
- 点击理由是否明确
- 主标题是否只有一个核心承诺
- 文字是否在安全区内
- 手机缩略图是否可读
- 文字是否准确、无错别字和错误断行
- 人物、场景和文字是否互相遮挡
- 是否存在夸大、虚假排名、虚假价格或不当健康承诺
- 是否符合 40-50 岁受众的成熟审美
- 是否保留 Image 模型一次生成的完整成品和对应提示词，便于返工
