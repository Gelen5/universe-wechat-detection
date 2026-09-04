"""Publish the exact approved HTML through the installed Skill's WeChat API."""
import json
import sys
import base64
import hashlib
from pathlib import Path


def main():
    root, directory = map(Path, sys.argv[1:3])
    sys.path.insert(0,str(root))
    from toolkit.config import get_config
    from toolkit.wechat_api import WeChatAPI
    from toolkit.recommendation_quality import check_article_file
    report = check_article_file(str(directory / 'article.md'),strict=True)
    if report['blocked']:
        raise RuntimeError('推荐质量门禁未通过')
    delivery = json.loads((directory / 'delivery.json').read_text(encoding='utf-8'))
    api = WeChatAPI(get_config())
    html = (directory / 'approved.html').read_text(encoding='utf-8')
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html,'html.parser')
    files = {hashlib.sha256(path.read_bytes()).hexdigest():path for path in (directory / 'images').iterdir() if path.is_file()}
    uploaded = {}
    for image in soup.find_all('img'):
        source = image.get('src','')
        if not source.startswith('data:image/') or ';base64,' not in source:
            raise RuntimeError('交付图片不是已确认的本地图片')
        raw = base64.b64decode(source.split(';base64,',1)[1],validate=True)
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in files:
            raise RuntimeError('交付图片与本地文件不一致')
        url = uploaded.get(digest) or api.upload_image(str(files[digest]))
        if not url:
            raise RuntimeError('正文图片上传失败')
        uploaded[digest] = url
        image['src'] = url
        image.attrs.pop('data-src',None)
    rewritten = str(soup)
    cover_id = api.upload_cover(delivery['cover'])
    if not cover_id:
        raise RuntimeError('封面上传失败')
    # Installed add_draft has a misspelled comment variable; the Skill's
    # multi-article API accepts a one-article payload and preserves HTML.
    media_id = api.add_draft_multi([{'title':delivery['title'],'content':rewritten,
                                   'thumb_media_id':cover_id,'need_open_comment':0,
                                   'only_fans_can_comment':0}])
    if not media_id:
        raise RuntimeError('微信未返回草稿media_id')
    print(json.dumps({'status':'draft_created','media_id':media_id},ensure_ascii=False))


if __name__ == '__main__':
    main()
