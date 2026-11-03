from pathlib import Path
from html.parser import HTMLParser
from PIL import Image
from server.site_icons import SITE_ICONS

ROOT = Path(__file__).resolve().parents[1]

class IconParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'link' and values.get('rel') in ('icon', 'apple-touch-icon'):
            self.icons.append((values.get('rel'), values.get('href')))


def test_standalone_pages_use_same_icons_as_workbench():
    expected = IconParser(); expected.feed(SITE_ICONS)
    for name in ('index.html', 'bookshelf.html', 'market.html', 'admin-activity.html', 'owner-behavior.html', 'owner-revenue.html'):
        doc = IconParser(); doc.feed((ROOT / 'static' / name).read_text(encoding='utf-8'))
        assert doc.icons == expected.icons, name


def test_fallback_favicon_is_valid_ico():
    with Image.open(ROOT / 'static' / 'favicon.ico') as icon:
        assert icon.format == 'ICO'
        assert (16, 16) in icon.ico.sizes()
        assert (32, 32) in icon.ico.sizes()
