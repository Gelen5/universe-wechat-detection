#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
贴图合成引擎 — 把底图、照片、中文文字合成为成品贴图。
用户不需要打开任何第三方工具。

用法：
    python compose.py --config spec.json

spec.json 结构见 README 或 SKILL.md。坐标一律用 0-1 归一化比例，
不必关心像素，换画布尺寸不用改配置。
"""

import argparse
import json
import os
import sys
from functools import lru_cache

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.stderr.write(
        "缺少 Pillow，无法出图。\n"
        "请先安装：python -m pip install pillow\n"
    )
    sys.exit(1)

# ---------- 字体 ----------

# 只列固定的系统字体目录，不读环境变量
FONT_DIRS = [
    "/usr/share/fonts/opentype/noto",
    r"C:\Windows\Fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts"),
]

FONT_ALIAS = {
    "hei": ["msyhbd.ttc", "msyh.ttc", "simhei.ttf", "PingFang.ttc",
            "NotoSansCJK-Bold.ttc", "NotoSansSC-Regular.otf", "NotoSansCJK-Regular.ttc"],
    "regular": ["msyh.ttc", "simhei.ttf", "PingFang.ttc",
                "NotoSansSC-Regular.otf", "NotoSansCJK-Regular.ttc"],
    "light": ["msyhl.ttc", "msyh.ttc", "PingFang.ttc", "NotoSansSC-Regular.otf"],
    "serif": ["simsun.ttc", "NotoSerifCJK-Regular.ttc", "STSong.ttf", "NotoSansSC-Regular.otf"],
}


def resolve_font(alias):
    names = FONT_ALIAS.get(alias, FONT_ALIAS["hei"])
    for d in FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for name in names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


@lru_cache(maxsize=64)
def load_font(alias, size):
    path = resolve_font(alias)
    if not path:
        raise RuntimeError(
            "当前环境没有中文字体，无法做精确排版。\n"
            "建议改走 AI 直出：把文字写进生图提示词直接生成（中文可能错字，需核对）。\n"
            "或自行把一个中文 TTF/OTF 放到 scripts/fonts/ 目录后重试。"
        )
    return ImageFont.truetype(path, size)


# ---------- 基础工具 ----------


def hex2rgb(h, alpha=None):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, 255 if alpha is None else alpha)


def box2px(box, w, h):
    x1, y1, x2, y2 = box
    return (int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h))


def fit_cover(img, tw, th, anchor="center"):
    """等比缩放并裁切到目标尺寸。anchor 控制裁掉哪一头：
    top 保上部（人像头部）、bottom 保下部、center 居中。"""
    sw, sh = img.size
    scale = max(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale + 0.5)), max(1, int(sh * scale + 0.5))
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    if anchor == "top":
        top = 0
    elif anchor == "bottom":
        top = nh - th
    else:
        top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def fit_contain(img, tw, th):
    sw, sh = img.size
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale + 0.5)), max(1, int(sh * scale + 0.5))
    return img.resize((nw, nh), Image.LANCZOS)


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def add_shadow(canvas, size, radius, blur, offset, alpha):
    """在 canvas 上画一层柔和阴影，返回修改后的 canvas"""
    pad = blur * 2
    sw, sh = size[0] + pad * 2, size[1] + pad * 2
    sh_img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh_img)
    d.rounded_rectangle(
        [pad, pad, pad + size[0], pad + size[1]], radius=radius, fill=(0, 0, 0, alpha)
    )
    sh_img = sh_img.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(sh_img, (offset[0] - pad, offset[1] - pad))


# ---------- 中文断行 ----------


def char_width(font, ch):
    bbox = font.getbbox(ch)
    return bbox[2] - bbox[0]


NO_BREAK_HEAD = set("，。！？、；：）】》”』…·,!?;:%)]}>")
NO_BREAK_TAIL = set("（【《“‘『([{<")

# 断点优先级：数字越大越适合断行
PUNCT_BREAK = set("，。！？；：、")          # 标点后，最自然
WEAK_BREAK = set("的地得了是就都也很在与和或但而却又还把被让给从向对为以及之其吗呢吧啊")
GOOD_AFTER = set("这那一个我们你他她它件种次天年月日")


def _break_score(ch):
    """在 ch 之后断行的合适程度"""
    if ch in PUNCT_BREAK:
        return 3
    if ch in WEAK_BREAK:
        return 2
    if ch in GOOD_AFTER:
        return 1
    return 0


def wrap_text(draw, text, font, max_w, balanced=True):
    """中文断行：优先在标点/虚词处断，尽量均分各行，避免孤字。

    含手写换行符时，严格按手写断行（超宽交给字号自适应去缩，不重新切词）。
    """
    hard = "\n" in text
    out = []
    for para in text.split("\n"):
        if not para.strip():
            out.append("")
            continue

        if hard:
            # 手写断行：整段一行。只有真的放不下才退回自动断行
            if draw.textlength(para, font=font) <= max_w:
                out.append(para)
                continue

        n = len(para)
        widths = []
        prev = 0.0
        for ch in para:
            w = draw.textlength(para[: len(widths) + 1], font=font)
            widths.append(w)
            prev = w

        # 贪心算出最少行数，作为均分目标
        if balanced:
            lines_need, i = 1, 0
            while i < n:
                j = i
                while j < n and widths[j] - (widths[i - 1] if i > 0 else 0) <= max_w:
                    j += 1
                if j == i:
                    j = i + 1
                i = j
                if i < n:
                    lines_need += 1
            target_each = max(1, -(-n // max(1, lines_need)))
        else:
            target_each = n

        start = 0
        while start < n:
            # 本行最多能放到哪
            base = widths[start - 1] if start > 0 else 0.0
            end = start
            while end < n and widths[end] - base <= max_w:
                end += 1
            if end == start:
                end = start + 1
            if end >= n:
                out.append(para[start:])
                break

            # 在 (start, end] 里挑断点：先要有语义（标点/虚词后），再要离理想位置近
            ideal = min(start + target_each, end)
            cands = []
            for k in range(start + 1, end + 1):
                prev_ch = para[k - 1]
                nxt_ch = para[k] if k < n else ""
                if prev_ch in NO_BREAK_TAIL or nxt_ch in NO_BREAK_HEAD:
                    continue
                cands.append(k)
            if not cands:
                cands = [end]

            def _tier(k):
                s = _break_score(para[k - 1])
                return 0 if s >= 2 else (1 if s == 1 else 2)

            # 先限定在理想位置附近挑语义断点，避免为了凑虚词把行截得过短
            tol = max(2, int(target_each * 0.45))
            near = [k for k in cands if abs(k - ideal) <= tol]
            pool = near or cands
            best = min(pool, key=lambda k: (_tier(k), abs(k - ideal)))

            # 避免孤字：剩 1 个字就跟上一行走
            if n - best == 1 and best - start > 1:
                best = n

            out.append(para[start:best])
            start = best

    return out


def _region_luma(canvas, box):
    """取一块区域的平均亮度，用来决定文字该用深色还是浅色"""
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return 128
    region = canvas.crop((x1, y1, x2, y2)).convert("L")
    region.thumbnail((40, 40))
    hist = region.histogram()
    total = sum(hist)
    if not total:
        return 128
    return sum(i * c for i, c in enumerate(hist)) / total


def draw_text_block(canvas, layer, w, h):
    """渲染一个文字层，自动换行 + 字号自适应 + 自动对比度"""
    draw = ImageDraw.Draw(canvas)
    box = box2px(layer["box"], w, h)
    bw, bh = box[2] - box[0], box[3] - box[1]
    if bw <= 0 or bh <= 0:
        return

    text = str(layer.get("text", ""))
    if not text:
        return

    align = layer.get("align", "left")
    valign = layer.get("valign", "top")
    line_gap = float(layer.get("line_gap", 1.35))
    max_lines = layer.get("max_lines")
    alias = layer.get("font", "hei")

    color_hex = layer.get("color")
    halo_hex = layer.get("halo_color")
    stroke_w = int(layer.get("stroke", 0))

    # 自动对比度：底图浅就用深字，底图深就用浅字，中间地带加描边兜底
    if layer.get("auto_contrast", True):
        luma = _region_luma(canvas, box)
        if luma > 150:
            color_hex = color_hex or "#2B2B2E"
            halo_hex = halo_hex or "#FFFFFF"
        else:
            color_hex = color_hex or "#FFFFFF"
            halo_hex = halo_hex or "#1A1A1C"
            stroke_w = max(stroke_w, 2 if 90 <= luma <= 150 else 0)
    color_hex = color_hex or "#FFFFFF"
    color = hex2rgb(color_hex, int(layer.get("alpha", 255)))
    stroke_color = hex2rgb(halo_hex or "#000000")

    size = int(layer.get("size", 64))
    min_size = int(layer.get("min_size", 24))
    auto = layer.get("auto_size", True)

    def try_size(sz):
        f = load_font(alias, sz)
        lines = wrap_text(draw, text, f, bw)
        line_h = int(sz * line_gap)
        total_h = line_h * len(lines)
        widest = max((draw.textlength(l, font=f) for l in lines), default=0)
        ok = total_h <= bh + 4 and widest <= bw
        if max_lines and len(lines) > max_lines:
            ok = False
        return ok, lines, line_h, total_h

    if auto:
        ok, lines, line_h, total_h = try_size(size)
        while not ok and size > min_size:
            size -= 4
            ok, lines, line_h, total_h = try_size(size)
    else:
        _, lines, line_h, total_h = try_size(size)

    # 真的被断成多行、又没手写换行时才提醒，短标题不打扰
    if (
        "\n" not in text
        and len(lines) > 1
        and layer.get("warn_no_break", True)
    ):
        sys.stderr.write(
            f"[hint] 「{text[:14]}…」无手写换行，被断成 {len(lines)} 行，可能切断词语。"
            f"建议在语义停顿处加 \\n\n"
        )

    # 垂直定位
    if valign == "center":
        y = box[1] + (bh - total_h) // 2
    elif valign == "bottom":
        y = box[3] - total_h
    else:
        y = box[1]

    # 先算好每行的位置，再统一画高亮，最后画字（顺序不能反，否则色块盖字）
    f = load_font(alias, size)
    placed = []
    yy = y
    for line in lines:
        lw = draw.textlength(line, font=f)
        if align == "center":
            x = box[0] + (bw - lw) // 2
        elif align == "right":
            x = box[2] - lw
        else:
            x = box[0]
        placed.append((x, lw, line, yy))
        yy += line_h

    hl = layer.get("highlight")
    if hl:
        hl_color = hex2rgb(hl)
        hp = int(layer.get("highlight_pad_x", 9))
        vp = int(layer.get("highlight_pad_y", 4))
        hh = int(size * float(layer.get("highlight_h", 1.16)))
        for x, lw, line, ly in placed:
            draw.rectangle([x - hp, ly - vp, x + lw + hp, ly + hh], fill=hl_color)

    for x, lw, line, ly in placed:
        kw = dict(fill=color, font=f)
        if stroke_w > 0:
            kw["stroke_width"] = stroke_w
            kw["stroke_fill"] = stroke_color
        draw.text((x, ly), line, **kw)


# ---------- 排版预设 ----------
# 调用时只需 {"preset": "left-image", "base":..., "photo":..., "title":..., "subtitle":...}
# 坐标不用管，引擎自己组装图层。

PRESETS = {
    # 左图右文：竖版贴图最常用，明星剧照、人像、产品图都适用
    "left-image": {
        "photo_box": [0.04, 0.05, 0.48, 0.95],
        "photo_radius": 24,
        "photo_shadow": True,
        "scrim": {"box": [0.48, 0.0, 1.0, 1.0], "alpha": 0},
        "title_box": [0.52, 0.22, 0.96, 0.55],
        "title_size": 78,
        "title_max_lines": 4,
        "title_valign": "bottom",
        "sub_box": [0.52, 0.58, 0.96, 0.72],
        "sub_size": 32,
        "sub_max_lines": 4,
        "kicker_box": [0.52, 0.13, 0.96, 0.18],
    },
    # 上图下文：照片在上、文字在下，适合横构图素材和教程图
    "top-image": {
        "photo_box": [0.0, 0.0, 1.0, 0.58],
        "photo_radius": 0,
        "photo_shadow": False,
        "photo_anchor": "top",
        "scrim": {"box": [0.0, 0.55, 1.0, 0.60], "alpha": 0},
        "title_box": [0.08, 0.63, 0.92, 0.80],
        "title_size": 72,
        "title_max_lines": 3,
        "sub_box": [0.08, 0.82, 0.92, 0.93],
        "sub_size": 30,
        "sub_max_lines": 3,
        "kicker_box": None,
    },
    # 全图压字：照片铺满，底部渐变压暗，文字在最下三分之一
    "full-bleed": {
        "photo_box": [0.0, 0.0, 1.0, 1.0],
        "photo_radius": 0,
        "photo_shadow": False,
        "gradient": {"box": [0.0, 0.45, 1.0, 1.0], "from_alpha": 0, "to_alpha": 215},
        "title_box": [0.07, 0.63, 0.93, 0.82],
        "title_size": 74,
        "title_max_lines": 3,
        "sub_box": [0.07, 0.84, 0.93, 0.93],
        "sub_size": 30,
        "sub_max_lines": 2,
        "kicker_box": None,
    },
    # 上下分栏：上图 + 下方色块，文字压在色块里，最干净
    "split": {
        "photo_box": [0.0, 0.0, 1.0, 0.54],
        "photo_radius": 0,
        "photo_shadow": False,
        "photo_anchor": "top",
        "scrim": {"box": [0.0, 0.52, 1.0, 1.0], "alpha": 245, "color": "#12141A"},
        "title_box": [0.08, 0.59, 0.92, 0.78],
        "title_size": 76,
        "title_max_lines": 3,
        "sub_box": [0.08, 0.80, 0.92, 0.91],
        "sub_size": 30,
        "sub_max_lines": 3,
        "kicker_box": None,
    },
    # 纯文字卡：没有照片也能出，适合金句、观点、总结
    "text-only": {
        "photo_box": None,
        "scrim": None,
        "title_box": [0.10, 0.26, 0.90, 0.62],
        "title_size": 84,
        "title_max_lines": 5,
        "sub_box": [0.10, 0.66, 0.90, 0.80],
        "sub_size": 32,
        "sub_max_lines": 3,
        "kicker_box": None,
    },
}


def expand_preset(spec):
    """把简版 spec 展开成完整图层配置；已经是完整 spec 的原样返回"""
    name = spec.get("preset")

    # auto：按素材比例自动选，避免竖版人像被塞进横框切掉头
    if name == "auto":
        photo = spec.get("photo")
        if not photo or not os.path.exists(photo):
            name = "text-only"
        else:
            pw, ph = Image.open(photo).size
            name = "left-image" if ph >= pw * 1.05 else "top-image"
        spec = dict(spec, preset=name)

    if not name:
        return spec
    p = PRESETS.get(name)
    if not p:
        raise RuntimeError(f"未知排版预设：{name}，可选：{', '.join(PRESETS)}")

    layers = []

    if spec.get("photo") and p.get("photo_box"):
        layers.append({
            "type": "image",
            "path": spec["photo"],
            "box": p["photo_box"],
            "fit": spec.get("photo_fit", "cover"),
            "radius": int(spec.get("photo_radius", p.get("photo_radius", 0))),
            "shadow": p.get("photo_shadow", False),
            "anchor": p.get("photo_anchor", "center"),
        })

    if p.get("scrim") and p["scrim"].get("alpha", 0) > 0:
        layers.append({"type": "scrim", **p["scrim"]})

    if p.get("gradient"):
        layers.append({"type": "gradient", **p["gradient"]})

    if spec.get("kicker") and p.get("kicker_box"):
        layers.append({
            "type": "text",
            "text": spec["kicker"],
            "box": p["kicker_box"],
            "size": int(spec.get("kicker_size", 30)),
            "min_size": 20,
            "color": spec.get("kicker_color", "#E8B65C"),
            "font": "hei",
            "align": "left",
            "valign": "bottom",
            "line_gap": 1.3,
            "max_lines": 1,
        })

    if spec.get("title"):
        layers.append({
            "type": "text",
            "text": spec["title"],
            "box": p["title_box"],
            "size": int(spec.get("title_size", p["title_size"])),
            "min_size": int(spec.get("title_min_size", 40)),
            "color": spec.get("title_color"),
            "font": spec.get("title_font", "hei"),
            "align": spec.get("align", "left"),
            "valign": spec.get("title_valign", p.get("title_valign", "center")),
            "line_gap": float(spec.get("title_line_gap", 1.32)),
            "max_lines": p["title_max_lines"],
        })

    if spec.get("subtitle"):
        layers.append({
            "type": "text",
            "text": spec["subtitle"],
            "box": p["sub_box"],
            "size": int(spec.get("sub_size", p["sub_size"])),
            "min_size": int(spec.get("sub_min_size", 22)),
            "color": spec.get("sub_color"),
            "font": spec.get("sub_font", "regular"),
            "align": spec.get("align", "left"),
            "valign": "top",
            "line_gap": float(spec.get("sub_line_gap", 1.7)),
            "max_lines": p["sub_max_lines"],
        })

    # 多图系列的页码角标，如 1/5。不传 index 就不显示
    if spec.get("index"):
        layers.append({
            "type": "text",
            "text": str(spec["index"]),
            "box": spec.get("index_box", [0.82, 0.03, 0.95, 0.07]),
            "size": int(spec.get("index_size", 26)),
            "auto_size": False,
            "color": spec.get("index_color", "#8A9099"),
            "font": "hei",
            "align": "right",
            "valign": "top",
            "line_gap": 1.2,
            "max_lines": 1,
        })

    out = dict(spec)
    # preset 生成的图层在前，用户自定义的图层追加在后（不覆盖）
    out["layers"] = layers + list(spec.get("layers") or [])
    return out


def draw_pin(draw, layer, w, h):
    """部位标注：圆点 + 引线 + 文字。用于图解类贴图。"""
    to = (int(layer["to"][0] * w), int(layer["to"][1] * h))
    fr = (int(layer["from"][0] * w), int(layer["from"][1] * h))
    color = hex2rgb(layer.get("color", "#B5563C"))
    lw = max(1, int(layer.get("line_width", 3)))

    draw.line([to, fr], fill=color, width=lw)

    r = int(layer.get("dot", 7))
    draw.ellipse(
        [to[0] - r, to[1] - r, to[0] + r, to[1] + r],
        fill=color,
        outline=hex2rgb(layer.get("dot_ring", "#FFFFFF")),
        width=max(1, int(layer.get("dot_ring_w", 2))),
    )

    label = str(layer.get("label", ""))
    sub = str(layer.get("sub", ""))
    size = int(layer.get("size", 36))
    f = load_font(layer.get("font", "hei"), size)
    side = layer.get("side", "left")
    pad = int(layer.get("gap", 14))

    pad_x = int(layer.get("pad_x", 0) * w)
    if side == "left":
        x = fr[0] - pad - draw.textlength(label, font=f) - pad_x
    else:
        x = fr[0] + pad + pad_x
    y = fr[1] - size // 2
    halo = int(layer.get("halo", 2))
    halo_c = hex2rgb(layer.get("halo_color", "#FFFFFF"))
    kw = {"font": f, "fill": color}
    if halo > 0:
        kw["stroke_width"] = halo
        kw["stroke_fill"] = halo_c
    draw.text((x, y), label, **kw)

    if sub:
        fs = int(size * float(layer.get("sub_ratio", 0.56)))
        fsub = load_font(layer.get("sub_font", "regular"), fs)
        sub_color = hex2rgb(layer.get("sub_color", "#8A7F72"))
        sy = y + int(size * 1.18)
        if side == "left":
            sx = fr[0] - pad - draw.textlength(sub, font=fsub) - pad_x
        else:
            sx = fr[0] + pad + pad_x
        kw2 = {"font": fsub, "fill": sub_color}
        if halo > 0:
            kw2["stroke_width"] = max(1, halo - 1)
            kw2["stroke_fill"] = halo_c
        draw.text((sx, sy), sub, **kw2)


def draw_table(draw, layer, w, h):
    """对照表格。用于清单、做法对照、参数比较。"""
    box = box2px(layer["box"], w, h)
    x1, y1, x2, y2 = box
    cols = layer.get("columns") or []
    if not cols:
        return
    headers = layer.get("headers") or []
    rows = layer.get("rows") or []

    total_w = x2 - x1
    weights = [float(c.get("w", 1)) for c in cols]
    s = sum(weights) or 1
    xs, acc = [], x1
    for wt in weights:
        xs.append(acc)
        acc += int(total_w * wt / s)
    xs.append(x2)

    row_h = int(layer.get("row_h", 0.062) * h)
    header_h = int(layer.get("header_h", 0.062) * h) if headers else 0

    # 行数太多时自动压行高，绝不静默丢行
    avail = (y2 - y1) - header_h
    if rows and row_h * len(rows) > avail:
        new_h = max(int(0.030 * h), avail // len(rows))
        sys.stderr.write(
            f"[info] 表格 {len(rows)} 行放不下，行高由 {row_h}px 自动压缩到 {new_h}px\n"
        )
        row_h = new_h
    hsize = int(layer.get("header_size", 28))
    csize = int(layer.get("cell_size", 26))
    hcolor = hex2rgb(layer.get("header_color", "#FFFFFF"))
    tcolor = hex2rgb(layer.get("text_color", "#2B2B2B"))
    kcolor = hex2rgb(layer.get("key_color", "#B5563C"))
    hbg = hex2rgb(layer.get("header_bg", "#B5563C"))
    zebra = layer.get("zebra")
    line_c = layer.get("line_color")

    y = y1
    if headers:
        draw.rectangle([x1, y, x2, y + header_h], fill=hbg)
        fh = load_font("hei", hsize)
        for i, htxt in enumerate(headers[: len(cols)]):
            draw.text((xs[i] + int(layer.get("cell_pad", 0.018) * w), y + header_h // 2 - hsize // 2),
                      str(htxt), font=fh, fill=hcolor)
        y += header_h

    for ri, row in enumerate(rows):
        if y + row_h > y2 + 2:
            sys.stderr.write(
                f"[warn] 表格超出指定区域，已在第 {ri} 行截断（共 {len(rows)} 行，建议减少行数或调小 row_h）\n"
            )
            break
        if zebra and ri % 2 == 1:
            draw.rectangle([x1, y, x2, y + row_h], fill=hex2rgb(zebra))
        for ci, cell in enumerate(row[: len(cols)]):
            pad = int(layer.get("cell_pad", 0.018) * w)
            cw = xs[ci + 1] - xs[ci] - pad * 2
            fs = csize
            font = load_font("hei" if ci == 0 else "regular", fs)
            lines = wrap_text(draw, str(cell), font, cw)
            while len(lines) * int(fs * 1.28) > row_h - 8 and fs > 16:
                fs -= 2
                font = load_font("hei" if ci == 0 else "regular", fs)
                lines = wrap_text(draw, str(cell), font, cw)
            ty = y + (row_h - len(lines) * int(fs * 1.28)) // 2
            for ln in lines:
                draw.text((xs[ci] + pad, ty), ln, font=font,
                          fill=kcolor if ci == 0 else tcolor)
                ty += int(fs * 1.28)
        if line_c:
            draw.line([x1, y + row_h, x2, y + row_h], fill=hex2rgb(line_c), width=1)
        y += row_h


def draw_bars(draw, layer, w, h):
    """横向条形排行：标签 + 条形 + 数值。用于排行榜、对比图。"""
    box = box2px(layer["box"], w, h)
    x1, y1, x2, y2 = box
    items = layer.get("items") or []
    if not items:
        return

    max_v = float(layer.get("max") or max(float(i.get("value", 0)) for i in items) or 1)
    label_w = float(layer.get("label_w", 0.26)) * (x2 - x1)
    val_w = float(layer.get("value_w", 0.14)) * (x2 - x1)
    size = int(layer.get("size", 36))
    vsize = int(layer.get("value_size", int(size * 0.92)))
    bar_h = int(float(layer.get("bar_h", 0.03)) * h)
    row_h = int(bar_h * float(layer.get("row_gap", 1.7)))
    radius = int(layer.get("radius", bar_h // 2))

    bar_x0 = x1 + label_w
    bar_zone = (x2 - x1) - label_w - val_w
    f = load_font(layer.get("font", "hei"), size)
    fv = load_font(layer.get("value_font", "hei"), vsize)

    label_color = hex2rgb(layer.get("label_color", "#E6E8EC"))
    track_color = layer.get("track_color")
    thr = layer.get("thresholds") or [10, 20]
    palette = layer.get("palette") or {}
    c_low = hex2rgb(palette.get("low", "#7D8C4E"))
    c_mid = hex2rgb(palette.get("mid", "#C9A227"))
    c_high = hex2rgb(palette.get("high", "#C0453B"))

    pad = int(float(layer.get("pad", 0.016)) * w)
    for i, it in enumerate(items):
        ry = y1 + i * row_h
        label = str(it.get("label", ""))
        v = float(it.get("value", 0))

        # 名称右对齐到条形起点
        lw = draw.textlength(label, font=f)
        lc = hex2rgb(it["label_color"]) if it.get("label_color") else label_color
        draw.text((bar_x0 - pad - lw, ry + bar_h // 2 - size // 2), label,
                  font=f, fill=lc)

        # 背景轨道
        if track_color:
            draw.rounded_rectangle(
                [bar_x0, ry, bar_x0 + bar_zone, ry + bar_h],
                radius=radius, fill=hex2rgb(track_color))

        # 条形
        frac = max(0.0, min(1.0, v / max_v)) if max_v else 0
        blen = max(bar_h, int(bar_zone * frac))
        if it.get("color"):
            c = hex2rgb(it["color"])
        elif layer.get("auto_color", True):
            c = c_high if v >= thr[1] else (c_mid if v >= thr[0] else c_low)
        else:
            c = c_mid
        draw.rounded_rectangle([bar_x0, ry, bar_x0 + blen, ry + bar_h],
                               radius=radius, fill=c)

        # 数值贴在条形末端，短条形也不会离得太远
        vt = str(it.get("text") or (int(v) if float(v).is_integer() else v))
        vx = bar_x0 + blen + pad
        if vx + draw.textlength(vt, font=fv) > x2:
            vx = x2 - draw.textlength(vt, font=fv)
        draw.text((vx, ry + bar_h // 2 - vsize // 2), vt, font=fv, fill=c)


# ---------- 主流程 ----------


def render(spec):
    canvas_cfg = spec.get("canvas", {})
    W = int(canvas_cfg.get("w", 1080))
    H = int(canvas_cfg.get("h", 1440))

    base_path = spec.get("base")
    if base_path and os.path.exists(base_path):
        base = Image.open(base_path).convert("RGB")
        canvas = fit_cover(base, W, H).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (W, H), hex2rgb(spec.get("bg", "#111114")))

    for layer in spec.get("layers", []):
        t = layer.get("type")

        if t == "image":
            p = layer.get("path")
            if not p or not os.path.exists(p):
                continue
            box = box2px(layer["box"], W, H)
            tw, th = box[2] - box[0], box[3] - box[1]
            if tw <= 0 or th <= 0:
                continue
            photo = Image.open(p).convert("RGB")
            fit = layer.get("fit", "cover")
            anchor = layer.get("anchor", "center")
            photo = (
                fit_cover(photo, tw, th, anchor)
                if fit == "cover"
                else fit_contain(photo, tw, th)
            )

            radius = int(layer.get("radius", 0))
            if radius > 0:
                photo = photo.convert("RGBA")
                photo.putalpha(rounded_mask(photo.size, radius))
            else:
                photo = photo.convert("RGBA")

            if layer.get("shadow"):
                add_shadow(
                    canvas,
                    (tw, th),
                    radius,
                    int(layer.get("shadow_blur", 18)),
                    (box[0], box[1] + int(layer.get("shadow_offset", 10))),
                    int(layer.get("shadow_alpha", 90)),
                )
            if layer.get("border"):
                bw = int(layer.get("border_width", 4))
                bd = ImageDraw.Draw(canvas)
                bd.rounded_rectangle(
                    [box[0], box[1], box[2], box[3]],
                    radius=radius,
                    outline=hex2rgb(layer.get("border")),
                    width=bw,
                )
            canvas.alpha_composite(photo, (box[0], box[1]))

        elif t == "scrim":
            box = box2px(layer["box"], W, H)
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(overlay)
            d.rectangle(
                [box[0], box[1], box[2], box[3]],
                fill=hex2rgb(layer.get("color", "#000000"), int(layer.get("alpha", 120))),
            )
            canvas.alpha_composite(overlay)

        elif t == "gradient":
            box = box2px(layer["box"], W, H)
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw > 0 and bh > 0:
                col = hex2rgb(layer.get("color", "#000000"))
                a1 = int(layer.get("from_alpha", 0))
                a2 = int(layer.get("to_alpha", 200))
                ease = float(layer.get("ease", 1.6))
                strip = Image.new("RGBA", (1, bh))
                for yy in range(bh):
                    t = (yy / max(1, bh - 1)) ** ease
                    a = int(a1 + (a2 - a1) * t)
                    strip.putpixel((0, yy), (col[0], col[1], col[2], a))
                canvas.alpha_composite(strip.resize((bw, bh), Image.NEAREST), (box[0], box[1]))

        elif t == "text":
            draw_text_block(canvas, layer, W, H)

        elif t == "pin":
            draw_pin(ImageDraw.Draw(canvas), layer, W, H)

        elif t == "table":
            draw_table(ImageDraw.Draw(canvas), layer, W, H)

        elif t == "bars":
            if not layer.get("label_color"):
                luma = _region_luma(canvas, box2px(layer["box"], W, H))
                layer = dict(layer, label_color="#2B2B2E" if luma > 150 else "#E6E8EC")
            draw_bars(ImageDraw.Draw(canvas), layer, W, H)

    out = spec.get("out", "out.jpg")
    quality = int(spec.get("quality", 92))
    canvas.convert("RGB").save(out, quality=quality, subsampling=0)
    return out, (W, H)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args = ap.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        spec = json.load(f)

    # 支持单个对象，也支持数组（多图系列，一次出完）
    if isinstance(spec, list):
        items = []
        for i, s in enumerate(spec, 1):
            s = expand_preset(s)
            if not s.get("out"):
                s["out"] = os.path.join(
                    os.path.dirname(args.config) or ".", f"series_{i:02d}.jpg"
                )
            out, size = render(s)
            items.append({"out": os.path.abspath(out), "size": size})
        print(json.dumps({"ok": True, "count": len(items), "items": items}, ensure_ascii=False))
    else:
        spec = expand_preset(spec)
        out, size = render(spec)
        print(json.dumps({"ok": True, "out": os.path.abspath(out), "size": size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
