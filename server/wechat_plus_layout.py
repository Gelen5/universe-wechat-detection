"""Deterministic, content-preserving themes for the native publisher Skill."""
from __future__ import annotations
import secrets
import importlib.util
import sys
from functools import lru_cache
from copy import deepcopy
from bs4 import BeautifulSoup, Comment
import markdown
from . import skill_article_adapter, workbench

THEMES = {
    'clean': {'name':'简约清爽','primary_color':'#263b36','accent_color':'#478674','background':'#f2f8f4','heading':'line'},
    'tech': {'name':'专业科技','primary_color':'#233956','accent_color':'#346fac','background':'#edf4fb','heading':'bar'},
    'warm': {'name':'温暖故事','primary_color':'#513d33','accent_color':'#b67552','background':'#fbf3eb','heading':'soft'},
    'editorial': {'name':'沉稳编辑','primary_color':'#343535','accent_color':'#626b68','background':'#f3f4f2','heading':'minimal'},
}
COLORS = {'蓝':'#346fac','绿':'#39845d','橙':'#b87540','紫':'#775aa0','粉':'#b76882','黑':'#3a3a3a','灰':'#626b68','金':'#9a7133','红':'#a34444'}
KEYWORDS = {'clean':('简约','清爽','清新','极简','简洁'), 'tech':('科技','专业','商务'), 'warm':('温暖','故事','暖色'), 'editorial':('沉稳','编辑','杂志','黑白')}
OPTIONS = ['简约清爽','专业科技','温暖故事','沉稳编辑','帮我选']


def choose(request: str, previous: dict | None = None, *, fresh: bool = False, content: str = '') -> dict:
    """Honor supported appearance requests and retain a previous base for refinements."""
    request = str(request or '')[:1000]
    previous = previous if isinstance(previous, dict) else {}
    selected = next((key for key, words in KEYWORDS.items() if any(word in request for word in words)), None)
    explicit_theme = selected is not None
    explicit_color = next((value for name, value in COLORS.items() if name + '色' in request or name + '调' in request), None)
    if not selected and fresh and explicit_color:
        selected = {'#346fac':'tech', '#39845d':'clean', '#b87540':'warm'}.get(explicit_color)
    change = fresh or request.strip() in {'排版','排版看看','开始排版','帮我排版','生成排版'} or any(word in request for word in ('换一种','换一个','换一套','再来一种','帮我选','自动'))
    if not selected and not change and previous.get('id') in THEMES:
        selected = previous['id']
    if not selected:
        text = (content or '')[:6000].lower()
        if any(word in text for word in ('科技','技术','工具','教程','人工智能','ai','软件')):
            candidates = ['tech','clean','editorial']
        elif any(word in text for word in ('故事','生活','家人','成长','回忆','心情')):
            candidates = ['warm','clean','editorial']
        else:
            candidates = list(THEMES)
        choices = [key for key in candidates if key != previous.get('id')] or candidates
        selected = secrets.choice(choices)
    theme = deepcopy(THEMES[selected]); theme['id'] = selected
    if not explicit_theme and not change and previous.get('id') == selected:
        for key in ('accent_color', 'no_heading_background', 'prominent_heading', 'heading_align'):
            if key in previous:
                theme[key] = previous[key]
    if explicit_color:
        theme['accent_color'] = explicit_color
    if any(word in request for word in ('不要底色','不要背景色','无底色','不带底色')):
        theme['no_heading_background'] = True
    if any(word in request for word in ('标题醒目','标题突出','标题显眼')):
        theme['prominent_heading'] = True
    if any(word in request for word in ('标题居中','居中标题')):
        theme['heading_align'] = 'center'
    elif any(word in request for word in ('标题左对齐','标题靠左')):
        theme['heading_align'] = 'left'
    return theme


