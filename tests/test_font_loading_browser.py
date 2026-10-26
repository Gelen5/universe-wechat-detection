"""Prevent the full Chinese font library from downloading on the first screen."""
from tests.test_ui_shell_browser import browser, ui


def test_home_only_loads_character_relevant_font_shards(ui):
    page, _ = ui
    fonts = []
    page.on('request', lambda request: fonts.append(request.url) if '.woff2' in request.url else None)
    page.goto('http://ui.test/', wait_until='networkidle')
    page.evaluate('document.fonts.ready')
    assert 0 < len(fonts) < 60, f'Unexpected font download fanout: {len(fonts)}'
    assert page.evaluate('''() => [...document.fonts].every(font => font.unicodeRange !== 'U+0-10FFFF')''')
