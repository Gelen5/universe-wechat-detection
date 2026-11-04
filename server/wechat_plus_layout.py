"""Deterministic, content-preserving layout for the native publisher Skill.

Plus drives the Skill's full MarkdownConverter pipeline and composes a fresh
module recipe for every formatting request.  The 29 modules and four visual
styles come from ``vendor/skills/weChat-autoCreate/references/``; every design
decision lives in this application-side module, no Skill source is modified.

Legacy ``THEMES`` and the four public functions keep their original contract so
existing sessions, callers and tests remain valid.  A theme produced by
``choose()`` carries ``variant``/``style``/``modules`` and takes the pipeline
path; a bare ``THEMES`` dict takes the original parameterised template path.
"""
from __future__ import annotations
import hashlib
import importlib.util
import logging
import re
import secrets
import sys
import uuid
from copy import deepcopy
from functools import lru_cache
from bs4 import BeautifulSoup, Comment
import markdown
from . import skill_article_adapter, workbench

LOG = logging.getLogger(__name__)

THEMES = {
    'clean': {'name':'简约清爽','primary_color':'#263b36','accent_color':'#478674','background':'#f2f8f4','heading':'line'},
    'tech': {'name':'专业科技','primary_color':'#233956','accent_color':'#346fac','background':'#edf4fb','heading':'bar'},
    'warm': {'name':'温暖故事','primary_color':'#513d33','accent_color':'#b67552','background':'#fbf3eb','heading':'soft'},
    'editorial': {'name':'沉稳编辑','primary_color':'#343535','accent_color':'#626b68','background':'#f3f4f2','heading':'minimal'},
}
COLORS = {'蓝':'#346fac','绿':'#39845d','橙':'#b87540','紫':'#775aa0','粉':'#b76882','黑':'#3a3a3a','灰':'#626b68','金':'#9a7133','红':'#a34444'}
KEYWORDS = {'clean':('简约','清爽','清新','极简','简洁'), 'tech':('科技','专业','商务'), 'warm':('温暖','故事','暖色'), 'editorial':('沉稳','编辑','杂志','黑白')}
OPTIONS = ['简约清爽','专业科技','温暖故事','沉稳编辑','帮我选']

