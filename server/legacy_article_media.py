"""Read-only access to images referenced by migrated one-click articles."""
import re
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from . import accounts, workbench
router=APIRouter()

@router.get('/api/qihaoshou/assets/{sid}/{name}')
def legacy_image(sid: str, name: str, request: Request):
    user=accounts.require_user(request)
    if not re.fullmatch(r'writer_[a-f0-9]{32}',sid) or not re.fullmatch(r'[a-f0-9]{32}\.jpg',name):
        raise HTTPException(404,'图片不存在')
    session=accounts.load_workbench_session(sid,user['id'])
    if not session or session.get('kind')!='qihaoshou' or name not in {x.get('file') for x in session.get('images',[]) if isinstance(x,dict)}:
        raise HTTPException(404,'图片不存在')
    path=workbench.ROOT / 'output' / 'qihaoshou' / sid / name
    if not path.is_file(): raise HTTPException(404,'图片不存在')
    return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'private, no-store'})
