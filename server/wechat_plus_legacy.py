"""Copy legacy article history into owner-scoped Plus sessions, without deleting sources."""
from __future__ import annotations
import hashlib
import json
import re
from bs4 import BeautifulSoup, NavigableString
from sqlalchemy import MetaData, Table, select, text
from . import database, wechat_plus_repository as repo, wechat_plus_runtime as runtime
from .models import Conversation, ConversationMessage, Artifact


def _id(kind, source):
    return hashlib.sha256(('plus-history-v1:' + kind + ':' + source).encode()).hexdigest()[:32]


def _messages(raw):
    if not isinstance(raw, list): return []
    return [{'role': m['role'], 'content': str(m.get('content') or '')} for m in raw
            if isinstance(m, dict) and m.get('role') in ('user','assistant') and isinstance(m.get('content'), str)]


def _html_to_markdown(html):
    """Make the one-click editor's HTML usable in Plus; retain original separately."""
    soup = BeautifulSoup(html, 'html.parser')
    def convert(node):
        if isinstance(node, NavigableString): return str(node)
        name = getattr(node, 'name', '') or ''
        if name in {'script','style','iframe','object'}: return ''
        if name == 'img':
            src=str(node.get('src') or ''); alt=str(node.get('alt') or '')
            return f'![{alt}]({src})' if src else ''
        if name == 'br': return '\n'
        if name in {'table','pre'}: return '\n\n'+str(node)+'\n\n'
        inner=''.join(convert(child) for child in node.children)
        if name in {'h1','h2','h3','h4','h5','h6'}: return '\n\n'+'#'*int(name[1])+' '+inner.strip()+'\n\n'
        if name in {'strong','b'} and inner.strip(): return '**'+inner+'**'
        if name in {'em','i'} and inner.strip(): return '*'+inner+'*'
        if name == 'a' and node.get('href'): return '['+inner+']('+str(node['href'])+')'
        if name == 'li': return '\n- '+inner.strip()+'\n'
        if name == 'blockquote': return '\n\n'+'\n'.join('> '+line for line in inner.strip().splitlines())+'\n\n'
        if name in {'p','div','section','ul','ol'}: return '\n\n'+inner.strip()+'\n\n'
        return inner
    return re.sub(r'\n{3,}', '\n\n', convert(soup)).strip()


def _state(title, draft, messages, versions, source, images=None, formatted=''):
    article = runtime.initialize(title or '历史文章')
    article.update(draft=draft, topic=title or '历史文章', selected_title=title or '历史文章',
                   angle='基于用户历史文章继续创作')
    article['intent']['goal'] = '继续编辑用户历史文章'
    article['audience'] = {'description':'沿用历史文章读者，未另行指定','status':'unspecified'}
    if draft:
        article['evidence_pack'] = {'sources': {'records': [{'source_id':'legacy-manuscript',
            'kind':'user','title':'用户历史文章','evidence':draft,'status':'unverified',
            'notes':'历史文章，事实尚未独立复核'}]}, 'claims':[], 'research_status':'partial',
            'limitations':['历史文章的事实尚未独立核验。']}
        article['outline'] = [{'heading':'沿用原文结构'}]
        article['writing_strategy'] = {'mode':'edit_existing','instruction':'保留历史文章，只执行用户本次要求',
            'material_gaps':['原稿事实未独立核验'],'prohibited':['编造经历、数据和来源']}
    unique=[]
    for body in [*versions,draft]:
        if not isinstance(body,str) or not body.strip() or (unique and unique[-1]['draft']==body): continue
        unique.append({'number':len(unique)+1,'draft':body,'title':title,'reason':'迁移历史版本','at':''})
    safe_images=[]
    for image in images or []:
        if not isinstance(image,dict): continue
        url=image.get('url')
        if isinstance(url,str) and url.startswith(('/api/workbench/assets/', '/api/qihaoshou/assets/', '/api/storage/')):
            safe_images.append({'url':url})
    return {'messages':_messages(messages),'article_state':article,'choices':[], 'versions':unique,
            'imported':bool(draft),'legacy_source':source,'legacy_images':safe_images,
            'legacy_preview_html':formatted if isinstance(formatted,str) else '',
            'legacy_original_draft':draft}


