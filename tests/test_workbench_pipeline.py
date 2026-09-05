import tempfile
import unittest
import json
import base64
import importlib.util
import types
import sys
from pathlib import Path
from unittest.mock import patch
from server import workbench as w, workbench_research as research, task_worker
from server import skill_runtime


class PipelineTests(unittest.TestCase):
    def test_changing_theme_keeps_layout_node_and_article_assets(self):
        article = "已经确认的正文。"
        session = {
            "id": "theme-session", "user_id": "user", "current_step": 6,
            "theme": "default", "article": article, "framework": {},
            "review": {"gate": "passed", "article_sha256": skill_runtime.digest(article)},
            "image_plan": {"status": "generated"}, "images": [{"url": "/image.jpg"}],
            "typeset_html": "old", "preview_document": "old", "conversation": [], "versions": [],
        }

        def fake_typeset(current):
            current["typeset_html"] = "new"
            current["preview_document"] = "new-document"

        with patch.object(w, "_get_session", return_value=session), patch.object(w, "_save_session"), patch.object(w, "_typeset", side_effect=fake_typeset):
            result = w.chat("theme-session", "换个排版主题", "change_theme", user_id="user")

        self.assertEqual(result["current_step"], 6)
        self.assertEqual(result["theme"], "minimal-elegant")
        self.assertEqual(result["article"], article)
        self.assertEqual(result["images"], [{"url": "/image.jpg"}])
        self.assertEqual(result["versions"], [])
        self.assertEqual(result["typeset_source"], None)

    def test_delivery_uploads_embedded_image_and_keeps_approved_html(self):
        path = w.ROOT / 'scripts/workbench-skill-publish.py'
        spec = importlib.util.spec_from_file_location('delivery_test',path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        api = unittest.mock.Mock()
        api.upload_image.return_value = 'https://mmbiz.qpic.cn/verified.jpg'
        api.upload_cover.return_value = 'cover-id'
        api.add_draft_multi.return_value = 'draft-id'
        config, wechat, quality = (types.ModuleType(name) for name in ('toolkit.config','toolkit.wechat_api','toolkit.recommendation_quality'))
        config.get_config = lambda: {}
        wechat.WeChatAPI = lambda _: api
        quality.check_article_file = lambda *a,**k: {'blocked':False}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'images').mkdir()
            (root/'images/cover.jpg').write_bytes(b'image')
            (root/'delivery.json').write_text(json.dumps({'title':'标题','cover':str(root/'images/cover.jpg')}),encoding='utf-8')
            (root/'approved.html').write_text('<p style="color:#123456">已确认正文</p><img src="data:image/jpeg;base64,'+base64.b64encode(b'image').decode()+'">',encoding='utf-8')
            with patch.dict(sys.modules,{'toolkit.config':config,'toolkit.wechat_api':wechat,'toolkit.recommendation_quality':quality}), patch.object(sys,'argv',['publish',str(root),str(root)]), patch('builtins.print'):
                module.main()
            payload = api.add_draft_multi.call_args.args[0][0]
            self.assertIn('color:#123456',payload['content'])
            self.assertIn('已确认正文',payload['content'])
            self.assertNotIn('data:image',payload['content'])
            self.assertEqual(payload['thumb_media_id'],'cover-id')

    def test_dispatch_claims_only_requested_job(self):
        with patch.object(task_worker.accounts,'job',return_value={'type':'workbench_step','lane':'image'}), patch.object(task_worker.accounts,'claim_job',return_value={'id':'wanted'}) as claim, patch.object(task_worker,'_run') as run:
            with patch.object(task_worker.WORKBENCH_EXECUTOR,'submit',side_effect=lambda fn:fn()):
                task_worker.dispatch_workbench_job('wanted')
            claim.assert_called_once_with(['image'],job_id='wanted')
            run.assert_called_once_with({'id':'wanted'})

    def test_plan_stops_before_generation(self):
        article='测试正文。'
        session={'id':'test','mode':'interactive','article':article,'framework':{},'review':{'gate':'passed','article_sha256':skill_runtime.digest(article)},'images':[]}
        with patch.object(w,'_image_plan',return_value={'status':'awaiting_confirmation','article_sha256':skill_runtime.digest(article)}), patch.object(w,'_images') as images:
            w._advance(session,5)
        images.assert_not_called()
        self.assertEqual(session['current_step'],5)

    def test_edited_article_cannot_skip_new_confirmation(self):
        session={'id':'test','mode':'interactive','current_step':5,'article':'old'}
        with patch.object(w,'_get_session',return_value=session), patch.object(w,'_save_session'):
            with self.assertRaises(w.ProviderError):
                w.step('test',6,article='new',user_id='user')
        self.assertEqual(session['current_step'],3)
        self.assertIsNone(session['image_plan'])

    def test_source_private_ip_rejected(self):
        with patch.object(research.socket,'getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): research.public_url('https://private.test/')

    def test_missing_history_is_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(research.history(Path(directory))['status'],'unavailable')

    def test_actual_component_composition_keeps_text_and_image(self):
        from server.workbench_layout import compose
        if not w.SKILL_DIR.exists(): self.skipTest('Installed Skill not present')
        html=compose('<h1>标题</h1><p>完整观点。</p><p><img src="data:image/jpeg;base64,YQ=="></p><p>图注：AI示意。</p>',w.SKILL_DIR,{'emphasis':'完整观点。'})
        self.assertIn('完整观点。',html)
        self.assertIn('border-left:3px solid #C9A962',html)
        self.assertIn('data:image/jpeg;base64,YQ==',html)
        self.assertNotIn('class=',html)

    def test_actual_lost_quote_blocks_but_quote_punctuation_does_not(self):
        for candidate, allowed in [('原话。',True),('丢失。',False)]:
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as directory, patch.object(w,'OUTPUT_DIR',Path(directory)), patch.object(skill_runtime,'context',return_value=('Skill',[])), patch.object(skill_runtime,'script',return_value={}), patch.object(w,'_json_text',return_value={'issues':[],'reason':'语义检查','fidelity_ok':True,'readability_ok':True}), patch.object(w,'_text',return_value=candidate), patch.object(w,'_anti_ai_audit',return_value={'status':'success','complete_sentence_ratio':1,'missing_protected_spans':{'quoted_text':['“原话”']}}):
                if allowed:
                    result, review=w._review(candidate,{'id':'test'})
                    self.assertEqual(review['gate'],'passed')
                else:
                    with self.assertRaises(w.ProviderError): w._review(candidate,{'id':'test'})
