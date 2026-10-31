#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出图前后自检。

出图前查配置：坐标越界、文字层重叠、表格行数、字号过小。
出图后查成品：尺寸、是否全黑全白、底部大面积空白。

用法：
    python scripts/check.py --config spec.json
    python scripts/check.py --image out.jpg
    python scripts/check.py --config spec.json --image out.jpg

有问题退出码 1，无问题退出码 0。
"""

import argparse
import json
import os
import sys

try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from compose import expand_preset
except Exception:
    expand_preset = None


def _expand(spec):
    """preset 简版配置先展开成图层，否则检查不到东西"""
    if isinstance(spec, dict) and spec.get("preset") and expand_preset:
        try:
            return expand_preset(spec)
        except Exception:
            return spec
    return spec


def overlap_ratio(b1, b2):
    """两个 box 的相交面积占较小那个的比例"""
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    a1 = max(1e-9, (b1[2] - b1[0]) * (b1[3] - b1[1]))
    a2 = max(1e-9, (b2[2] - b2[0]) * (b2[3] - b2[1]))
    return inter / min(a1, a2)


def check_spec(spec):
    issues = []
    warns = []
    if not isinstance(spec, dict):
        return ["配置根节点应该是对象"], warns

    layers = spec.get("layers") or []
    if not layers:
        issues.append("没有任何图层，出图会是空白的")

    texts = []
    for i, l in enumerate(layers):
        t = l.get("type")
        if t not in ("image", "scrim", "gradient", "text", "pin", "table", "bars"):
            issues.append(f"层{i}：未知类型 {t!r}")
        box = l.get("box")
        if t != "pin" and box is None:
            issues.append(f"层{i}({t})：缺少 box")
            continue
        if box:
            if len(box) != 4:
                issues.append(f"层{i}：box 应为 4 个数")
                continue
            x1, y1, x2, y2 = box
            # 允许 ±0.06 的出血位（微调图片位置常用），超出才报错
            if not (-0.06 <= x1 < x2 <= 1.06 and -0.06 <= y1 < y2 <= 1.06):
                issues.append(f"层{i}({t})：box 越界或反向 {box}")
            if t == "text" and l.get("text"):
                sz = l.get("size", 0)
                if sz < 18:
                    warns.append(f"层{i}：字号 {sz}px 偏小，手机上可能看不清")
                texts.append((i, box, str(l["text"])[:14], sz))

        if t == "text" and l.get("size") and box:
            h_px = (box[3] - box[1]) * int((spec.get("canvas") or {}).get("h", 1440))
            if h_px < l["size"]:
                issues.append(
                    f"层{i}：box 高度 {int(h_px)}px 小于字号 {l['size']}px，文字会被裁掉")

        if t == "table":
            rows = l.get("rows") or []
            ch = int((spec.get("canvas") or {}).get("h", 1440))
            avail = (box[3] - box[1]) * ch - int(l.get("header_h", 0.06) * ch)
            need = int(l.get("row_h", 0.062) * ch) * len(rows)
            if need > avail * 1.02:
                warns.append(
                    f"层{i}(table)：{len(rows)} 行需要 {need}px，区域只有 {int(avail)}px，行高会被自动压缩")

        if t == "bars":
            items = l.get("items") or []
            if not items:
                issues.append(f"层{i}(bars)：items 为空")
            else:
                ch = int((spec.get("canvas") or {}).get("h", 1440))
                bh = int(l.get("bar_h", 0.03) * ch)
                gap = float(l.get("row_gap", 1.7))
                need = int(bh * gap) * len(items)
                avail = (box[3] - box[1]) * ch
                if need > avail * 1.02:
                    issues.append(
                        f"层{i}(bars)：{len(items)} 行需要 {need}px，区域只有 {int(avail)}px，会溢出")

    # 文字层重叠
    for a in range(len(texts)):
        for b in range(a + 1, len(texts)):
            r = overlap_ratio(texts[a][1], texts[b][1])
            if r > 0.40:
                issues.append(
                    f"文字重叠：层{texts[a][0]}「{texts[a][2]}」与层{texts[b][0]}「{texts[b][2]}」"
                    f"重叠 {r:.0%}，一定会糊在一起")

    return issues, warns


def check_image(path):
    issues = []
    warns = []
    if not os.path.exists(path):
        return [f"找不到图片：{path}"], warns
    if Image is None:
        return ["缺少 Pillow，无法检查图片"], warns

    im = Image.open(path)
    w, h = im.size
    if abs(w / h - 0.75) > 0.02:
        warns.append(f"尺寸 {w}x{h}，不是标准 3:4（1080x1440 或等比例）")

    g = im.convert("L")
    hist = g.histogram()
    total = sum(hist) or 1
    if sum(hist[0:6]) / total > 0.98:
        issues.append("整张图接近全黑，可能是图层顺序或底色出错")
    if sum(hist[250:]) / total > 0.98:
        warns.append("整张图接近纯白，确认内容是否真的画上去了")

    # 底部空白比例
    small = g.copy()
    small.thumbnail((120, 160))
    sw, sh = small.size
    bg = small.getpixel((2, sh // 2))
    empty_rows = 0
    for y in range(sh - 1, -1, -1):
        row = [small.getpixel((x, y)) for x in range(0, sw, 4)]
        if all(abs(p - bg) <= 4 for p in row):
            empty_rows += 1
        else:
            break
    frac = empty_rows / sh
    if frac > 0.28:
        warns.append(f"底部空白约 {frac:.0%}，偏多，考虑上移内容或加大字号")

    return issues, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config")
    ap.add_argument("--image")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    issues, warns = [], []
    if args.config:
        spec = json.load(open(args.config, encoding="utf-8"))
        specs = spec if isinstance(spec, list) else [spec]
        for i, s in enumerate(specs, 1):
            a, b = check_spec(_expand(s))
            tag = f"#{i} " if len(specs) > 1 else ""
            issues += [tag + x for x in a]
            warns += [tag + x for x in b]
    if args.image:
        a, b = check_image(args.image)
        issues += a
        warns += b

    if not args.config and not args.image:
        print("至少给 --config 或 --image 之一")
        return 2

    if args.json:
        print(json.dumps({"ok": not issues, "issues": issues, "warnings": warns},
                         ensure_ascii=False))
    else:
        for x in issues:
            print(f"[问题] {x}")
        for x in warns:
            print(f"[提醒] {x}")
        print("通过" if not issues else f"共 {len(issues)} 个问题需要修")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