# Color tokens lifted from the Skill's four visual-style references.  One
# restrained accent per article, neutral body text, no decorative dark blocks.
STYLES = {
    'ink_gold': {'name':'墨金质感', 'primary_color':'#1D1D1F', 'body_color':'#4A4A4F',
                 'accent_color':'#C9A962', 'background':'#F7F7F5', 'soft':'#FBF8F1',
                 'line':'#E5E5E5', 'heading':'line'},
    'signal_green': {'name':'信号绿', 'primary_color':'#0A0A0A', 'body_color':'#3A3A3A',
                     'accent_color':'#059669', 'background':'#F5F5F5', 'soft':'#ECFDF5',
                     'line':'#CCCCCC', 'heading':'bar'},
    'navy_gold': {'name':'深蓝金', 'primary_color':'#0C2340', 'body_color':'#334155',
                  'accent_color':'#D4A017', 'background':'#E2E8F0', 'soft':'#FFFBEB',
                  'line':'#CBD5E1', 'heading':'bar'},
    'warm_ink': {'name':'暖墨米', 'primary_color':'#2C2420', 'body_color':'#5C4A3E',
                 'accent_color':'#B8860B', 'background':'#FAF6F1', 'soft':'#F0EBE3',
                 'line':'#DDD3C8', 'heading':'soft'},
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
        candidates = [key for key in STYLES if key != previous.get('style')] or list(STYLES)
        style = requested_style or candidates[int(hashlib.sha256(seed.encode()).hexdigest()[:2], 16) % len(candidates)]
        palette = STYLES[style]
        theme['primary_color'] = palette['primary_color']
        theme['background'] = palette['background']
        theme['heading'] = palette['heading']
        if not explicit_color:
            theme['accent_color'] = palette['accent_color']
        theme.update({'variant': seed[:12], 'style': style,
                      'style_name': palette['name'], 'modules': _recipe(seed, style)})
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
    """Markdown -> sanitised HTML, reused by both rendering paths."""
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


def _wrappable(block: str) -> bool:
    """Only prose blocks become modules; structural blocks must stay untouched."""
    stripped = block.lstrip()
    return not stripped.startswith(('#', '```', '~~~', '![', '|', '<', '---', '==='))


def _wrap_blocks(draft: str, recipe: list[dict]) -> tuple[str, list[dict]]:
    """Wrap existing blocks in Skill containers; never inject visible text.

    Returns the wrapped markdown plus the recipe in document order, because
    the converter strips ``class`` from its wrappers before the final HTML is
    assembled.  The order is what lets us style each module differently.
    """
    blocks = [block.strip() for block in re.split(r'\n\s*\n', draft) if block.strip()]
    if not blocks:
        return draft, []
    safe = [index for index, block in enumerate(blocks) if _wrappable(block)]
    if not safe:
        return draft, []  # a pure heading/code/table document gets no cards
    last = safe[-1]
    first_body = safe[0]

    def pick(predicate, fallback):
        return next((index for index in safe if predicate(blocks[index])), fallback)

    picks: dict[int, dict] = {}
    for item in recipe:
        category = item['category']
        if category == 'opening':
            index = first_body  # the H1 stays outside any card
        elif category == 'evidence':
            index = pick(lambda block: block.startswith('>'), safe[min(1, len(safe) - 1)])
        elif category == 'infographic':
            index = pick(lambda block: bool(re.match(r'^\s*(?:[-*]\s|\d+\.)', block)),
                         safe[min(2, len(safe) - 1)])
        elif category == 'judgment':
            index = safe[max(0, len(safe) - 2)]
        else:
            index = last
        picks.setdefault(index, item)
    rendered = []
    for index, block in enumerate(blocks):
        item = picks.get(index)
        rendered.append(f":::{item['container']}\n{block}\n:::" if item else block)
    return '\n\n'.join(rendered), [picks[index] for index in sorted(picks)]


def _container_css(theme: dict, category: str = '') -> str:
    """One restrained treatment per module category, never a uniform card wall."""
    paint = STYLES.get(theme.get('style'), STYLES['ink_gold'])
    accent = theme.get('accent_color') or paint['accent_color']
    soft, line, body = paint['soft'], paint['line'], paint['body_color']
    common = f'color:{body};'
    if category == 'opening':
        return (f'margin:1.1em 0 1.7em;padding:0 0 12px;border:0;'
                f'border-bottom:1px solid {line};background:transparent;{common}')
    if category == 'evidence':
        return (f'margin:1.4em 0;padding:10px 16px;border:0;'
                f'border-left:3px solid {accent};background:{soft};{common}')
    if category == 'infographic':
        return (f'margin:1.4em 0;padding:14px 16px;border:1px solid {line};'
                f'border-radius:10px;background:{soft};{common}')
    if category == 'judgment':
        return (f'margin:1.4em 0;padding:11px 0;border:0;'
                f'border-top:1px solid {line};border-bottom:1px solid {line};'
                f'background:transparent;{common}')
    return (f'margin:1.6em 0 1em;padding:12px 16px;border:0;'
            f'border-left:2px solid {accent};border-radius:0 8px 8px 0;'
            f'background:{soft};{common}')


def _converter_class(theme: dict, ordered: list[dict]):
    """Full 16-step converter with text-mutating steps disabled in-app."""
    skill_article_adapter._skill_modules()
    from toolkit.converter import MarkdownConverter

    class FaithfulConverter(MarkdownConverter):
        def _step1_preprocess_containers(self, text):
            result = super()._step1_preprocess_containers(text)
            counter = {'index': 0}

            def decorate(match):
                item = ordered[counter['index']] if counter['index'] < len(ordered) else {}
                counter['index'] += 1
                # The Skill hard-codes orange/green/blue cards.  Replace them
                # while ``class`` still exists, using this article's palette
                # and the per-module treatment chosen by the recipe.
                return match.group(1) + 'style="' + _container_css(theme, item.get('category', '')) + '"'

            return re.sub(r'(<div class="[^"]*-container" )style="[^"]*"', decorate, result)

        def _step2_cjk_spacing(self, text):
            return text  # CJK spacing inserts characters into the article

        def _step4_code_enhance(self, html):
            # Upstream writes line numbers and a language label into <pre>,
            # changing the article text.  Presentation is fine, content is not.
            return re.sub(r'<pre\b[^>]*>',
                          '<pre style="margin:1.2em 0;padding:14px 16px;'
                          'border-radius:8px;background:#F5F5F5;overflow-x:auto;'
                          'font-size:13px;line-height:1.7;">', html)

        def _step6_bold_punctuation_move(self, html):
            return html  # moves punctuation out of emphasis, altering the text

        def _step7_list_to_section(self, html):
            return html  # injects "•" bullet characters not present in the draft

        def _step8_external_links_to_footnotes(self, html):
            return html  # footnotes add text that was never in the draft

        def _step13_aigc_declaration(self, html):
            return html  # no declaration and no extra visible copy

        def _step14_summary(self, html):
            return html

        def _step15_final_cleanup(self, html):
            # The upstream step decodes entities and can corrupt code blocks.
            return re.sub(r'<br\s*/?>', '<br/>', html).strip()

    return FaithfulConverter


def _apply_style(soup: BeautifulSoup, theme: dict) -> None:
    paint = STYLES.get(theme.get('style'), STYLES['ink_gold'])
    primary = theme.get('primary_color') or paint['primary_color']
    accent = theme.get('accent_color') or paint['accent_color']
    background = theme.get('background') or paint['background']
    soft = paint['soft']
    body = paint['body_color']
    line = paint['line']
    heading = theme.get('heading') or paint['heading']
    for tag in soup.find_all(['h1','h2','h3']):
        if heading == 'bar':
            style = f'font-size:19px;font-weight:700;color:{primary};margin:1.5em 0 .8em;padding:8px 12px;border-left:4px solid {accent};background:{soft};'
        elif heading == 'soft' and not theme.get('no_heading_background'):
            style = f'font-size:18px;font-weight:700;color:{primary};margin:1.5em 0 .8em;padding:9px 13px;background:{soft};border-radius:6px;'
        elif heading == 'minimal':
            style = f'font-size:19px;font-weight:700;color:{primary};margin:1.6em 0 .8em;padding:0;border:0;'
        else:
            style = f'font-size:19px;font-weight:700;color:{primary};margin:1.5em 0 .8em;padding:0 0 7px;border-bottom:1px solid {accent};'
        if theme.get('prominent_heading'):
            style += f'color:{accent};'
        if theme.get('heading_align') in {'left', 'center'}:
            style += f'text-align:{theme["heading_align"]};'
        tag['style'] = style
    for tag in soup.find_all('blockquote'):
        # The evidence container already carries the tint and the rule; a
        # second full card inside it would read as a decorative block wall.
        tag['style'] = f'margin:.5em 0;padding:2px 0 2px 12px;border-left:2px solid {accent};background:transparent;color:{body};'
    # Container styles are applied in step 1 while the Skill's class attribute
    # still exists.  Do not overwrite them here: the converter strips classes
    # later, so a second pass could no longer tell modules apart.
    for tag in soup.find_all('p'):
        tag['style'] = f'margin:1em 0;line-height:1.9;color:{body};font-size:16px;'
    for tag in soup.find_all('img'):
        tag['style'] = 'max-width:100%;height:auto;display:inline-block;'
        tag.attrs.pop('data-src', None)


def _render_pipeline(draft: str, theme: dict) -> str:
    source = _safe_source(draft)
    baseline = _signature(source)
    wrapped, ordered = _wrap_blocks(draft, theme['modules'])
    pipeline_theme = dict(theme, css_perturbation=True, aigc_declaration=False)
    converter = _converter_class(pipeline_theme, ordered)()
    rendered = converter.convert(wrapped)
    soup = BeautifulSoup(rendered, 'html.parser')
    _apply_style(soup, theme)
    final = str(soup)
    if _signature(final) != baseline:
        raise ValueError('排版内容与原文不一致，已保留原正文和预览')
    return f'<!-- plus-layout:{theme.get("variant", "")} -->\n{final}'


def _render_legacy(draft: str, theme: dict) -> str:
    """Original parameterised template, kept as the safe fallback path."""
    skill_article_adapter._skill_modules()
    from toolkit.converter import MarkdownConverter
    from toolkit.leaf import wrap_cjk_leaf
    source = _safe_source(draft)
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


def render(draft: str, theme: dict) -> str:
    """Render with the Skill pipeline when a module recipe is present."""
    if not theme.get('modules'):
        return _render_legacy(draft, theme)
    try:
        return _render_pipeline(draft, theme)
    except (ValueError, ImportError, AttributeError, OSError, TypeError) as exc:
        # A layout failure must never cost the user their existing preview,
        # but it must be visible in logs instead of silently looking "fine".
        LOG.warning('plus layout pipeline fell back to legacy: %s: %s',
                    type(exc).__name__, exc)
        return _render_legacy(draft, theme)


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
