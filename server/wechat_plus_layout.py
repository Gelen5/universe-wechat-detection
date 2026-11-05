"""Deterministic layout entry points for the native publisher Skill.

Plus does not author article HTML.  ``render()`` hands the manuscript to the
installed Skill's own Markdown + ``:::module`` DSL pipeline (through
``wechat_plus_skill_layout.render_native``), which runs the Skill converter,
the Skill leaf wrapper and both Skill gates.  The model, when present, only
returns a small layout decision.

The legacy ``THEMES`` / ``choose()`` / ``check()`` contract is preserved so
existing sessions, callers and tests remain valid.  There is deliberately no
silent fallback to a local template: a failure raises and the caller keeps the
user's previous preview.
"""
from __future__ import annotations
import hashlib
import importlib.util
import secrets
import sys
import uuid
from copy import deepcopy
from functools import lru_cache
import markdown
from bs4 import BeautifulSoup, Comment
from . import workbench

THEMES = {
    'clean': {'name':'简约清爽','primary_color':'#263b36','accent_color':'#478674','background':'#f2f8f4','heading':'line'},
    'tech': {'name':'专业科技','primary_color':'#233956','accent_color':'#346fac','background':'#edf4fb','heading':'bar'},
    'warm': {'name':'温暖故事','primary_color':'#513d33','accent_color':'#b67552','background':'#fbf3eb','heading':'soft'},
    'editorial': {'name':'沉稳编辑','primary_color':'#343535','accent_color':'#626b68','background':'#f3f4f2','heading':'minimal'},
}
COLORS = {'蓝':'#346fac','绿':'#39845d','橙':'#b87540','紫':'#775aa0','粉':'#b76882','黑':'#3a3a3a','灰':'#626b68','金':'#9a7133','红':'#a34444'}
KEYWORDS = {'clean':('简约','清爽','清新','极简','简洁'), 'tech':('科技','专业','商务'), 'warm':('温暖','故事','暖色'), 'editorial':('沉稳','编辑','杂志','黑白')}
OPTIONS = ['简约清爽','专业科技','温暖故事','沉稳编辑','帮我选']

# User-facing style identifiers only.  The Skill's own default theme owns every
# rendered colour; these identifiers pick the :::module recipe and the label.
STYLE_NAMES = {
    'ink_gold': '墨金质感',
    'signal_green': '信号绿',
    'navy_gold': '深蓝金',
    'warm_ink': '暖墨米',
}
STYLE_KEYWORDS = {'墨金质感': 'ink_gold', '信号绿': 'signal_green',
                  '深蓝金': 'navy_gold', '暖墨米': 'warm_ink'}
STYLE_OPTIONS = list(STYLE_KEYWORDS)

# The Skill's 29 md2wechat modules (references/layouts.md).  Brand modules are
# listed for the capability panel but never wrapped: they would inject text
# that is not present in the draft and break content preservation.
MODULES = {
    'opening': ('hero','toc','cards','part','label-title'),
    'evidence': ('quote','image-text','image-steps','image-compare','image-annotate'),
    'infographic': ('metrics','compare','steps','timeline','infographic'),
    'judgment': ('verdict','audience-fit','myth-fact','manifesto','bridge'),
    'conversion': ('cta','faq','checklist','notice','summary'),
    'brand': ('author-card','people','series','subscribe'),
}
MODULE_COUNT = sum(len(names) for names in MODULES.values())
# Only containers whose converter wrapper is a plain div are used.  dialogue /
# timeline / module have special parsers that rewrite text, so they are avoided.
CONTAINER_FOR = {'opening':'highlight', 'evidence':'quote', 'infographic':'callout',
                 'judgment':'summary', 'conversion':'callout'}


def _recipe(seed: str, style: str) -> list[dict]:
    """Pick one module from each content-led category, deterministically per seed."""
    digest = hashlib.sha256((seed + style).encode()).hexdigest()
    recipe = []
    for index, (category, names) in enumerate(MODULES.items()):
        container = CONTAINER_FOR.get(category)
        if not container:
            continue
        offset = int(digest[index * 2:index * 2 + 2], 16)
        recipe.append({'category': category, 'name': names[offset % len(names)],
                       'container': container})
    return recipe


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

    # A new formatting request gets a genuinely different design: a fresh
    # visual style, a fresh module recipe and a fresh spacing perturbation.
    # Refinements (colour, alignment, heading emphasis) keep the same design.
    # Naming a visual style is an explicit choice and always wins the draw.
    requested_style = next((key for name, key in STYLE_KEYWORDS.items() if name in request), None)
    if change or fresh or requested_style:
        seed = uuid.uuid4().hex
        candidates = [key for key in STYLE_NAMES if key != previous.get('style')] or list(STYLE_NAMES)
        style = requested_style or candidates[int(hashlib.sha256(seed.encode()).hexdigest()[:2], 16) % len(candidates)]
        theme.update({'variant': seed[:12], 'style': style,
                      'style_name': STYLE_NAMES[style],
                      'modules': _recipe(seed, style),
                      'previous_variant': previous.get('variant') or ''})
    elif previous.get('variant'):
        for key in ('variant', 'style', 'style_name', 'modules'):
            if key in previous:
                theme[key] = previous[key]
    return theme


def _signature(html: str):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup.find_all(string=lambda text:isinstance(text, Comment)):
        node.extract()
    return (soup.get_text(), [node.get('href') for node in soup.find_all('a')],
        [(node.get('src'), node.get('alt')) for node in soup.find_all('img')],
        [node.get_text() for node in soup.find_all('pre')])


def _safe_source(draft: str) -> str:
    """Markdown -> sanitised HTML, used for safety checks and fidelity."""
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
    return str(original)


def render(draft: str, theme: dict, *, trace: dict | None = None,
           generate=None, check_cancelled=None, passthrough=(),
           work_dir=None) -> str:
    """Render through the installed Skill's native Markdown + :::module DSL.

    The model only returns a layout decision (``layout_plan``); the manuscript
    stays Markdown and the Skill's own ``MarkdownConverter`` renders it via
    ``server/skill_preview.py``.  Both Skill gates run before delivery.
    Failures raise -- there is no silent fallback to a local template -- so the
    caller can keep the user's existing preview and show the real reason.
    """
    # Unsafe source HTML is a hard error, never a silent layout fallback.
    _safe_source(draft)
    from . import wechat_plus_skill_layout as native
    return native.render_native(draft, theme, generate=generate,
                                check_cancelled=check_cancelled,
                                passthrough=tuple(passthrough or ()),
                                work_dir=work_dir, trace=trace)


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
    # div containers are produced by the Skill's own official converter.
    allowed = {'image_host_not_wechat', 'div_tag'}
    blocking = [item for item in findings if item.severity in {'error','warn_blocking'} and item.code not in allowed]
    if blocking:
        raise ValueError('排版未通过公众号兼容检查，原预览已保留，请调整正文或稍后重试')
    notes = []
    if any(item.code == 'image_host_not_wechat' for item in findings):
        notes.append('文章含外部图片，粘贴到公众号后请检查图片是否正常显示。')
    if any(item.severity == 'warn' for item in warnings):
        notes.append('请在公众号编辑器中检查手机端排版。')
    return notes
