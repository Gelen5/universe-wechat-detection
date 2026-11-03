from sqlalchemy import MetaData, Table, Column, String, Text, insert, select
from tests import test_wechat_plus_api as fixtures
from server import wechat_plus_legacy as migration, wechat_plus_repository as repo
import json

def test_legacy_history_migration_keeps_ownership_versions_and_new_edits():
 case=fixtures.PlusAPITests(methodName='runTest'); case.setUp()
 try:
  old=Table('workbench_sessions',MetaData(),Column('id',String,primary_key=True),Column('user_id',String),Column('payload_json',Text),Column('updated_at',String))
  old.create(case.engine)
  records=[
   {'id':'writer_a','user_id':'owner','payload_json':json.dumps({'kind':'qihaoshou','title':'旧一键','html':'<p>旧正文<img src="/api/qihaoshou/assets/writer_a/pic.jpg"></p>','messages':[{'role':'user','content':'旧要求'}]}),'updated_at':'2026-11-01T00:00:00+00:00'},
   {'id':'old_a','user_id':'owner','payload_json':json.dumps({'pipeline_version':1,'topic':'旧创作','article':'最终稿','versions':[{'article':'初稿'}],'conversation':[{'role':'user','content':'写一篇'}]}),'updated_at':'2026-11-01T00:00:00+00:00'},
   {'id':'other','user_id':'other','payload_json':json.dumps({'kind':'qihaoshou','html':'其他用户隐私'}),'updated_at':'2026-11-01T00:00:00+00:00'},
   {'id':'tie','user_id':'owner','payload_json':json.dumps({'conversation_skill':'tie-tu','article':'贴图不应迁移'}),'updated_at':'2026-11-01T00:00:00+00:00'}]
  with case.engine.begin() as db: db.execute(insert(old),records)
  assert migration.migrate_for('owner')==2
  sessions=repo.list_sessions('owner');assert len(sessions)==2
  writer=repo.get(migration._id('one-click','writer_a'),'owner')
  assert '/api/qihaoshou/assets/writer_a/pic.jpg' in writer['state']['article_state']['draft']
  assert '旧正文' in writer['state']['article_state']['draft']
  assert '<p>旧正文' in writer['state']['legacy_preview_html']
  old_row=repo.get(migration._id('workbench','old_a'),'owner')
  assert [x['draft'] for x in old_row['state']['versions']]==['初稿','最终稿']
  state=old_row['state']; state['article_state']['draft']='用户新修改'
  repo.save(old_row['id'],'owner',old_row['version'],state)
  assert migration.migrate_for('owner')==0
  assert repo.get(old_row['id'],'owner')['state']['article_state']['draft']=='用户新修改'
  try: repo.get(writer['id'],'other');assert False
  except KeyError: pass
 finally: case.tearDown()

def test_normalized_conversations_move_only_wechat_articles_and_versions():
 from server.models import Base, Conversation, ConversationMessage, Artifact
 from datetime import datetime, timezone
 case=fixtures.PlusAPITests(methodName='runTest'); case.setUp()
 try:
  Base.metadata.create_all(case.engine)
  now=datetime.now(timezone.utc)
  with case.engine.begin() as db:
   db.execute(insert(Conversation),[{'id':'conv-a','user_id':'owner','title':'旧对话','skill_id':'wechat_writer','mode':'manual','status':'active','metadata_json':{},'created_at':now,'updated_at':now},
     {'id':'conv-other','user_id':'other','title':'其他','skill_id':'wechat_writer','mode':'manual','status':'active','metadata_json':{},'created_at':now,'updated_at':now},
     {'id':'conv-image','user_id':'owner','title':'贴图','skill_id':'easel_skill_content_matrix','mode':'manual','status':'active','metadata_json':{},'created_at':now,'updated_at':now}])
   db.execute(insert(ConversationMessage),[{'id':'msg-a','conversation_id':'conv-a','role':'user','content':'旧对话要求','content_json':{},'metadata_json':{},'created_at':now}])
   db.execute(insert(Artifact),[{'id':'v1','user_id':'owner','conversation_id':'conv-a','run_id':'run-a','type':'article','title':'旧稿','content':'第一版','content_json':{},'version':1,'created_at':now,'updated_at':now},
     {'id':'v2','user_id':'owner','conversation_id':'conv-a','run_id':'run-a','type':'article','title':'旧稿','content':'第二版','content_json':{},'version':2,'created_at':now,'updated_at':now}])
  assert migration.migrate_for('owner')==1
  state=repo.get(migration._id('conversation','conv-a'),'owner')['state']
  assert state['article_state']['draft']=='第二版'
  assert [v['draft'] for v in state['versions']]==['第一版','第二版']
  assert state['messages'][0]['content']=='旧对话要求'
 finally: case.tearDown()

def test_legacy_preview_is_owner_scoped_sandboxed_and_rejects_stale_content():
 case=fixtures.PlusAPITests(methodName='runTest');case.setUp()
 try:
  row=repo.create('owner','历史文章')
  state=migration._state('历史文章','原文',[],[],{'kind':'workbench','id':'old'},formatted='<p>历史排版</p><script>bad()</script>')
  row=repo.save(row['id'],'owner',row['version'],state)
  path='/api/wechat-plus/sessions/'+row['id']+'/legacy-preview'
  r=case.client.get(path,headers=case.headers)
  assert r.status_code==200 and 'sandbox' in r.headers['content-security-policy']
  assert case.client.get(path,headers={'X-Test-User':'other'}).status_code==404
  state['article_state']['draft']='已修改正文';repo.save(row['id'],'owner',row['version'],state)
  assert case.client.get(path,headers=case.headers).status_code==404
 finally:case.tearDown()

def test_legacy_image_is_restricted_to_owning_user(tmp_path, monkeypatch):
 from fastapi import FastAPI
 from fastapi.testclient import TestClient
 from server import legacy_article_media as media
 sid='writer_'+'a'*32; name='b'*32+'.jpg'
 folder=tmp_path/'output'/'qihaoshou'/sid; folder.mkdir(parents=True);(folder/name).write_bytes(b'fake image')
 monkeypatch.setattr(media.workbench,'ROOT',tmp_path)
 monkeypatch.setattr(media.accounts,'require_user',lambda request:{'id':request.headers.get('X-User')})
 monkeypatch.setattr(media.accounts,'load_workbench_session',lambda session_id,user_id: {'kind':'qihaoshou','images':[{'file':name}]} if session_id==sid and user_id=='owner' else None)
 app=FastAPI();app.include_router(media.router);client=TestClient(app)
 path=f'/api/qihaoshou/assets/{sid}/{name}'
 assert client.get(path,headers={'X-User':'owner'}).status_code==200
 assert client.get(path,headers={'X-User':'other'}).status_code==404
 assert client.get(f'/api/qihaoshou/assets/{sid}/not-a-file',headers={'X-User':'owner'}).status_code==404
