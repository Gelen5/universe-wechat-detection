#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章抓取器
====================
输入 mp.weixin.qq.com/s/xxx 链接，输出标题+正文到 Markdown 文件。

用法:
    python3 fetch_article.py <文章链接> [-o 输出文件]

输出:
    标准输出打印 TITLE / CHARS / SAVED
    文件内容为纯文本正文（图片位置以 [图] 占位，连续重复段落自动去重）
"""

import sys
import re
import argparse
import urllib.request

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")


def fetch(url, out):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"ERROR: 抓取失败 {e}", file=sys.stderr)
        sys.exit(1)

    # 尝试用 BeautifulSoup（若可用），否则降级正则
    title, body = None, None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1", class_="rich_media_title") or soup.find("h1", id="activity-name")
        title = h1.get_text(strip=True) if h1 else "NO_TITLE"
        content = soup.find("div", id="js_content")
        if content:
            for img in content.find_all("img"):
                img.replace_with("[图]")
            paras = [p.get_text(strip=True) for p in content.find_all(["p", "section"])]
            paras = [p for p in paras if p]
            body = "\n".join(paras)
    except ImportError:
        pass

    if not body:
        m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', html, re.S)
        if m:
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', html, re.S)
        if m:
            raw = re.sub(r"<[^>]+>", "\n", m.group(1))
            body = "\n".join(l.strip() for l in raw.split("\n") if l.strip())
    if not body:
        print("ERROR: 未解析到正文（可能需登录或文章已删除）", file=sys.stderr)
        sys.exit(1)

    # 去重：去掉连续重复的行（微信排版嵌套 section 常见）
    out_lines = []
    for line in body.split("\n"):
        if out_lines and line.strip() == out_lines[-1].strip():
            continue
        out_lines.append(line.strip())
    final_body = "\n".join(out_lines)

    with open(out, "w", encoding="utf-8") as f:
        f.write(final_body)
    print(f"TITLE: {title}")
    print(f"CHARS: {len(final_body.replace(chr(10), ''))}")
    print(f"SAVED: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="微信公众号文章抓取器")
    ap.add_argument("url", help="mp.weixin.qq.com/s/xxx 链接")
    ap.add_argument("-o", "--out", default="article.md", help="输出文件")
    args = ap.parse_args()
    fetch(args.url, args.out)