def migrate_for(user_id):
    """Idempotent, per-owner copies; existing Plus content is never overwritten."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from sqlalchemy import inspect
    existing_tables = set(inspect(database.ENGINE).get_table_names())
    # Do not copy a partial snapshot while a previous writer is still running.
    with database.ENGINE.connect() as db:
        checks = []
        if 'workbench_jobs' in existing_tables:
            checks.append("SELECT COUNT(*) FROM workbench_jobs WHERE user_id=:user AND status IN ('queued','running')")
        if 'jobs' in existing_tables:
            checks.append("SELECT COUNT(*) FROM jobs WHERE user_id=:user AND type IN ('workbench','workbench_step') AND status IN ('queued','running')")
        if 'runs' in existing_tables:
            checks.append("SELECT COUNT(*) FROM runs WHERE user_id=:user AND skill_id='wechat_writer' AND status IN ('queued','running')")
        if any(db.execute(text(query), {'user':user_id}).scalar() for query in checks):
            raise RuntimeError('legacy writing is still running; retry migration after it completes')
    with database.ENGINE.connect() as db:
        existing = set(db.execute(select(repo.sessions.c.id).where(repo.sessions.c.user_id==user_id)).scalars())
    rows=[]
    if 'workbench_sessions' in existing_tables:
        legacy=Table('workbench_sessions',MetaData(),autoload_with=database.ENGINE)
        with database.ENGINE.connect() as db:
            source_rows=db.execute(select(legacy.c.id,legacy.c.payload_json,legacy.c.updated_at)
                .where(legacy.c.user_id==user_id)).all()
        for sid, raw, updated in source_rows:
            try: data=json.loads(raw) if isinstance(raw,str) else raw
            except (ValueError, TypeError): continue
            if not isinstance(data,dict): continue
            writer=data.get('kind')=='qihaoshou'
            if not writer and (data.get('conversation_skill') or data.get('kind') or 'pipeline_version' not in data): continue
            kind='one-click' if writer else 'workbench'
            if _id(kind,sid) in existing: continue
            title=str(data.get('title') or data.get('topic') or '历史创作')[:240]
            original_html=str(data.get('html') or '') if writer else ''
            draft=_html_to_markdown(original_html) if writer else str(data.get('article') or '')
            messages=data.get('messages') if writer else data.get('conversation')
            raw_versions = data.get('versions')
            versions=[x.get('article') for x in raw_versions if isinstance(x,dict)] if isinstance(raw_versions,list) else []
            if not draft and not _messages(messages): continue
            rows.append({'id':_id(kind,sid),'user_id':user_id,'title':f'【历史】{title}'[:240],
                'version':1,'state':_state(title,draft,messages or [],versions,{'kind':kind,'id':sid},data.get('images'),
                    original_html if writer else data.get('typeset_html','')),
                'updated_at':str(updated or repo.now())})
    if {'conversations','artifacts','messages'}.issubset(existing_tables):
        with database.ENGINE.connect() as db:
            conversations=db.execute(select(Conversation.id,Conversation.title,Conversation.updated_at)
                .where(Conversation.user_id==user_id,Conversation.skill_id=='wechat_writer')).all()
            for sid,title,updated in conversations:
                if _id('conversation',sid) in existing: continue
                artifacts=db.execute(select(Artifact.type,Artifact.content,Artifact.version)
                    .where(Artifact.conversation_id==sid,Artifact.user_id==user_id,
                           Artifact.type.in_(['article','markdown'])).order_by(Artifact.version)).all()
                messages=db.execute(select(ConversationMessage.role,ConversationMessage.content)
                    .where(ConversationMessage.conversation_id==sid,
                           ConversationMessage.role.in_(['user','assistant']))
                    .order_by(ConversationMessage.created_at,ConversationMessage.id)).all()
                images=db.execute(select(Artifact.storage_url).where(
                    Artifact.conversation_id==sid, Artifact.user_id==user_id, Artifact.type=='image')).scalars().all()
                formatted=db.execute(select(Artifact.content).where(
                    Artifact.conversation_id==sid, Artifact.user_id==user_id, Artifact.type=='html')
                    .order_by(Artifact.version.desc()).limit(1)).scalar() or ''
                texts=[a.content for a in artifacts if a.content]
                if not texts and not messages: continue
                label=str(title or '历史创作')[:240]
                rows.append({'id':_id('conversation',sid),'user_id':user_id,'title':f'【历史】{label}'[:240],
                    'version':1,'state':_state(label,texts[-1] if texts else '',
                        [{'role':m.role,'content':m.content} for m in messages],texts,{'kind':'conversation','id':sid},
                        [{'url':url} for url in images], formatted),
                    'updated_at':updated.isoformat() if updated else repo.now()})
    insert = pg_insert if database.ENGINE.dialect.name=='postgresql' else sqlite_insert
    with database.ENGINE.begin() as db:
        for row in rows:
            db.execute(insert(repo.sessions).values(**row).on_conflict_do_nothing(index_elements=['id']))
    return len(rows)
