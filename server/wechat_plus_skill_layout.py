"""Skill-native DSL layout host for the Plus workspace (application side only).

Plus never composes article HTML itself.  The model only returns a small
layout *decision* (module names, decoration budget, one emphasis sentence);
the manuscript travels as Markdown plus the Skill's ``:::module`` DSL and the
installed Skill's own ``MarkdownConverter`` renders the HTML.  Two Skill gates
(``layout_quality_check.py`` and ``wechat_compliance_check.py``) then decide
whether the fragment may be delivered.

The chain mirrors the proven old-workbench path (``server/workbench.py``
``_typeset_dsl``) but is implemented independently: no workbench private
helper is imported, no Skill source is modified, and no inline styles are
authored here.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup

from . import skill_fine_layout
from . import workbench

REFERENCES = (
    'references/mobile-layout-quality.md',
    'references/wechat-html-spec.md',
    'references/components.md',
    'references/article-template.html',
)
PLAN_FIELDS = ('first_screen', 'components', 'decoration_budget', 'emphasis',
               'image_evidence', 'line_break_risks')
MAX_COMPONENTS = 8
DEFAULT_PLAN = {
    'first_screen': '',
    'components': [],
    'decoration_budget': 0,
    'emphasis': '',
    'image_evidence': '',
    'line_break_risks': '',
    'source': 'default',
}


def layout_plan(draft: str, theme: dict, generate, *,
                check_cancelled=None, passthrough=()) -> dict:
    """Ask the model for a layout decision only; the prose is never sent back.

    ``generate`` is Plus's JSON-dict generator.  With no generator (direct
    calls, tests, previews) a conservative default plan is used; the article
    still goes through the same native converter and gates.  Exceptions other
    than ``passthrough`` are not swallowed.
    """
    if generate is None:
        return dict(DEFAULT_PLAN)
    if check_cancelled:
        check_cancelled()
    from . import skill_runtime
    instructions, manifest = skill_runtime.context(workbench.SKILL_DIR, REFERENCES)
    prompt = f'''{instructions}
当前只生成排版决策，不改正文。必须使用 weChat-autoCreate 的模式B（Markdown + :::module DSL），只选择与内容有功能关系的模块，不堆装饰。
正文：{draft}
用户风格选择：{theme.get('style_name') or theme.get('name') or ''}
返回JSON：{{"first_screen":"首屏安排","components":["callout","quote"],"decoration_budget":3,"emphasis":"需要强调的一句正文原文或空字符串","image_evidence":"图文对应说明","line_break_risks":"断行风险"}}'''
    try:
        result = generate(prompt)
    except passthrough:
        raise
    if isinstance(result, str):
        result = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', result.strip()))
    if not isinstance(result, dict):
        raise ValueError('排版决策不是 JSON 对象')
    plan = {key: result.get(key) for key in PLAN_FIELDS}
    components = plan.get('components') or []
    if not isinstance(components, list):
        components = []
    plan['components'] = [str(name) for name in components
                          if isinstance(name, str)][:MAX_COMPONENTS]
    plan['emphasis'] = str(plan.get('emphasis') or '').strip()
    try:
        plan['decoration_budget'] = max(0, min(10, int(plan.get('decoration_budget') or 0)))
    except (TypeError, ValueError):
        plan['decoration_budget'] = 0
    for key in ('first_screen', 'image_evidence', 'line_break_risks'):
        plan[key] = str(plan.get(key) or '')
    plan['source'] = 'model'
    plan['manifest'] = manifest
    if check_cancelled:
        check_cancelled()
    return plan


def to_markdown(draft: str, plan: dict, theme: dict, title: str = '') -> tuple[str, str]:
    """Wrap at most two existing blocks in the Skill's DSL; never edit a word.

    ``emphasis`` matching a block turns it into ``:::quote``; the first prose
    block becomes ``:::callout``.  Everything else is passed through untouched,
    so the converter receives the manuscript itself.
    """
    emphasis = str(plan.get('emphasis') or '').strip()
    blocks: list[str] = []
    first_body = True
    for block in draft.split('\n\n'):
        clean = block.strip()
        if not clean:
            continue
        # A quoted source block keeps its "> " marker; the model quotes the
        # sentence itself, so compare both forms.
        matched = bool(emphasis) and (clean == emphasis
                                      or clean.lstrip('>').strip() == emphasis)
        if matched:
            blocks.extend([':::quote', clean, ':::'])
        elif first_body and not clean.startswith(('#', '<')):
            blocks.extend([':::callout', clean, ':::'])
        else:
            blocks.append(clean)
        if not clean.startswith('#') and not clean.startswith('<'):
            first_body = False
    body = '\n\n'.join(blocks)
    heading = re.search(r'^\s*#\s+([^\n]+)', draft)
    resolved = (title or (heading.group(1).strip() if heading else '')
                or theme.get('name') or '未命名').replace("'", '')
    # The Skill's own default theme owns every rendered colour; Plus never
    # injects an application palette.
    theme_name = 'default'
    markdown = f"---\ntitle: '{resolved}'\ntheme: {theme_name}\n---\n{body}"
    return markdown, theme_name


def run_preview(markdown_path: Path, theme_name: str, *,
                faithful: bool = True, timeout: int = 120) -> tuple[str, dict]:
    """Run the Skill's own preview renderer and return the article fragment."""
    markdown_path = Path(markdown_path).resolve()
    script = Path(__file__).resolve().parent / 'skill_preview.py'
    command = [workbench._skill_python(), '-X', 'utf8', str(script),
               str(Path(workbench.SKILL_DIR).resolve()), str(markdown_path), theme_name]
    if faithful:
        command.append('--faithful')
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                cwd=str(workbench.SKILL_DIR), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Skill 原生排版超时，原正文和预览已保留') from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or '').strip()[-1200:]
        raise ValueError('Skill 原生排版失败：' + (detail or '未知错误'))
    preview_path = markdown_path.with_name(markdown_path.stem + '_preview.html')
    if not preview_path.is_file():
        raise ValueError('Skill 排版完成但未生成预览文件')
    document = preview_path.read_text(encoding='utf-8')
    match = re.search(r'<main id="article-content">(.*?)</main>', document, flags=re.S)
    if not match:
        raise ValueError('Skill 预览缺少 article-content 正文区域')
    trace_path = markdown_path.with_suffix('.render.json')
    if not trace_path.is_file():
        raise ValueError('Skill 排版完成但缺少渲染记录')
    render_info = json.loads(trace_path.read_text(encoding='utf-8'))
    if render_info.get('renderer') != 'toolkit.converter.MarkdownConverter':
        raise ValueError('排版未经过 weChat-autoCreate 正式转换器')
    # ``quality_gate_blocked`` is the Skill's *content* recommendation gate.
    # Plus's format action explicitly keeps editing drafts previewable (see the
    # `no_information_anchor` preview-only path in wechat_plus_service), so it
    # is reported to the caller instead of aborting the layout.  The two layout
    # gates below still block real delivery problems.
    return match.group(1).strip(), render_info


