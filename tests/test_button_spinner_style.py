"""等待态转圈的几何约束。

线上出现过一次：登录按钮上的转圈被压成一个小扁椭圆。原因是 `.button-spinner`
只声明了 width/height，没有 display —— span 默认是行内元素，行内元素忽略
宽高，只剩 4px 边框。`.skill-primary` 恰好是 display:flex（flex item 会被
阻断化），所以那批按钮一直正常，只有普通 button 上暴露出来。

这个测试锁住那条规则必须自带 display，避免以后被"瘦身"掉。
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def _rule(css: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"{selector} 规则不见了"
    return match.group(1)


def test_spinner_is_a_box_not_an_inline_span():
    rule = _rule((STATIC / "style.css").read_text(encoding="utf-8"), ".button-spinner")
    assert "display: inline-block" in rule, "行内元素会忽略宽高，转圈会被压扁"
    assert "width: 14px" in rule and "height: 14px" in rule
    # border 会撑大盒子，不写 border-box 时圆形会变成 18×18 的胖圆。
    assert "box-sizing: border-box" in rule


def test_spinner_has_its_animation():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert "@keyframes spin" in css
    assert "animation: spin" in _rule(css, ".button-spinner")


def test_every_waiting_button_gets_a_space_after_the_spinner():
    """普通 button 里没有 gap，转圈和文字之间必须有一个空格，否则会贴死。"""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert '<span class="button-spinner"></span> ${esc(label)}' in js, (
        "beginButton 里转圈和文案之间少了空格"
    )
