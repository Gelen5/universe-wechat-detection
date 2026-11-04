"""Server-owned content and constraints; creative plans cannot mutate source facts."""
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def build(analysis, goal, preserve_person=False):
    asset=(analysis.get('visual_contract') or {}).get('asset_type','poster')
    category=analysis.get('content_type') or {'photo':'person_photo','infographic':'data','text':'opinion'}.get(asset,'poster')
    if category not in ('data','person_photo','product','tutorial','opinion','poster'):
        category='poster'
    if analysis.get('data_contract'): category='data'
    core=analysis.get('content_core') or {}
    if not isinstance(core,dict): core={}
    ledger={'version':2,'category':category,'goal':goal,'preserve_person':bool(preserve_person),
            'data':analysis.get('data_contract'),'core':core,'verification':'source_only',
            'visual':analysis.get('visual_contract') or {}}
    ledger['fingerprint']=fingerprint(ledger)
    return ledger


def select(session, submitted):
    analysis=session.get('result') or {}
    plans=analysis.get('ideas') or []
    chosen=next((p for p in plans if p.get('id')==submitted.get('id')),None)
    if not chosen: raise ValueError('方案已失效，请重新选择当前拆解结果中的方案')
    ledger=session.get('content_ledger') or build(analysis,session.get('goal') or '',session.get('preserve_person'))
    return {**chosen,'choices':submitted.get('choices') or {},'content_ledger':ledger,
            'source_fingerprint':ledger['fingerprint'],'user_goal':ledger['goal']}
