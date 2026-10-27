import base64
import io
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from PIL import Image
from tests import support  # isolated DB before app import
from server import accounts, qihaoshou as q, workbench
from server.main import app


class WritingStudioTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.user=self.client.post('/api/auth/register',json={'email':uuid.uuid4().hex+'@example.com','password':'testing-pass-123','display_name':'写作测试'}).json()['user']
        self.admin=TestClient(app)
        self.admin.post('/api/auth/login',json={'email':'admin@example.com','password':'testing-pass-123'})
        self.admin.post('/api/admin/recharge',json={'user_id':self.user['id'],'points':100,'bucket':'trial','note':'writing tests'})
        self.data=self.client.post('/api/qihaoshou/sessions',json={'topic':'如何建立真实的写作习惯','html':'<h1>写作习惯</h1><p>2026年每天记录10分钟，不把工具当作结果。</p>'}).json()

    def op(self,data=None):
        d=data or self.data
        return {'session_id':d['id'],'revision':d['revision'],'request_id':uuid.uuid4().hex}

    def balance(self):return self.client.get('/api/wallet').json()['wallet']['balance']

    def test_menu_page_and_auth(self):
        self.assertEqual(self.client.get('/qihaoshou').status_code,200)
        self.assertIn('data-view="one-click-writing"',self.client.get('/').text)
        self.assertEqual(TestClient(app).get('/api/qihaoshou/sessions').status_code,401)
        self.assertFalse(self.client.get('/api/qihaoshou/capabilities').json()['wechat'])

    def test_owned_persistence_and_stale_revision(self):
        other=TestClient(app)
        other.post('/api/auth/register',json={'email':uuid.uuid4().hex+'@example.com','password':'testing-pass-123','display_name':'other'})
        self.assertEqual(other.get('/api/qihaoshou/sessions/'+self.data['id']).status_code,404)
        result=self.client.put('/api/qihaoshou/sessions/'+self.data['id'],json={**self.data,'title':'已经保存'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['revision'],1)
        self.assertEqual(self.client.put('/api/qihaoshou/sessions/'+self.data['id'],json=self.data).status_code,409)
        self.assertEqual(self.client.get('/api/qihaoshou/sessions').json()['sessions'][0]['title'],'已经保存')

    def test_optional_writing_choices_survive_old_client_and_reach_generation(self):
        choices={'writing_goal':'学会操作','content_form':'实操教程','author_material':'已有素材：字段清单'}
        saved=self.client.put('/api/qihaoshou/sessions/'+self.data['id'],json={**self.data,**choices}).json()
        legacy={k:v for k,v in saved.items() if k not in choices}
        legacy['title']='旧版编辑'
        saved=self.client.put('/api/qihaoshou/sessions/'+self.data['id'],json=legacy).json()
        self.assertEqual({k:saved[k] for k in choices},choices)
        captured=[]
        def tokens(prompt,cancel):
            captured.append(prompt)
            yield '# 标题\n\n'+'依据给定材料解释步骤。'*10
        with patch.object(q,'provider_ready'),patch.object(q,'text_stream',side_effect=tokens):
            result=self.client.post('/api/qihaoshou/generate',json=self.op(saved))
        self.assertIn('"done": true',result.text)
        for value in choices.values(): self.assertIn(value,captured[0])
        restored=self.client.get('/api/qihaoshou/sessions/'+self.data['id']).json()
        self.assertEqual({k:restored[k] for k in choices},choices)

    def test_empty_optional_choices_and_explicit_fiction_keep_writing_path(self):
        draft=q.Draft(topic='创作一个虚构故事',content_form='故事').model_dump()
        prompt=q.draft_prompt(draft)
        self.assertIn('可选读者目标：自动判断',prompt)
        self.assertIn('用户明确要求小说、虚构故事',prompt)
        self.assertIn('不得冒充真实人物',prompt)
        self.assertEqual(q.Draft(topic='普通主题').writing_goal,'')

    def test_editor_sanitization_preserves_format_but_not_active_content(self):
        raw='<script>alert(1)</script><p onclick="x()" style="text-align:center;color:red;background:url(http://x)">正文<b>加粗</b></p><img src="https://example.com/track"><iframe src="x"></iframe>'
        value=q.clean_html(raw,self.data['id'])
        for text in ['script','onclick','iframe','url(','https://example.com']:
            self.assertNotIn(text,value)
        self.assertIn('text-align:center',value)
        self.assertIn('<b>加粗</b>',value)
        for _ in range(3):
            self.data=self.client.post('/api/qihaoshou/render',json=self.op()).json()
        self.assertEqual(self.data['html'].count('max-width:680px'),1)
        self.assertIn('2026',self.data['html'])

    def test_generate_stream_persists_and_charges_once(self):
        def tokens(prompt,cancel):
            yield '# 真实写作标题\n\n'
            yield '先记录今天发生的事情，再整理可以核对的素材。不要为了凑篇幅编造经历。每天完成一段具体的内容，然后检查事实和表达。'
        payload=self.op()
        with patch.object(q,'provider_ready'),patch.object(q,'text_stream',side_effect=tokens):
            result=self.client.post('/api/qihaoshou/generate',json=payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertIn('"token"',result.text)
        self.assertIn('"done": true',result.text)
        self.assertEqual(self.balance(),90)
        saved=self.client.get('/api/qihaoshou/sessions/'+self.data['id']).json()
        self.assertEqual(saved['revision'],1)
        self.assertEqual(saved['title'],'真实写作标题')
        # A stale duplicate is rejected before any second billing.
        with patch.object(q,'provider_ready'),patch.object(q,'text_stream') as stream:
            retry=self.client.post('/api/qihaoshou/generate',json={**payload,'revision':1})
        self.assertEqual(retry.status_code,409)
        stream.assert_not_called();self.assertEqual(self.balance(),90)

    def test_partial_provider_failure_refunds_and_preserves_original(self):
        def fail(prompt,cancel):
            yield '# 不完整的新稿\n'
            raise workbench.ProviderError('模型流意外中断，原稿已保留')
        before=self.balance()
        with patch.object(q,'provider_ready'),patch.object(q,'text_stream',side_effect=fail):
            result=self.client.post('/api/qihaoshou/generate',json=self.op())
        self.assertIn('"error"',result.text);self.assertNotIn('"done": true',result.text)
        self.assertEqual(self.balance(),before)
        self.assertEqual(self.client.get('/api/qihaoshou/sessions/'+self.data['id']).json()['html'],self.data['html'])

    def test_missing_points_blocks_provider(self):
        with accounts.DB_LOCK,accounts._connect() as c:
            c.execute('UPDATE wallets SET balance=0,trial_balance=0 WHERE user_id=?',(self.user['id'],))
        with patch.object(q,'provider_ready'),patch.object(q,'text_stream') as stream:
            result=self.client.post('/api/qihaoshou/generate',json=self.op())
        self.assertEqual(result.status_code,402);stream.assert_not_called()

    def test_titles_and_invalid_deai_refund(self):
        with patch.object(q,'provider_ready'),patch.object(workbench,'_json_text',return_value={'titles':['如何开始写作','先记录，再创作']}):
            result=self.client.post('/api/qihaoshou/titles',json=self.op())
        self.assertEqual(result.json()['titles'][0],'如何开始写作');self.assertEqual(self.balance(),97)
        with patch.object(q,'provider_ready'),patch.object(workbench,'_json_text',return_value={'paragraphs':['错误标题','2027年每天记录20分钟']}):
            result=self.client.post('/api/qihaoshou/deai',json=self.op())
        self.assertEqual(result.status_code,502);self.assertEqual(self.balance(),97)
        self.assertEqual(self.client.get('/api/qihaoshou/sessions/'+self.data['id']).json()['html'],self.data['html'])

    def test_deai_changes_review_undo_and_noop_refund(self):
        old = self.data['html']
        review = dict(facts_preserved=True, stance_preserved=True, conditions_preserved=True, no_invention=True, readable=True, issues=[])
        with patch.object(q,'provider_ready'), patch.object(workbench,'_json_text',side_effect=[{'edits':[{'id':'0','text':'2026年，每天花10分钟记录；别把工具当作结果。'}]},review]):
            result = self.client.post('/api/qihaoshou/deai',json=self.op())
        self.assertEqual(result.status_code,200,result.text)
        self.data = result.json()
        self.assertEqual(self.balance(),95)
        self.assertEqual(self.data['deai_review']['before_html'],old)
        self.assertIn('别把工具',self.data['html'])
        restored = self.client.post('/api/qihaoshou/deai-undo',json=self.op())
        self.assertEqual(restored.status_code,200,restored.text)
        self.data = restored.json()
        self.assertEqual(self.data['html'],old)
        self.assertEqual(self.balance(),95)
        with patch.object(q,'provider_ready'), patch.object(workbench,'_json_text',return_value={'edits':[{'id':'0','text':'2026年每天记录10分钟，不把工具当作结果。'}]}):
            result = self.client.post('/api/qihaoshou/deai',json=self.op())
        self.assertEqual(result.status_code,502)
        self.assertEqual(self.balance(),95)

    def test_image_insert_owned_asset_and_failed_image_refund(self):
        buffer=io.BytesIO();Image.new('RGB',(16,16),'green').save(buffer,'PNG')
        with tempfile.TemporaryDirectory() as folder,patch.object(q,'OUTPUT',Path(folder)),patch.object(q,'provider_ready'),patch.object(q.image_provider,'generate',return_value={'data':[{'b64_json':base64.b64encode(buffer.getvalue()).decode()}]}):
            result=self.client.post('/api/qihaoshou/image',json={**self.op(),'prompt':'明亮书桌'})
            self.assertEqual(result.status_code,200,result.text)
            self.data=result.json();url=self.data['images'][0]['url']
            self.assertEqual(self.client.get(url).status_code,200)
            self.assertEqual(self.admin.get(url).status_code,404)
            self.assertIn(url,self.data['html'])
        self.assertEqual(self.balance(),70)
        with patch.object(q,'provider_ready'),patch.object(q.image_provider,'generate',side_effect=RuntimeError('offline')):
            result=self.client.post('/api/qihaoshou/image',json={**self.op(),'prompt':'书桌'})
        self.assertEqual(result.status_code,502);self.assertEqual(self.balance(),70)

    def test_wechat_needs_admin_confirmation_and_no_false_success(self):
        self.assertEqual(self.client.post('/api/qihaoshou/wechat-draft',json={**self.op(),'confirm':True}).status_code,403)
        data=self.admin.post('/api/qihaoshou/sessions',json={'title':'确认稿','html':'<h1>确认稿</h1><p>已核对的完整正文内容，用于草稿箱接口测试。</p>'}).json()
        self.assertEqual(self.admin.post('/api/qihaoshou/wechat-draft',json=self.op(data)).status_code,400)
        admin_uid=self.admin.get('/api/auth/me').json()['user']['id']
        name='a'*32+'.jpg';url=f"/api/qihaoshou/assets/{data['id']}/{name}"
        data['images']=[{'file':name,'url':url}];data['html']+=f'<p><img src="{url}"></p>'
        accounts.save_workbench_session(admin_uid,data)
        with tempfile.TemporaryDirectory() as folder,patch.object(q,'OUTPUT',Path(folder)),patch.dict('os.environ',{'WECHAT_APPID':'test','WECHAT_SECRET':'test'}):
            directory=Path(folder)/data['id'];directory.mkdir();(directory/name).write_bytes(b'fixture-image')
            def call(client,url,**kwargs):
                if url.endswith('token'):return {'access_token':'fixture-token'}
                if url.endswith('uploadimg'):return {'url':'https://mmbiz.qpic.cn/fixture'}
                if url.endswith('add_material'):return {'media_id':'cover-fixture'}
                return {'media_id':'draft-fixture'}
            with patch.object(q,'wechat_call',side_effect=call) as remote:
                result=self.admin.post('/api/qihaoshou/wechat-draft',json={**self.op(data),'confirm':True})
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual(result.json()['media_id'],'draft-fixture')
                replay=self.admin.post('/api/qihaoshou/wechat-draft',json={**self.op(data),'confirm':True})
                self.assertEqual(replay.json()['media_id'],'draft-fixture')
                self.assertEqual(remote.call_count,4)

    def test_provider_truncated_output_is_not_success(self):
        response=MagicMock();response.ok=True;response.headers={'Content-Type':'text/event-stream'}
        response.iter_lines.return_value=['data: {"choices":[{"delta":{"content":"正文"}}]}','data: [DONE]']
        response.__enter__.return_value=response
        client=MagicMock();client.__enter__.return_value=client;client.post.return_value=response
        with patch.object(q.requests,'Session',return_value=client),patch.dict('os.environ',{'WECHAT_TEXT_API_KEY':'fixture-key'}):
            with self.assertRaises(workbench.ProviderError):list(q.text_stream('测试',threading.Event()))



    def test_responses_stream_uses_configured_endpoint_and_real_deltas(self):
        response=MagicMock();response.ok=True;response.headers={'Content-Type':'text/event-stream'}
        response.iter_lines.return_value=[
            'event: response.output_text.delta',
            'data: '+json.dumps({'type':'response.output_text.delta','delta':'真实正文'}),
            'data: '+json.dumps({'type':'response.completed','response':{'status':'completed'}})]
        response.__enter__.return_value=response
        client=MagicMock();client.__enter__.return_value=client;client.post.return_value=response
        settings={'WECHAT_TEXT_API_BASE_URL':'https://example.test/v1/responses','WECHAT_TEXT_API_KEY':'fixture','WECHAT_TEXT_MODEL':'test-model'}
        with patch.object(q.requests,'Session',return_value=client),patch.object(workbench,'_setting',side_effect=lambda key,default='':settings.get(key,default)):
            self.assertEqual(list(q.text_stream('材料',threading.Event())),['真实正文'])
        args,kwargs=client.post.call_args
        self.assertEqual(args[0],'https://example.test/v1/responses')
        self.assertIn('input',kwargs['json']);self.assertNotIn('messages',kwargs['json'])
        self.assertTrue(kwargs['json']['stream'])

    def test_incomplete_responses_is_rejected(self):
        response=MagicMock();response.ok=True;response.headers={'Content-Type':'text/event-stream'}
        response.iter_lines.return_value=['data: '+json.dumps({'type':'response.incomplete','response':{'status':'incomplete'}})]
        response.__enter__.return_value=response
        client=MagicMock();client.__enter__.return_value=client;client.post.return_value=response
        settings={'WECHAT_TEXT_API_BASE_URL':'https://example.test/v1/responses','WECHAT_TEXT_API_KEY':'fixture'}
        with patch.object(q.requests,'Session',return_value=client),patch.object(workbench,'_setting',side_effect=lambda key,default='':settings.get(key,default)):
            with self.assertRaises(workbench.ProviderError):list(q.text_stream('材料',threading.Event()))


if __name__=='__main__':unittest.main()
