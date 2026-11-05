"""Read-time normalisation of historical Plus preview documents.

Old sessions can still point formatted_output at a complete HTML page with a
grey background, a 420px phone frame, a fixed toolbar and scripts.  /preview
must deliver only the inline-styled article body without rewriting the stored
file or the state field, while keeping the sandbox CSP and the other headers
byte-for-byte identical.
"""
import pytest

from server import wechat_plus_api as api
from server import wechat_plus_repository as repo
from server import workbench
from tests import test_wechat_plus_api as fixtures

CSP = ("sandbox; default-src 'none'; style-src 'unsafe-inline'; "
       "img-src 'self' data: https:; font-src 'none'")
HEADERS = {
    'content-type': 'text/html; charset=utf-8',
    'content-security-policy': CSP,
    'cache-control': 'private, no-store',
    'x-content-type-options': 'nosniff',
}

ARTICLE = (
    '<section style="max-width:100%;box-sizing:border-box;padding:26px 18px 36px;'
    'margin:0 auto;font-size:16px;line-height:1.85">'
    '<h1>整理会议记录</h1><p>核对任务和负责人。</p>'
    '<blockquote>纪要要留下承诺。</blockquote></section>')

PURE_FRAGMENT = (
    '<!-- plus-layout:deadbeef0123 -->'
    '<!-- ========== ARTICLE HTML START ========== -->'
    + ARTICLE +
    '<!-- ========== ARTICLE HTML END ========== -->')

LEGACY_DOCUMENT = (
    '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
    '<title>公众号排版预览</title>'
    '<style>body{background:#E8E8E8;padding:40px}.phone-frame{max-width:375px}</style>'
    '</head><!-- plus-layout:deadbeef0123 -->'
    '<body style="margin:0;padding:24px 12px 48px;background:#F2F2F0">'
    '<div class="toolbar" style="position:fixed">复制排版</div>'
    '<section data-wp-article="" style="max-width:420px;margin:0 auto;'
    'background:#FFFFFF;border:1px solid #E5E5E5;border-radius:16px;'
    'padding:26px 20px 36px">'
    '<!-- ========== ARTICLE HTML START ========== -->'
    + ARTICLE +
    '<!-- ========== ARTICLE HTML END ========== -->'
    '</section><script>copyHtml()</script></body></html>')

LEGACY_ORPHAN = (
    '<!DOCTYPE html><html><head><title>旧预览</title></head>'
    '<body><p>孤立正文</p></body></html>')


def assert_secure(response):
    assert response.status_code == 200
    for name, value in HEADERS.items():
        assert response.headers[name] == value, (name, response.headers.get(name))
    csp = response.headers['content-security-policy']
    assert csp.startswith('sandbox;')
    assert "default-src 'none'" in csp
    assert 'allow-scripts' not in csp
    assert 'allow-same-origin' not in csp
    assert 'script-src' not in csp
    assert 'http:' not in csp


@pytest.fixture
def plus(tmp_path, monkeypatch):
    case = fixtures.PlusAPITests(methodName='runTest')
    case.setUp()
    monkeypatch.setattr(workbench, 'OUTPUT_DIR', tmp_path)
    try:
        yield case, tmp_path
    finally:
        case.tearDown()


def _blank_state():
    return {'messages': [], 'versions': [],
            'article_state': api.service.runtime.initialize('改稿')}


def _session(case, tmp_path, content, name='article.html'):
    row = repo.create('owner')
    folder = tmp_path / 'wechat-plus' / row['id']
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(content, encoding='utf-8')
    state = _blank_state()
    state['article_state'].update(draft='原稿', formatted_output=str(path))
    repo.save(row['id'], 'owner', 1, state)
    return row['id'], path


def _preview(case, session_id, headers=None, *, chrome=False):
    url = f'/api/wechat-plus/sessions/{session_id}/preview'
    if chrome:
        url += '?chrome=true'
    return case.client.get(url, headers=case.headers if headers is None else headers)


def test_pure_fragment_is_returned_verbatim(plus):
    case, tmp_path = plus
    session_id, path = _session(case, tmp_path, PURE_FRAGMENT)
    response = _preview(case, session_id)
    assert_secure(response)
    assert response.text == PURE_FRAGMENT
    assert path.read_text(encoding='utf-8') == PURE_FRAGMENT


def test_legacy_document_is_stripped_and_keeps_all_body_text(plus):
    case, tmp_path = plus
    session_id, path = _session(case, tmp_path, LEGACY_DOCUMENT)
    response = _preview(case, session_id)
    assert_secure(response)
    body = response.text
    for shell in ('<!DOCTYPE', '<!doctype', '<html', '<head', '<body', '<style',
                  '<script', '#F2F2F0', '#E8E8E8', 'max-width:420px',
                  'data-wp-article', 'toolbar', '复制排版', 'phone-frame'):
        assert shell not in body, shell
    assert 'max-width:100%' in body
    assert 'padding:26px 18px 36px' in body
    for text in ('整理会议记录', '核对任务和负责人。', '纪要要留下承诺。'):
        assert text in body
    # No data migration: the stored file and the state field are untouched.
    assert path.read_text(encoding='utf-8') == LEGACY_DOCUMENT
    assert repo.get(session_id, 'owner')['state']['article_state']['formatted_output'] == str(path)