def _run_gate(command: list[str], label: str, *, allowed=()) -> dict:
    """Run one Skill gate; ``allowed`` are accepted findings, never errors.

    ``image_host_not_wechat`` is a ``warn_blocking`` rule that the Skill's own
    ``--allow`` cannot waive, but Plus manuscripts legitimately carry CDN
    images.  The raw return code is still reported; the accepted set only
    suppresses that specific rule, and ``layout.check`` shows the user warning.
    """
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                cwd=str(workbench.SKILL_DIR), timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f'Skill {label}超时，原正文和预览已保留') from exc
    report = None
    if result.stdout.strip():
        try:
            report = json.loads(result.stdout)
        except ValueError:
            report = None
    findings = report if isinstance(report, list) else (report or {}).get('findings', [])
    blocked = [item for item in findings
               if item.get('severity') in {'error', 'warn_blocking'}
               and item.get('code') not in set(allowed)]
    accepted = sorted({item.get('code') for item in findings
                       if item.get('code') in set(allowed)})
    info = {'returncode': result.returncode, 'passed': not blocked,
            'accepted': accepted, 'report': report}
    if blocked:
        detail = '; '.join(f"{item.get('code', 'unknown')}: "
                           f"{str(item.get('suggestion', ''))[:120]}"
                           for item in blocked[:6])
        detail = detail or (result.stderr or result.stdout or '').strip()[-600:]
        raise ValueError(f'Skill {label}未通过：' + (detail or '未知问题'))
    if result.returncode and not findings:
        detail = (result.stderr or result.stdout or '').strip()[-600:]
        raise ValueError(f'Skill {label}未通过：' + (detail or '未知问题'))
    return info


