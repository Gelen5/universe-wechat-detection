"""Verbatim-text configuration of the Skill's own ``MarkdownConverter``.

The Skill's 16-step pipeline intentionally rewrites prose in several steps:
CJK spacing, code line numbers, punctuation moves, list bullets, link
footnotes, AIGC copy and a digest.  Plus delivers the user's manuscript
verbatim, so exactly those steps are disabled and nothing else.  Every visual
token -- container colors, heading rules, radii, body typography -- stays the
Skill's own; no colour, font, spacing or radius value is written here.

No Skill source is modified: ``server/skill_preview.py`` passes ``--faithful``
and swaps ``MarkdownConverter`` for this subclass.  The default three-argument
path (old workbench, Skill CLI) keeps the upstream behaviour untouched.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup


def faithful_converter_class(base):
    """Return a ``MarkdownConverter`` subclass that never edits visible text."""

    class FaithfulConverter(base):
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

        def _step9_inline_styles(self, html):
            # Step8 is disabled, so the link survives in the body.  Give it the
            # theme's accent instead of the browser's undefined default blue.
            html = super()._step9_inline_styles(html)
            accent = str(self.theme.get('accent_color') or '').strip()
            if not accent:
                return html
            soup = BeautifulSoup(html, 'html.parser')
            for link in soup.find_all('a'):
                link['style'] = f'color:{accent};text-decoration:underline;'
            return str(soup)

        def _step13_aigc_declaration(self, html):
            return html  # no extra visible copy

        def _step14_summary(self, html):
            return html  # the digest comment is not needed for delivery

        def _step15_final_cleanup(self, html):
            # Upstream decodes entities, which can corrupt code blocks.
            return re.sub(r'<br\s*/?>', '<br/>', html).strip()

    return FaithfulConverter