@pytest.mark.parametrize('open_tag,close_tag', [
    ('<div id="articleContent">', '</div>'),
    ('<div id="article-content">', '</div>'),
    ('<section data-wp-article="">', '</section>'),
])
def test_legacy_document_without_boundaries_falls_back_to_container(plus, open_tag, close_tag):
    case, tmp_path = plus
    document = (
        '<!DOCTYPE html><html><head><title>旧预览</title></head>'
        '<body style="background:#F2F2F0">' + open_tag +
        '<h1>整理会议记录</h1><p>核对任务和负责人。</p>' + close_tag +
        '</body></html>')
    session_id, _ = _session(case, tmp_path, document)
    response = _preview(case, session_id)
    assert_secure(response)
    body = response.text
    assert '<!DOCTYPE' not in body and '<html' not in body and '<head' not in body
    assert '#F2F2F0' not in body
    assert '整理会议记录' in body and '核对任务和负责人。' in body


def test_unrecognisable_legacy_document_returns_404(plus):
    case, tmp_path = plus
    session_id, _ = _session(case, tmp_path, LEGACY_ORPHAN)
    response = _preview(case, session_id)
    assert response.status_code == 404
    assert '重新排版' in response.json()['detail']


def test_default_mode_returns_a_pure_fragment_without_padding(plus):
    case, tmp_path = plus
    session_id, _ = _session(case, tmp_path, ARTICLE)
    response = _preview(case, session_id)
    assert_secure(response)
    assert response.text.startswith('<section')
    assert 'padding:0 18px' not in response.text
    assert response.text == ARTICLE


def test_chrome_mode_wraps_exactly_one_padding_section(plus):
    case, tmp_path = plus
    session_id, path = _session(case, tmp_path, ARTICLE)
    response = _preview(case, session_id, chrome=True)
    assert_secure(response)
    assert response.text == api.CHROME_OPEN + ARTICLE + '</section>'
    assert response.text.count('padding:0 18px') == 1
    assert response.text.count('<section') == 2  # wrapper + article
    # The stored file is never modified by the visual wrapper.
    assert path.read_text(encoding='utf-8') == ARTICLE


def test_both_modes_share_identical_security_headers(plus):
    case, tmp_path = plus
    session_id, _ = _session(case, tmp_path, ARTICLE)
    default = _preview(case, session_id)
    chrome = _preview(case, session_id, chrome=True)
    assert_secure(default)
    assert_secure(chrome)
    assert {name: default.headers[name] for name in HEADERS} == \
           {name: chrome.headers[name] for name in HEADERS}


def test_chrome_mode_still_strips_a_legacy_document(plus):
    case, tmp_path = plus
    session_id, _ = _session(case, tmp_path, LEGACY_DOCUMENT)
    response = _preview(case, session_id, chrome=True)
    assert_secure(response)
    body = response.text
    assert body.startswith(api.CHROME_OPEN)
    assert body.count('padding:0 18px') == 1
    for shell in ('<!DOCTYPE', '<!doctype', '<html', '<head', '<body', '<style',
                  '<script', '#F2F2F0', '#E8E8E8', 'max-width:420px',
                  'data-wp-article', 'toolbar', '复制排版', 'phone-frame'):
        assert shell not in body, shell
    assert '核对任务和负责人。' in body


def test_path_traversal_still_returns_404(plus):
    case, tmp_path = plus
    outside = tmp_path / 'outside.html'
    outside.write_text(PURE_FRAGMENT, encoding='utf-8')
    row = repo.create('owner')
    state = _blank_state()
    state['article_state'].update(draft='原稿', formatted_output=str(outside))
    repo.save(row['id'], 'owner', 1, state)
    for chrome in (False, True):
        assert _preview(case, row['id'], chrome=chrome).status_code == 404
        assert _preview(case, row['id'], {'X-Test-User': 'other'},
                        chrome=chrome).status_code == 404
    assert _preview(case, row['id'], {}).status_code == 401


def test_foreign_session_directory_is_out_of_scope(plus):
    case, tmp_path = plus
    foreign = tmp_path / 'wechat-plus' / 'another-session' / 'article.html'
    foreign.parent.mkdir(parents=True, exist_ok=True)
    foreign.write_text(PURE_FRAGMENT, encoding='utf-8')
    row = repo.create('owner')
    state = _blank_state()
    state['article_state'].update(draft='原稿', formatted_output=str(foreign))
    repo.save(row['id'], 'owner', 1, state)
    assert _preview(case, row['id']).status_code == 404


def test_missing_formatted_output_returns_404(plus):
    case, _ = plus
    row = repo.create('owner')
    repo.save(row['id'], 'owner', 1, _blank_state())
    response = _preview(case, row['id'])
    assert response.status_code == 404
    assert '生成排版预览' in response.json()['detail']
