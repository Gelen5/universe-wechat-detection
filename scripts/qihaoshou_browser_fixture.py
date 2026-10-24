"""Local integration fixture. Only external providers/WeChat are simulated."""
import base64
import io
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
folder=tempfile.TemporaryDirectory(prefix='qhs-browser-')
os.environ.update(DATABASE_URL='sqlite:///'+(Path(folder.name)/'accounts.db').as_posix(),APP_ENV='development',
 CREATOR_ACCOUNTS_DB=str(Path(folder.name)/'accounts.db'),CREATOR_OWNER_EMAIL='writer-test@example.com',
 CREATOR_ADMIN_PASSWORD='writer-test-123',CREATOR_NEW_USER_TRIAL_POINTS='0',
 WECHAT_TEXT_API_KEY='local-fixture',WECHAT_TEXT_API_BASE_URL='http://127.0.0.1:8895/v1/responses',WECHAT_TEXT_MODEL='fixture',
 WECHAT_IMAGE_API_KEY='local-fixture',WECHAT_IMAGE_API_BASE_URL='http://127.0.0.1:8895/v1',
 WECHAT_APPID='fixture',WECHAT_SECRET='fixture')
from PIL import Image
buffer=io.BytesIO();Image.new('RGB',(400,300),'#b6d5c1').save(buffer,'PNG')
encoded=base64.b64encode(buffer.getvalue()).decode()
ARTICLE='# 从一段记录开始写作\n\n先记录今天发生的事情，再把可以核对的素材整理出来。每次写作都从一个具体问题开始，给读者一个清楚的回答。\n\n## 把表达与排版分开\n\n内容先保证准确，再调整段落和标题。每天用10分钟记录，逐渐形成自己的素材。\n\n> 一篇文章，先把一件事情说明白。'
class Provider(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  self.send_response(200)
  if self.path.endswith('/images/generations'):
   self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'data':[{'b64_json':encoded}]}).encode());return
  prompt=(data.get('messages') or data.get('input'))[-1]['content']
  if '为公众号生成5个' in prompt:result={'items':[{'title':'把记录写成文章'+str(i),'angle':'从真实素材开始','outline':'记录；核实；组织','reason':'创作者可直接实践','source_ids':['0']} for i in range(3)]}
  elif '拟5个' in prompt:result={'titles':['从一段记录开始写作','把素材整理成自己的文章','先把一件事情说明白']}
  elif '你是独立校对编辑' in prompt:result=dict(facts_preserved=True,stance_preserved=True,conditions_preserved=True,no_invention=True,readable=True,issues=[])
  elif '你是中文深度编辑' in prompt:
   blocks=json.loads(prompt.split('材料：',1)[1])
   result={'edits':[{'id':part['id'],'text':part['text'].replace('先记录今天发生的事情','先把今天发生的事记下来')} for block in blocks for part in block['parts']]}

  else:result=None
  text=json.dumps(result,ensure_ascii=False) if result else ARTICLE
  if data.get('stream'):
   self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
   try:
    for i in range(0,len(text),14):
     event={'type':'response.output_text.delta','delta':text[i:i+14]} if self.path.endswith('/responses') else {'choices':[{'delta':{'content':text[i:i+14]}}]}
     self.wfile.write(('data: '+json.dumps(event,ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(.12)
    final={'type':'response.completed','response':{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}} if self.path.endswith('/responses') else {'choices':[{'delta':{},'finish_reason':'stop'}]}
    self.wfile.write(('data: '+json.dumps(final,ensure_ascii=False)+'\n\n'+('' if self.path.endswith('/responses') else 'data: [DONE]\n\n')).encode());self.wfile.flush()
   except (BrokenPipeError,ConnectionResetError):pass
   return
  self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'choices':[{'message':{'content':text}}]},ensure_ascii=False).encode())
threading.Thread(target=ThreadingHTTPServer(('127.0.0.1',8895),Provider).serve_forever,daemon=True).start()
from server.main import app
from server import accounts,qihaoshou,qihaoshou_topics
from datetime import datetime,timezone
qihaoshou_topics.source_search=lambda query: {"checked_at":datetime.now(timezone.utc).isoformat(),"sources":[{"title":"近期创作工具资讯样本","url":"https://example.com/news","excerpt":"本地测试资讯摘要。","published_at":datetime.now(timezone.utc).isoformat(),"provider":"local-fixture"}]}
qihaoshou.OUTPUT=Path(folder.name)/'images'
owner=accounts.authenticate('writer-test@example.com','writer-test-123')
accounts.recharge(owner['id'],owner['id'],500,'trial','local fixture')
def wechat(client,url,**kwargs):
 if url.endswith('token'):return {'access_token':'fixture'}
 if url.endswith('uploadimg'):return {'url':'https://mmbiz.qpic.cn/fixture'}
 if url.endswith('add_material'):return {'media_id':'fixture-cover'}
 return {'media_id':'fixture-draft'}
qihaoshou.wechat_call=wechat
import uvicorn
uvicorn.run(app,host='127.0.0.1',port=8894,log_level='warning')