def run_gates(fragment: str, work_dir: Path, *, source: str = '') -> dict:
    """Run both real Skill gates on the delivered fragment.

    ``div_tag`` is produced by the Skill's own container wrappers.  External
    image hosts are allowed because Plus drafts legitimately carry CDN images;
    ``layout.check`` still surfaces that as a user-visible warning.  Half-width
    punctuation is allowed only when the manuscript already contains it, since
    formatting must not rewrite the user's prose.
    """
    directory = Path(work_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    check_path = directory / 'layout-check.html'
    check_path.write_text(fragment, encoding='utf-8')
    scripts = workbench.SKILL_DIR / 'scripts'
    python = workbench._skill_python()
    quality = _run_gate([python, '-X', 'utf8', str(scripts / 'layout_quality_check.py'),
                         str(check_path), '--format', 'json'], '排版质量检查')
    accepted = {'div_tag', 'image_host_not_wechat'}
    allowances = ['--allow', 'div_tag', '--allow', 'image_host_not_wechat']
    if re.search(r'[\u4e00-\u9fff][,;!?]|[,;!?][\u4e00-\u9fff]', source or ''):
        allowances += ['--allow', 'halfwidth_punct']
        accepted.add('halfwidth_punct')
    compliance = _run_gate([python, '-X', 'utf8', str(scripts / 'wechat_compliance_check.py'),
                            str(check_path), '--format', 'json', '--strict', *allowances],
                           '微信合规检查', allowed=accepted)
    return {'layout': quality, 'compliance': compliance}


def _verify_fidelity(fragment: str, draft: str) -> None:
    """Fail closed if the rendered fragment no longer carries the manuscript."""
    from . import wechat_plus_layout as layout
    source = layout._safe_source(draft)
    soup = BeautifulSoup(fragment, 'html.parser')
    expected = BeautifulSoup(source, 'html.parser')
    if skill_fine_layout.visible_text(fragment) != skill_fine_layout.visible_text(source):
        raise ValueError('排版内容与原文不一致，已保留原正文和预览')
    if ([tag.get_text().strip('\n') for tag in soup.find_all('pre')]
            != [tag.get_text().strip('\n') for tag in expected.find_all('pre')]):
        raise ValueError('排版代码块与原文不一致，已保留原正文和预览')
    if ([tag.get('href') for tag in soup.find_all('a')]
            != [tag.get('href') for tag in expected.find_all('a')]):
        raise ValueError('排版链接与原文不一致，已保留原正文和预览')
    if ([(tag.get('src'), tag.get('alt')) for tag in soup.find_all('img')]
            != [(tag.get('src'), tag.get('alt')) for tag in expected.find_all('img')]):
        raise ValueError('排版图片与原文不一致，已保留原正文和预览')


def decor_metrics(fragment: str) -> dict:
    """Measure the fragment against the stock Skill output (no design targets)."""
    soup = BeautifulSoup(fragment, 'html.parser')
    styles = [str(tag.get('style') or '') for tag in soup.find_all(True)]

    def declarations(prop: str) -> int:
        return sum(style.lower().count(prop) for style in styles)

    def rgb(value: str) -> tuple[int, int, int]:
        digits = value.lstrip('#')
        if len(digits) == 3:
            digits = ''.join(char * 2 for char in digits)
        return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))

    colors: dict[str, int] = {}
    for value in re.findall(r'#[0-9a-fA-F]{3,8}', fragment):
        key = value.upper()
        colors[key] = colors.get(key, 0) + 1

    def chromatic(value: str) -> bool:
        try:
            red, green, blue = rgb(value)
        except ValueError:
            return False
        return max(red, green, blue) - min(red, green, blue) > 8

    def depth(tag) -> int:
        count, node = 0, tag
        while node is not None:
            if getattr(node, 'name', None) in {'section', 'div'}:
                count += 1
            node = node.parent
        return count

    return {
        'chromatic_kinds': sorted(value for value in colors if chromatic(value)),
        'border_left': declarations('border-left'),
        'border_top': declarations('border-top'),
        'border_bottom': declarations('border-bottom'),
        'border_radius': declarations('border-radius'),
        'max_nesting': max((depth(tag) for tag in soup.find_all(['section', 'div'])),
                           default=0),
        'links': len(soup.find_all('a')),
        'uls': len(soup.find_all('ul')),
        'bullets': fragment.count('•'),
        'colors': dict(sorted(colors.items(), key=lambda item: (-item[1], item[0]))),
    }


def render_native(draft: str, theme: dict, *, generate=None,
                  check_cancelled=None, passthrough=(), work_dir=None,
                  trace: dict | None = None) -> str:
    """Plan -> Markdown/DSL -> Skill converter -> two gates -> fragment."""
    plan = layout_plan(draft, theme, generate,
                       check_cancelled=check_cancelled, passthrough=passthrough)
    markdown, theme_name = to_markdown(draft, plan, theme)
    temporary = None
    if work_dir is None:
        temporary = tempfile.TemporaryDirectory()
        directory = Path(temporary.name)
    else:
        directory = Path(work_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        markdown_path = directory / 'article.md'
        markdown_path.write_text(markdown, encoding='utf-8')
        fragment, render_info = run_preview(markdown_path, theme_name)
        _verify_fidelity(fragment, draft)
        gates = run_gates(fragment, directory, source=draft)
    finally:
        if temporary is not None:
            temporary.cleanup()
    if trace is not None:
        metrics = decor_metrics(fragment)
        trace.update({
            'mode': 'skill-native-dsl',
            'plan': plan,
            'components': plan.get('components') or [],
            'modules': render_info.get('modules') or [],
            'decoration_budget': plan.get('decoration_budget', 0),
            'renderer': render_info.get('renderer'),
            'content_gate_blocked': bool(render_info.get('quality_gate_blocked')),
            'theme_name': theme_name,
            'gates': {name: {'returncode': info['returncode'],
                             'passed': info['passed'],
                             'accepted': info.get('accepted') or []}
                      for name, info in gates.items()},
            'metrics': metrics,
        })
    return fragment
