from types import SimpleNamespace
from io import BytesIO
from zipfile import ZipFile
import pytest
from fastapi import HTTPException
from server import sticker_extract as subject


def test_type8_original_images_skip_nested_watermarks_and_preserve_duplicates():
    source = """picture_page_info_list: [
    {cdn_url:'https://mmbiz.qpic.cn/first/0?x=1\\x26amp;y=2', watermark:{cdn_url:'https://mmbiz.qpic.cn/watermark/0'}},
    {cdn_url: JsDecode('https://mmbiz.qpic.cn/second/0')},
    {cdn_url:'https://mmbiz.qpic.cn/first/0?x=1\\x26amp;y=2'}];"""
    assert subject.parse_images(source) == ['https://mmbiz.qpic.cn/first/0?x=1&y=2', 'https://mmbiz.qpic.cn/second/0', 'https://mmbiz.qpic.cn/first/0?x=1&y=2']


def test_zip_scoped_to_account_and_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(subject, 'ROOT', tmp_path)
    token = 'a' * 32
    folder = tmp_path / 'one' / token
    folder.mkdir(parents=True)
    (folder / '01.png').write_bytes(b'one')
    (folder / '02.jpg').write_bytes(b'two')
    owner = SimpleNamespace(state=SimpleNamespace(user={'id':'one'}))
    other = SimpleNamespace(state=SimpleNamespace(user={'id':'two'}))
    archive = subject.download_zip(token, owner)
    with ZipFile(BytesIO(archive.body)) as z:
        assert z.namelist() == ['01.png', '02.jpg']
        assert z.testzip() is None
    with pytest.raises(HTTPException) as e: subject._dir(other, token)
    assert e.value.status_code == 404


def test_reject_large_image_collection():
    source = 'picture_page_info_list: [' + ','.join("{cdn_url:'https://mmbiz.qpic.cn/%d/0'}" % n for n in range(31)) + ']'
    with pytest.raises(ValueError, match='30'): subject.parse_images(source)
