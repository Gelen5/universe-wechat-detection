# 合成引擎配置手册

`scripts/compose.py` 把底图、照片、中文文字合成为成品贴图。用户不需要打开任何第三方工具。

```bash
python scripts/compose.py --config spec.json
# 输出：{"ok": true, "out": "绝对路径", "size": [1080, 1440]}
```

---

## 简版配置（推荐，只填内容）

```json
{
  "preset": "auto",
  "canvas": {"w": 1080, "h": 1440},
  "base": "底图.jpg",
  "photo": "照片.jpg",
  "kicker": "娱评",
  "title": "他为什么\n突然退出综艺",
  "subtitle": "不是被封杀\n是这三件事同时发生了",
  "out": "成品.jpg"
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `preset` | 是 | `auto` / `left-image` / `top-image` / `split` / `full-bleed` / `text-only` |
| `canvas` | 否 | 默认 1080×1440（3:4） |
| `base` | 否 | 底图路径，缺省用纯色 `bg` |
| `bg` | 否 | 无底图时的背景色，默认 `#111114` |
| `photo` | 否 | 照片路径，`text-only` 不需要 |
| `kicker` | 否 | 小标签，只在 `left-image` 显示 |
| `title` | 是 | 主标题，**用 `\n` 手动断行** |
| `subtitle` | 否 | 副标题 |
| `index` | 否 | 页码角标，如 `"1/5"`，显示在右上角。多图系列必填 |
| `out` | 是 | 输出路径 |
| `quality` | 否 | JPG 质量，默认 92 |

覆盖项：`title_size`、`title_color`、`title_font`（`hei`/`regular`/`light`/`serif`）、`title_valign`、`title_line_gap`、`sub_size`、`sub_color`、`photo_radius`、`align`。

---

## 5 个预设的版式

| preset | 照片区 | 文字区 | 用在什么时候 |
|---|---|---|---|
| `left-image` | 左侧 4%–48%，圆角 24 | 右侧 52%–96% | 竖版人像、剧照、产品图 |
| `top-image` | 顶部 0–58%，裁切保上部 | 下方 63%–93% | 横版素材、教程图 |
| `split` | 顶部 0–54% | 下方纯色块内 59%–91% | 观点输出，最干净 |
| `full-bleed` | 铺满全图 | 底部渐变上 63%–93% | 情绪内容，冲击力最强 |
| `text-only` | 无 | 居中 30%–86% | 金句、总结 |

`auto` 规则：无照片 → `text-only`；照片高/宽 ≥ 1.05（竖版）→ `left-image`；否则 → `top-image`。

---

## 三条必须知道的规则

### 1. 断行必须手写 `\n`

引擎严格尊重手写换行，不会重新切词。**没有 `\n` 时才自动断行**，而自动断行容易断错词（"突然"被切成"突/然"）。主标题一律手写。

自动断行的兜底逻辑：优先在标点后断，其次在虚词（的/了/是/就/在/但…）后断，并且尽量均分各行、避免孤字。

### 2. 文字超框会缩字号，不会溢出

从 `title_size` 往下每档减 4px，直到放得下或到达 `min_size`（默认 40）。所以 `title_size` 填的是**上限**，不是固定值。

### 3. 照片裁切朝向

`cover` 裁切默认居中。`top-image` 和 `split` 自动用 `anchor: top`——保住人的头部，不会把脸切掉。需要改时传 `photo_fit` / 在完整配置里写 `anchor`。

---

## 完整配置（需要精确控制时）

```json
{
  "canvas": {"w": 1080, "h": 1440},
  "base": "底图.jpg",
  "layers": [
    {"type": "image", "path": "照片.jpg", "box": [0.04, 0.05, 0.48, 0.95],
     "fit": "cover", "anchor": "top", "radius": 24, "shadow": true},
    {"type": "scrim", "box": [0.48, 0, 1, 1], "color": "#0B0D10", "alpha": 135},
    {"type": "gradient", "box": [0, 0.45, 1, 1], "color": "#000000",
     "from_alpha": 0, "to_alpha": 215},
    {"type": "text", "text": "主标题", "box": [0.52, 0.22, 0.96, 0.55],
     "size": 78, "min_size": 40, "color": "#FFFFFF", "font": "hei",
     "align": "left", "valign": "bottom", "line_gap": 1.32, "max_lines": 4,
     "stroke": 0, "stroke_color": "#000000"}
  ],
  "out": "成品.jpg"
}
```

坐标全是 0–1 的归一化比例，换画布尺寸不用改配置。

图层类型：

| type | 作用 | 关键参数 |
|---|---|---|
| `image` | 贴照片 | `box` `fit`(cover/contain) `anchor`(top/center/bottom) `radius` `shadow` `border` |
| `scrim` | 纯色半透明遮罩 | `box` `color` `alpha` |
| `gradient` | 上下渐变遮罩 | `box` `color` `from_alpha` `to_alpha` `ease` |
| `text` | 文字 | `box` `text` `size` `min_size` `color` `font` `align` `valign` `line_gap` `max_lines` `stroke` |
| `pin` | 部位标注（图解类） | `label` `sub` `to` `from` `color` `side` `size` `dot` `halo` |
| `table` | 对照表格（清单类） | `columns` `headers` `rows` `header_bg` `row_h` `zebra` |
| `bars` | 横向条形排行 | `items` `max` `label_w` `bar_h` `thresholds` `palette` |

**preset 与自定义 layers 可以同时用**：preset 生成的图层在前，自定义图层追加在后，不会互相覆盖。

---

## pin 部位标注

