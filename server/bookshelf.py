"""Public, metadata-only library. Tutorials stay on their authors' sites."""
import json
from html import escape
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter()
STATIC = Path(__file__).resolve().parents[1] / 'static'


@router.get('/bookshelf', response_class=HTMLResponse, include_in_schema=False)
@router.get('/bookshelf/{book_id}', response_class=HTMLResponse, include_in_schema=False)
def page(book_id: str | None = None):
    html = (STATIC / 'bookshelf.html').read_text(encoding='utf-8')
    if book_id:
        books = json.loads((STATIC / 'bookshelf-data.json').read_text(encoding='utf-8'))['books']
        book = next((b for b in books if b['id'] == book_id), None)
        if book is None:
            raise HTTPException(404, '这本书尚未收录')
        html = html.replace('AI 书架 · 宇宙第一工作台', escape(book['title']) + ' · AI 书架')
        html = html.replace('收集值得反复阅读的 AI 开源教程。查看作者、许可证与官方阅读入口。', escape(book['description'], quote=True))
    return HTMLResponse(html, headers={'Cache-Control': 'no-cache'})
