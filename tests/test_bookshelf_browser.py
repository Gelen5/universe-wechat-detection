"""Real browser behavior against the public static catalog; no paid APIs."""
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def test_bookshelf_public_reading_and_mobile_layout():
    errors = []
    def serve(route):
        path = urlparse(route.request.url).path
        file = ROOT / path.lstrip('/') if path.startswith('/static/') else ROOT / 'static/bookshelf.html'
        route.fulfill(status=200, body=file.read_bytes(), content_type=mimetypes.guess_type(str(file))[0] or 'text/plain')

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        page = browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('http://library.test/**', serve)
        page.goto('http://library.test/bookshelf')
        expect(page.locator('.book-link')).to_have_count(21)
        data = json.loads((ROOT / 'static/bookshelf-data.json').read_text(encoding='utf-8'))['books']
        expected = [b['id'] for b in sorted(data, key=lambda b: -b['stars'])]
        assert page.locator('[data-book]').evaluate_all('(els)=>els.map(e=>e.dataset.book)') == expected
        page.get_by_role('button', name='知识管理', exact=True).click()
        expect(page.locator('.book-link')).to_have_count(1)
        page.get_by_role('button', name='全部', exact=True).click()
        page.get_by_role('button', name='搜索书名', exact=True).click()
        page.get_by_role('searchbox', name='搜索书名', exact=True).fill('Codex')
        expect(page.locator('.book-link')).to_have_count(1)
        page.locator('.book-link').click()
        expect(page.locator('#detail-title')).to_have_text('OpenAI Codex 橙皮书')
        expect(page.locator('.detail-source')).to_contain_text('CC BY-NC-SA 4.0')
        read = page.get_by_role('link', name='阅读原文')
        assert read.get_attribute('href') == next(b['readUrl'] for b in data if b['id'] == 'codex')
        assert read.get_attribute('target') == '_blank'
        page.get_by_role('button', name='收藏此书', exact=True).click()
        page.reload()
        expect(page.get_by_role('button', name='取消收藏', exact=True)).to_be_visible()
        page.get_by_role('link', name='返回书架', exact=False).click()
        # A direct detail reload must not break the return path.
        expect(page.locator('.book-link')).to_have_count(21)
        page.get_by_role('button', name='搜索书名', exact=True).click()
        page.get_by_role('searchbox', name='搜索书名', exact=True).fill('不存在的书')
        expect(page.get_by_role('heading', name='还没有找到这本书')).to_be_visible()
        page.get_by_role('button', name='查看全部', exact=True).click()
        for width, columns in ((390,2),(768,3),(1280,4),(1440,4),(1920,5)):
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), width
            assert len(page.locator('#book-grid').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ")')) == columns
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button', name='更多', exact=True).click()
        expect(page.get_by_role('dialog', name='全部功能')).to_be_visible()
        page.keyboard.press('Escape')
        expect(page.get_by_role('button', name='更多', exact=True)).to_be_focused()
        assert not errors, errors
        browser.close()


def test_catalog_network_failure_can_be_retried():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        page = browser.new_page()
        def serve(route):
            path = urlparse(route.request.url).path
            if path.endswith('bookshelf-data.json'):
                route.fulfill(status=503, body='unavailable')
            else:
                file = ROOT / path.lstrip('/') if path.startswith('/static/') else ROOT / 'static/bookshelf.html'
                route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'text/plain')
        page.route('http://library.test/**',serve)
        page.goto('http://library.test/bookshelf')
        expect(page.get_by_role('button', name='重新载入')).to_be_visible()
        page.route('**/bookshelf-data.json',lambda route: route.fulfill(body=(ROOT / 'static/bookshelf-data.json').read_bytes(), content_type='application/json'))
        page.get_by_role('button', name='重新载入').click()
        expect(page.locator('.book-link')).to_have_count(21)
        browser.close()


def test_life_guides_categories_details_and_mobile_authorship():
    books = json.loads((ROOT / 'static/bookshelf-data.json').read_text(encoding='utf-8'))['books']
    additions = [book for book in books if book.get('series') == '生活与成长指南']
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        page = browser.new_page(viewport={'width': 390, 'height': 844})
        def serve(route):
            path = urlparse(route.request.url).path
            file = ROOT / path.lstrip('/') if path.startswith('/static/') else ROOT / 'static/bookshelf.html'
            route.fulfill(status=200, body=file.read_bytes(), content_type=mimetypes.guess_type(str(file))[0] or 'text/plain')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http://library.test/**', serve)
        for book in additions:
            page.goto('http://library.test/bookshelf/' + book['id'])
            expect(page.locator('#detail-title')).to_have_text(book['title'])
            expect(page.locator('.detail-author')).to_have_text(book['author'] + ' ↗')
            assert page.locator('.detail-author').get_attribute('href') == book['authorUrl']
            assert page.locator('.detail-read').get_attribute('href') == book['readUrl']
            expect(page.locator('.detail-cover .cover-author')).to_have_text(book['author'])
            expect(page.locator('.detail-copy .library-eyebrow')).not_to_contain_text('橙皮书')
            if book.get('riskNote'):
                expect(page.get_by_role('region', name='阅读提示')).to_contain_text(book['riskNote'])
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), book['id']
        page.goto('http://library.test/bookshelf')
        for category in sorted({book['category'] for book in additions}):
            page.get_by_role('button', name=category, exact=True).click()
            expect(page.locator('.book-link')).to_have_count(sum(book['category'] == category for book in books))
        assert not errors, errors
        browser.close()