画一个圆点落在目标位置，一条引线连到文字，用来做图解类贴图（图上标注、架构图、地图）。

```json
{"type":"pin","label":"鸡胸","sub":"鸡胸肉",
 "to":[0.316,0.500],     // 圆点位置（指向实物）
 "from":[0.185,0.497],   // 文字位置（引线末端）
 "color":"#B5563C","side":"left","size":40,
 "line_width":3,"dot":8,"halo":2}
```

| 参数 | 说明 |
|---|---|
| `to` / `from` | 归一化坐标，`to` 是实物位置，`from` 是文字锚点 |
| `side` | `left` 文字在引线左侧右对齐；`right` 左对齐 |
| `sub` | 下方小字，字号 = `size × 0.56` |
| `halo` | 文字白色描边宽度，压在复杂画面上时提高可读性 |

⚠️ **坐标要靠看图定**：AI 生成的主体位置不可预测，出图后看一遍再标，不要凭猜。第一版标偏很常见，调 `to` 即可。

## table 对照表格

```json
{"type":"table","box":[0.05,0.19,0.95,0.90],
 "columns":[{"w":0.22},{"w":0.26},{"w":0.52}],
 "headers":["部位","最适合","一句话记住"],
 "rows":[["鸡胸","炒、煎","切薄片抓点淀粉"]],
 "header_h":0.058,"row_h":0.072,
 "header_size":29,"cell_size":27,
 "header_bg":"#B5563C","text_color":"#3A2E26","key_color":"#8C4A32",
 "zebra":"#F6EBE4","line_color":"#E8DCD3","cell_pad":0.022}
```

- `header_h` / `row_h` 是**占画布高度的比例**，不是像素
- 单元格文字自动换行、超行高自动缩字号
- **行数超出 `box` 会在 stderr 给警告并截断**，不会画到画布外
- `key_color` 是第一列（表头列）的颜色，用于强调

## bars 条形排行

排行榜、数值对比的核心视觉。条形长度按比例，颜色可按阈值自动分高低。

```json
{"type":"bars","box":[0.06,0.28,0.94,0.80],
 "items":[{"label":"鲜枣","value":31},{"label":"西瓜","value":5}],
 "max":32,
 "label_w":0.24,"value_w":0.13,
 "size":40,"value_size":38,
 "bar_h":0.034,"row_gap":1.85,
 "track_color":"#15171D",
 "thresholds":[10,20],
 "palette":{"low":"#7D8C4E","mid":"#C9A227","high":"#C0453B"}}
```

| 参数 | 说明 |
|---|---|
| `items` | `[{label, value, color?, text?}]`，顺序即显示顺序，**自己先排好序** |
| `max` | 满格对应的值。不传则取最大值（最大那条会顶满） |
| `label_w` | 名称列占宽比例，名称**右对齐**到条形起点 |
| `bar_h` / `row_gap` | 条高占画布高度比例；行距 = `bar_h × row_gap` |
| `track_color` | 背景轨道色。**要暗于主色**，否则抢戏；不传则不画轨道 |
| `thresholds` | `[中, 高]` 两个断点，配合 `auto_color` 自动分色 |
| `palette` | 三档颜色 low/mid/high |
| `pad` | 数值与条形末端的间距，占画布宽度比例 |

数值自动贴在条形末端（不是行末），短条形也不会离太远；贴到右边界会自动回退。

⚠️ 颜色语义：绿=低/安全、金=中、红=高/警示。这是健康与风险场景的通用认知，不要反向用。

## 文字自动对比度

`text` 层默认 `auto_contrast: true`：采样该文字区域的平均亮度，
- 浅底（>150）→ 自动用深色 `#2B2B2E`
- 深底 → 自动用白色
- 中间地带 → 白字 + 深色描边兜底

**所以不要给浅色底图配白字**——不指定的颜色会自动算对。要强制指定就传 `color`，会覆盖自动判断。

---

## 多图批量（系列作品）

配置传**数组**即可一次出完，不用循环调用。

```json
[
  {"preset":"full-bleed","base":"b.jpg","photo":"p.jpg","index":"1/5",
   "title":"这三个月\n他到底经历了什么","out":"成品_01.jpg"},
  {"preset":"split","base":"b.jpg","photo":"p.jpg","index":"2/5",
   "title":"第一件事\n比想象的早","subtitle":"开机前两周就出现了","out":"成品_02.jpg"},
  {"preset":"text-only","base":"b.jpg","index":"5/5",
   "title":"所以不是\n被封杀","subtitle":"是他自己走的","out":"成品_05.jpg"}
]
```

返回：

```json
{"ok": true, "count": 5, "items": [{"out": "...", "size": [1080, 1440]}, ...]}
```

规则：
- 每项必须有自己的 `out`，否则自动命名为 `series_01.jpg` …
- **同一组只用一个 preset**（最多两三种做节奏），否则五张图像五个人做的
- `index` 显示 `1/5` 这种角标，位置右上角，颜色默认浅灰

---

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 字被切成奇怪的断行 | 没写 `\n` | 主标题手写换行 |
| 字号突然变小 | 文字超框触发了自适应 | 放宽 `box` 或减少字数 |
| 人像头部被切 | 用了 `cover` + 居中 | 用 `top-image`/`split`，或加 `anchor: top` |
| 照片变形 | 用了 `contain` 但框和照片比例差太多 | 改 `cover` |
| 找不到字体 | 系统无中文字体 | 把任意中文 TTF 放进 `scripts/fonts/` |
| 中文显示成方块 | 字体文件不含中文字形 | 换 `msyh.ttc` / `simhei.ttf` |
