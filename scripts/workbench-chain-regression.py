"""Real provider integration, isolated session files; no account charge or publish."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import workbench as w

sid = sys.argv[1] if len(sys.argv)>1 else 'qa-chain-20260905'
out = w.OUTPUT_DIR / sid
out.mkdir(parents=True,exist_ok=True)
checkpoint = out / 'session.json'


def save(session):
    w.SESSIONS[sid] = session
    checkpoint.write_text(json.dumps(session,ensure_ascii=False,indent=2),encoding='utf-8')


with w.provider_overrides(), patch.object(w,'_save_session',side_effect=save), patch.object(w,'_get_session',side_effect=lambda *a:w.SESSIONS[sid]):
    if checkpoint.exists():
        session = json.loads(checkpoint.read_text(encoding='utf-8'))
        w.SESSIONS[sid] = session
        if not session.get('suggestions'):
            session['suggestions'] = w._suggestions(session['brief'], session['persona'], session)
            save(session)
    else:
        w.create('写一篇面向刚开始写公众号的上班族的实用方法文章，主题是下班后整理写作素材。600—900字，提出三个具体步骤，不编造个人经历、案例、调查、比例、研究结论或名人引用。以建议口吻写，结尾给一个今天就能做的小行动。配图只要1张封面和1张正文示意图，图注说明AI示意。',user_id='isolated-regression',session_id=sid)
        session = w.SESSIONS[sid]
    try:
        if '--reuse-layout-plan' in sys.argv and session.get('layout_plan'):
            session['layout_plan_key'] = w.skill_runtime.digest(session['article'] + session['theme'] + json.dumps(session.get('image_plan',{}),sort_keys=True,ensure_ascii=False))
        if '--rerender' in sys.argv:
            session['typeset_html'] = ''
            session['current_step'] = 5
        if '--editor-fixture' in sys.argv and int(session.get('current_step',1)) < 4:
            session['article'] = (Path(__file__).parent / 'fixtures/material-workflow.md').read_text(encoding='utf-8')
            session['topic'] = '下班后，给写作素材找一个固定位置'
            session['current_step'] = 3
            session['qa_input'] = 'editor-authored fixture; stages 1-3 tested separately'
            save(session)
        start = int(session.get('current_step',1)) + 1
        for step in range(start,8):
            print('START',step,flush=True)
            w.step(sid,step,selection=1,user_id='isolated-regression')
            print('DONE',step,flush=True)
        print(json.dumps({'preview':session.get('preview_url'),'images':len(session.get('images',[])),'review':(session.get('review') or {}).get('gate'),'layout':session.get('layout_check')},ensure_ascii=False),flush=True)
    except Exception as exc:
        save(session)
        print('BLOCKED',str(exc),flush=True)
        raise
