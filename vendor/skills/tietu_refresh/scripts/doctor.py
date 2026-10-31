#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境自检：确认当前这台机器 / 这个云端环境能不能跑贴图合成。

用法：
    python scripts/doctor.py
    python scripts/doctor.py --json     # 只输出机器可读结果

检查五项：Python 版本、Pillow、中文字体、输出目录可写、实际渲染出图。
任何一项不过，脚本会直接告诉你该怎么办。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIRS = [
    r"C:\Windows\Fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.join(HERE, "fonts"),
    os.path.join(HERE, "..", "fonts"),
]
FONT_CANDIDATES = [
    "msyhbd.ttc", "msyh.ttc", "msyhl.ttc", "simhei.ttf", "simsun.ttc",
    "PingFang.ttc", "NotoSansCJKsc-Regular.otf", "NotoSansCJK-Regular.ttc",
    "NotoSansSC-Regular.ttf", "SourceHanSansSC-Regular.otf",
    "wqy-zenhei.ttc", "DroidSansFallbackFull.ttf",
]


def find_font():
    for d in FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for name in FONT_CANDIDATES:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    # 兜底：递归找任何一个 CJK 字体
    for d in FONT_DIRS:
        if not d or not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                low = f.lower()
                if any(k in low for k in ("notosanscjk", "notosanssc", "sourcehansans",
                                          "msyh", "simhei", "pingfang", "wqy", "droidsansfallback")):
                    return os.path.join(root, f)
            break
    return None


def check():
    items = []

    def add(name, ok, detail, fix=""):
        items.append({"item": name, "ok": ok, "detail": detail, "fix": fix})

    # 1 Python
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 8)
    add("Python", ok, ver, "" if ok else "需要 3.8 及以上")

    # 2 Pillow
    pillow_ver = None
    try:
        import PIL
        pillow_ver = getattr(PIL, "__version__", "?")
        add("Pillow", True, pillow_ver)
    except ImportError:
        add("Pillow", False, "未安装", f"运行：{sys.executable} -m pip install pillow")

    # 3 中文字体
    fp = find_font()
    add("中文字体", bool(fp), fp or "没找到",
        "" if fp else "系统无中文字体 → 自动切换 AI 直出模式；也可自行放一个中文 TTF 到 scripts/fonts/")

    # 4 写文件（输出到当前目录，不建临时文件）
    out_path = os.path.join(os.getcwd(), "tietu_selftest.jpg")
    try:
        with open(out_path, "wb") as f:
            f.write(b"selftest")
        add("写文件", True, os.getcwd())
    except Exception as e:
        add("写文件", False, str(e)[:80], "换一个有写权限的目录再跑")

    # 5 实拍一张（直接调用渲染函数，不创建子进程）
    if fp and pillow_ver:
        try:
            sys.path.insert(0, HERE)
            import compose as _c
            _c.load_font.cache_clear()

            tmp = os.path.join(os.getcwd(), "tietu_selftest.jpg")
            spec = {
                "canvas": {"w": 540, "h": 720},
                "bg": "#111114",
                "layers": [
                    {"type": "text", "text": "自检通过", "box": [0.1, 0.35, 0.9, 0.6],
                     "size": 80, "auto_size": False, "color": "#FFFFFF",
                     "align": "center", "valign": "center"},
                    {"type": "bars", "box": [0.15, 0.68, 0.85, 0.9],
                     "items": [{"label": "甲乙", "value": 8}, {"label": "丙丁", "value": 3}],
                     "max": 10, "size": 26, "value_size": 24},
                ],
                "out": tmp,
            }
            _c.render(_c.expand_preset(spec))
            from PIL import Image
            im = Image.open(tmp).convert("L")
            hist = im.histogram()
            bright = sum(hist[200:]) / max(1, sum(hist))
            if bright < 0.001:
                raise RuntimeError("出图是全黑，渲染异常")
            add("实拍出图", True, f"{tmp}（文字像素 {bright:.2%}）")
        except Exception as e:
            add("实拍出图", False, str(e)[:160], "把上面的报错发给我")
    else:
        add("实拍出图", False, "前置项未通过，跳过", "先修上面两项")

    return {"ok": all(i["ok"] for i in items), "items": items}


def main():
    res = check()
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False))
        return 0 if res["ok"] else 1

    print("=" * 46)
    print(" 贴图翻新 · 环境自检")
    print("=" * 46)
    for i in res["items"]:
        mark = "OK  " if i["ok"] else "FAIL"
        print(f"[{mark}] {i['item']:<10} {i['detail']}")
        if not i["ok"] and i["fix"]:
            print(f"         -> {i['fix']}")
    print("-" * 46)
    if res["ok"]:
        print("结论：这个环境可以直接用。")
    else:
        print("结论：还不能用，按上面 -> 后面的提示处理。修不好就把这段发我。")
    print("=" * 46)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
