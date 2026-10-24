import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests import support
from server import accounts, qihaoshou as q, qihaoshou_topics as topics, workbench
from server.main import app


def ideas():
    return {'items':[{'title':'从记录到文章'+str(i),'angle':'解释一个具体问题','outline':'记录素材；确认事实；组织表达','reason':'读者可以立即尝试','source_ids':['0']} for i in range(3)]}


def research():
    return {'sources':[{'title':'真实资讯样本','url':'https://example.com/news','excerpt':'这是来源摘要，不是已核实全文。','published_at':datetime.now(timezone.utc).isoformat(),'provider':'test-feed'}]}


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        user=self.client.post('/api/auth/register',json={'email':uuid.uuid4().hex+'@example.com','password':'testing-pass-123','display_name':'选题测试'}).json()['user']
        self.uid=user['id']
        accounts.recharge(self.uid,self.uid,100,'trial','selection tests')

    def balance(self):return self.client.get('/api/wallet').json()['wallet']['balance']

    def test_topics_billed_source_bound_and_refunded_on_invalid_model(self):
        with patch.object(q,'provider_ready'), patch.object(topics,'source_search',return_value=research()), patch.object(workbench,'_json_text',return_value=ideas()):
            r=self.client.post('/api/qihaoshou/topics',json={'direction':'写作'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(r.json()['items']),3)
        self.assertEqual(r.json()['items'][0]['sources'][0]['url'],'https://example.com/news')
        self.assertEqual(self.balance(),97)
        invalid=ideas();invalid['items'][0]['source_ids']=['fake']
        with patch.object(q,'provider_ready'), patch.object(topics,'source_search',return_value=research()), patch.object(workbench,'_json_text',return_value=invalid):
            r=self.client.post('/api/qihaoshou/topics',json={'direction':'写作'})
        self.assertEqual(r.status_code,502);self.assertEqual(self.balance(),97)

    def test_topics_no_sources_are_explicitly_evergreen(self):
        result=ideas()
        for row in result['items']:row['source_ids']=[]
        with patch.object(q,'provider_ready'),patch.object(workbench,'_json_text',return_value=result),patch.object(topics,'source_search') as search:
            r=self.client.post('/api/qihaoshou/topics',json={'research':False})
        search.assert_not_called()
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['items'][0]['kind'],'常青选题')
        self.assertIn('未取得',r.json()['notice'])

    def test_recent_news_requires_real_dates_and_rejects_stale_future_unknown(self):
        data=research();now=datetime.now(timezone.utc)
        for date in [(now-timedelta(days=5)).isoformat(),(now+timedelta(days=5)).isoformat(),'未知']:
            data['sources'].append({**data['sources'][0],'published_at':date})
        with patch.object(topics,'source_search',return_value=data):
            r=self.client.get('/api/qihaoshou/hotspots?category=科技')
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(r.json()['items']),1)
        self.assertEqual(self.balance(),100)
        with patch.object(topics,'source_search',return_value={'sources':[]}):
            self.assertEqual(self.client.get('/api/qihaoshou/hotspots').status_code,503)
        self.assertEqual(self.client.get('/api/qihaoshou/hotspots?category=bad').status_code,400)

    def test_theme_preview_and_style_prompt_and_mode_persistence(self):
        cap=self.client.get('/api/qihaoshou/capabilities').json()
        self.assertEqual(len(cap['styles']),7);self.assertEqual(len(cap['themes']),10)
        for theme in cap['themes']:
            r=self.client.post('/api/qihaoshou/themes/preview',json={'theme':theme['id']})
            self.assertEqual(r.status_code,200);self.assertIn('<h1',r.json()['html'])
        self.assertEqual(self.client.post('/api/qihaoshou/themes/preview',json={'theme':'bad'}).status_code,400)
        data=self.client.post('/api/qihaoshou/sessions',json={'topic':'写作','mode':'ai','angle':'事实与观点分开','outline':'素材；核实；成文','source_notes':'待核实来源 https://example.com','style':'sharp','theme':'forest'}).json()
        prompt=q.draft_prompt(data)
        self.assertIn(q.STYLE_GUIDES['sharp'],prompt);self.assertIn('事实与观点分开',prompt);self.assertIn('待核实来源',prompt)
        loaded=self.client.get('/api/qihaoshou/sessions/'+data['id']).json()
        self.assertEqual(loaded['outline'],'素材；核实；成文')
        data.update(mode='rewrite',reference='已提供的参考正文，说明一个真实问题和边界。')
        self.assertIn('已提供的参考正文',q.draft_prompt(data))
        data['reference']=''
        with self.assertRaises(workbench.ProviderError):q.draft_prompt(data)

    def test_selection_apis_require_login(self):
        anonymous=TestClient(app)
        self.assertEqual(anonymous.post('/api/qihaoshou/topics',json={}).status_code,401)
        self.assertEqual(anonymous.get('/api/qihaoshou/hotspots').status_code,401)
        self.assertEqual(anonymous.post('/api/qihaoshou/themes/preview',json={'theme':'green'}).status_code,401)

    def test_search_does_not_mix_unrelated_feed_fallbacks_into_category(self):
        rows=[{'title':'教育课堂的教学工具','url':'https://example.com/education','query':''},
              {'title':'无关的芯片新闻','url':'https://example.com/chip','query':''}]
        with patch.dict(topics._CACHE,clear=True),patch.object(topics.workbench_research,'search',return_value={'sources':rows}):
            result=topics.source_search('教育')
        self.assertEqual([x['title'] for x in result['sources']],['教育课堂的教学工具'])
