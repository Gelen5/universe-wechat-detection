"""Faithful, single-accent configuration of the Skill's ``MarkdownConverter``.

Two concerns live here, both purely at the theme layer -- no article HTML is
assembled by the application:

1. **Verbatim text.**  The Skill's 16-step pipeline intentionally rewrites prose
   in several steps (CJK spacing, code line numbers, punctuation moves, list
   bullets, link footnotes, AIGC copy).  Those steps are disabled.
2. **One accent color.**  The upstream ``CONTAINER_TYPES`` palette hard-codes
   orange/green/blue/pink containers and ``_step9_inline_styles`` draws rules
   under every heading.  Both are overridden here with the palette below, so a
   rendered article uses neutral greys plus a single accent.

No Skill source is modified: ``server/skill_preview.py`` passes ``--faithful``
and swaps ``MarkdownConverter`` for this subclass.  The default three-argument
path (old workbench, Skill CLI) keeps the upstream behaviour untouched.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

# The default ink-blue system.  All four STYLE_OPTIONS fall back to this set
# until the visual direction is confirmed; passing ``palette=`` overrides any
# key without changing the structure below.
PALETTE = {
    'ink': '#1B2A4A',
    'body': '#3A3A3C',
    'muted': '#86868B',
    'line': '#E8E8EA',
    'surface': '#F7F7F8',
    'accent': '#1B2A4A',
}


def faithful_converter_class(base, palette: dict | None = None):
    """Return a ``MarkdownConverter`` subclass with the Plus text/theme rules."""

    colors = {**PALETTE, **(palette or {})}

    class FaithfulConverter(base):
        palette = colors

        def __init__(self, theme: dict | None = None):
            merged = dict(theme or {})
            for key, value in colors.items():
                merged.setdefault(key, value)
            super().__init__(merged)

        # -- text fidelity -------------------------------------------------
        def _step2_cjk_spacing(self, text):
            return text  # inserting spaces between CJK and Latin edits the prose

        def _step4_code_enhance(self, html):
            # Upstream writes line numbers and a language label into <pre>.
            return re.sub(r'<pre\b[^>]*>', '<pre>', html)

        def _step6_bold_punctuation_move(self, html):
            return html  # moving punctuation out of <strong> changes the text

        def _step7_list_to_section(self, html):
            return html  # upstream replaces lists with literal "•" / "1." text

        def _step8_external_links_to_footnotes(self, html):
            return html  # upstream drops <a href> and appends a 参考链接 block

        def _step13_aigc_declaration(self, html):
            return html  # no extra visible copy

        def _step14_summary(self, html):
            return html  # the digest comment is not needed for delivery

        def _step15_final_cleanup(self, html):
            # Upstream decodes entities, which can corrupt code blocks.
            return re.sub(r'<br\s*/?>', '<br/>', html).strip()

        # -- one neutral container family, one accent ----------------------
        def _container_styles(self) -> dict[str, str]:
            c = self.palette
            neutral = (f'padding:16px 18px;background:{c["surface"]};'
                       f'border-left:3px solid {c["accent"]};border-radius:0;'
                       f'margin:28px 0;')
            quote = (f'padding:2px 0 2px 14px;background:transparent;'
                     f'border-left:2px solid {c["accent"]};border-radius:0;'
                     f'margin:28px 0;')
            return {
                'callout-container': neutral,
                'dialogue-container': neutral,
                'timeline-container': neutral,
                'highlight-container': neutral,
                'summary-container': neutral,
                'module-container': neutral,
                # The quote container owns the only rule; the nested
                # <blockquote> is cleared in _step9 to avoid a double line.
                'quote-container': quote,
            }

        def _step1_preprocess_containers(self, text):
            result = super()._step1_preprocess_containers(text)
            for class_name, style in self._container_styles().items():
                result = re.sub(rf'(<div class="{class_name}" )style="[^"]*"',
                                rf'\1style="{style}"', result)
            return result

        # -- typography: size/weight/space only, no heading rules ----------
        def _step9_inline_styles(self, html):
            c = self.palette
            style_map = {
                'h1': (f'font-size:22px;font-weight:700;color:{c["ink"]};'
                       'line-height:1.4;margin:0 0 26px;padding:0;border:0;'),
                'h2': (f'font-size:17px;font-weight:650;color:{c["ink"]};'
                       'line-height:1.5;margin:40px 0 14px;padding:0;border:0;'),
                'h3': (f'font-size:16px;font-weight:600;color:{c["ink"]};'
                       'line-height:1.6;margin:28px 0 10px;padding:0;border:0;'),
                'h4': (f'font-size:16px;font-weight:600;color:{c["ink"]};'
                       'margin:22px 0 8px;border:0;'),
                'p': (f'margin:0 0 22px;line-height:1.9;color:{c["body"]};'
                      'font-size:16px;'),
                'blockquote': (f'border-left:2px solid {c["accent"]};'
                               'background:transparent;'
                               f'color:{c["muted"]};padding:2px 0 2px 14px;'
                               'margin:28px 0;border-radius:0;'),
                'ul': 'padding-left:20px;margin:0 0 22px;list-style-position:outside;',
                'ol': 'padding-left:20px;margin:0 0 22px;list-style-position:outside;',
                'li': f'margin:8px 0;line-height:1.9;color:{c["body"]};',
                # The article's only coloured text is the accent; links stay
                # neutral so the page never shows a second hue.
                'a': f'color:{c["body"]};text-decoration:underline;',
            }
            soup = BeautifulSoup(html, 'html.parser')
            for tag_name, style in style_map.items():
                for element in soup.find_all(tag_name):
                    existing = str(element.get('style') or '')
                    element['style'] = f'{style}{existing}' if existing else style
            # A quote container already carries the rule: clear the inner
            # <blockquote> and its paragraphs so only one vertical line shows.
            for quote in soup.find_all('blockquote'):
                in_container = quote.find_parent('div', class_='quote-container')
                if in_container is not None:
                    quote['style'] = 'margin:0;padding:0;border:0;background:transparent;'
                    for paragraph in quote.find_all('p'):
                        paragraph['style'] = (f'margin:0;line-height:1.9;'
                                              f'color:{c["muted"]};font-size:16px;')
            return str(soup)

    return FaithfulConverter