def _signature(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.find_all(string=lambda text:isinstance(text, Comment)):
        node.extract()
    return (soup.get_text(), [node.get('href') for node in soup.find_all('a')],
        [(node.get('src'), node.get('alt')) for node in soup.find_all('img')],
        [node.get_text() for node in soup.find_all('pre')])


def render(draft: str, theme: dict) -> str:
    """Use the Skill converter's inline styling without its text-altering stages."""
    _, workflow = skill_article_adapter._skill_modules()
    from toolkit.converter import MarkdownConverter
    from toolkit.leaf import wrap_cjk_leaf
    source = markdown.markdown(draft, extensions=['fenced_code','tables','nl2br','sane_lists'])
    original = BeautifulSoup(source, 'html.parser')
    allowed = set('p h1 h2 h3 h4 h5 h6 strong b em i s del br hr blockquote ul ol li a img table thead tbody tfoot tr td th pre code div section span'.split())
    for tag in original.find_all(True):
        if tag.name not in allowed:
            raise ValueError('正文包含暂不支持的 HTML，请调整后重新排版；原正文和预览已保留')
        for name in list(tag.attrs):
            if name not in {'href','src','alt','title','colspan','rowspan','start'}:
                del tag.attrs[name]
        for attr in ('href','src'):
            value = str(tag.get(attr) or '')
            if value and value.lower().strip().startswith(('javascript:','vbscript:','data:text/html')):
                raise ValueError('正文包含不安全的链接，无法生成排版；原正文和预览已保留')
    source = str(original)
    converter = MarkdownConverter(theme)
    styled = converter._step9_inline_styles(converter._step5_image_process(source))
    soup = BeautifulSoup(styled, 'html.parser')
    color, background = theme['accent_color'], theme['background']
    heading = theme['heading']
    for tag in soup.find_all(['h1','h2','h3']):
        if heading == 'bar':
            style = f'font-size:19px;font-weight:700;color:{theme["primary_color"]};margin:1.5em 0 .8em;padding:8px 12px;border-left:4px solid {color};'
        elif heading == 'soft' and not theme.get('no_heading_background'):
            style = f'font-size:18px;font-weight:700;color:{theme["primary_color"]};margin:1.5em 0 .8em;padding:9px 13px;background:{background};border-radius:6px;'
        elif heading == 'minimal':
            style = f'font-size:19px;font-weight:700;color:{theme["primary_color"]};margin:1.6em 0 .8em;padding:0;border:0;'
        else:
            style = f'font-size:19px;font-weight:700;color:{theme["primary_color"]};margin:1.5em 0 .8em;padding:0 0 7px;border-bottom:1px solid {color};'
        if theme.get('prominent_heading'):
            style += f'color:{color};'
        if theme.get('heading_align') in {'left', 'center'}:
            style += f'text-align:{theme["heading_align"]};'
        tag['style'] = style
    for tag in soup.find_all('blockquote'):
        tag['style'] = f'margin:1.2em 0;padding:12px 16px;border-left:3px solid {color};background:{background};color:{theme["primary_color"]};'
    for tag in soup.find_all('p'):
        tag['style'] = 'margin:1em 0;line-height:1.9;color:#333333;font-size:16px;'
    for tag in soup.find_all('img'):
        tag['style'] = 'max-width:100%;height:auto;display:inline-block;'
        tag.attrs.pop('data-src', None)
    if _signature(source) != _signature(str(soup)):
        raise ValueError('排版内容与原文不一致，已保留原正文和预览')
    final = wrap_cjk_leaf('<section style="font-size:16px;line-height:1.9;color:#333333;word-wrap:break-word;">'+str(soup)+'</section>')
    if _signature(source) != _signature(final):
        raise ValueError('排版内容与原文不一致，已保留原正文和预览')
    return final


@lru_cache(maxsize=8)
def _checker(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError('排版检查暂不可用，原预览已保留')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def check(html: str) -> list[str]:
    """Run the native Skill's checks; retain third-party images as a visible warning."""
    root = workbench.SKILL_DIR / 'scripts'
    try:
        compliance = _checker(str(root / 'wechat_compliance_check.py'), '_plus_wechat_compliance')
        quality = _checker(str(root / 'layout_quality_check.py'), '_plus_layout_quality')
        findings = compliance.analyze(html)
        warnings = quality.analyze_html(html)
    except (OSError, ImportError, AttributeError) as error:
        raise ValueError('排版检查暂不可用，原预览已保留') from error
    blocking = [item for item in findings if item.severity in {'error','warn_blocking'} and item.code != 'image_host_not_wechat']
    if blocking:
        raise ValueError('排版未通过公众号兼容检查，原预览已保留，请调整正文或稍后重试')
    notes = []
    if any(item.code == 'image_host_not_wechat' for item in findings):
        notes.append('文章含外部图片，粘贴到公众号后请检查图片是否正常显示。')
    if any(item.severity == 'warn' for item in warnings):
        notes.append('请在公众号编辑器中检查手机端排版。')
    return notes
