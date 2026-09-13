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
    def test_image_plan_retries_schema_without_fabricating_fields(self):
        invalid = {'reason': '方向', 'images': [{'kind': 'cover', 'prompt': '封面'}]}
        valid = {'reason': '方向', 'images': [{'kind': 'cover', 'prompt': '封面', 'caption': 'AI示意图'}]}
        session = {'id': 'test', 'article': '正文。', 'brief': '一张封面'}
        with patch.object(skill_runtime, 'context', return_value=('Skill', ['SKILL.md'])), \
             patch.object(w, '_json_text', side_effect=[invalid, valid]) as generate, \
             patch.object(w, '_record_skill'):
            plan = w._image_plan(session)
        self.assertEqual(generate.call_count, 2)
        self.assertIn('缺少caption', generate.call_args_list[1].args[0])
        self.assertEqual(plan['images'], valid['images'])

    def test_topic_node_must_run_skill_hotspot_script(self):
        topics = [{'title': f'方向{i}', 'type': '观点', 'reason': '可展开', 'heat': 7, 'fan_score': 70, 'competition': '中'} for i in range(10)]
        session = {'skill_execution': []}
        with patch.object(w, '_require_skill'), \
             patch.object(skill_runtime, 'context', return_value=('Skill', [{'file': 'SKILL.md'}])), \
             patch.object(skill_runtime, 'script', return_value=[{'title': '真实热点'}]) as run_skill, \
             patch.object(research, 'search', return_value={'status': 'ok', 'sources': []}), \
             patch.object(research, 'history', return_value={'titles': [], 'status': 'checked'}), \
             patch.object(w, '_json_text', return_value={'topics': topics}):
            result = w._suggestions('测试方向', '观察者', session)
        run_skill.assert_called_once_with(w.SKILL_DIR, 'fetch_hotspots.py', '--source', 'all', '--limit', '30')
        self.assertEqual(len(result), 10)
        self.assertEqual(session['skill_execution'][-1]['status'], 'passed')

    def test_skill_gate_blocks_unexecuted_nodes(self):
        session = {'enforce_skill_pipeline': True, 'skill_execution': [
            {'step': 1, 'status': 'passed'},
        ]}
        with self.assertRaises(w.ProviderError):
            w._require_skill_steps(session, 3)

    def test_skill_markdown_contains_content_led_dsl_modules(self):
        article = '## 第一节\n\n第一段正文。\n\n值得记住的一句。'
        result = w._skill_dsl_article(article, {'emphasis': '值得记住的一句。'})
        self.assertIn(':::callout', result)
        self.assertIn(':::quote', result)
        self.assertIn('第一段正文。', result)

    def test_review_passes_protection_failure_back_to_editor(self):
        good = {'issues': [], 'reason': 'readable', 'fidelity_ok': True, 'readability_ok': True}
        diagnosis = {**good, 'issues': [{'quote': '“原话”', 'reason': 'style', 'fix': 'outside quote only'}]}
        prompts = []
        replies = iter([diagnosis, {'edits': [], 'retained_issue_indexes': [0]}, good])
        def generate(prompt):
            prompts.append(prompt)
            return next(replies)
        audits = [{'status': 'success', 'complete_sentence_ratio': 1, 'missing_protected_spans': {}}] * 2
        with tempfile.TemporaryDirectory() as directory, patch.object(w, 'OUTPUT_DIR', Path(directory)), patch.object(skill_runtime, 'context', return_value=('Skill', [])), patch.object(skill_runtime, 'script', return_value={}), patch.object(w, '_json_text', side_effect=generate), patch.object(w, '_anti_ai_audit', side_effect=audits):
            article, review = w._review('“原话”', {'id': 'test'})
        self.assertEqual(article, '“原话”')
        self.assertEqual(review['gate'], 'passed')
        self.assertEqual(review['rounds'][0]['retained_by_protection'][0]['quote'], '“原话”')

    def test_preview_keeps_content_warning_without_blocking_conversion(self):
        from server import skill_preview
        converter, theme, quality = (types.ModuleType(name) for name in ('toolkit.converter', 'toolkit.theme', 'toolkit.recommendation_quality'))
        engine = unittest.mock.Mock()
        engine.convert.return_value = '<p>unchanged</p>'
        converter.MarkdownConverter = lambda: engine
        theme.load_theme = lambda name: name
        theme.apply_theme = lambda content, name: content
        quality.check_article_file = lambda *a, **k: {'blocked': True, 'findings': ['review before publishing']}
        leaf = types.ModuleType('leaf_autofix')
        class TestLeafWrapper:
            def feed(self, value): self.value = value
            def close(self): pass
            def result(self): return self.value
        leaf.LeafWrapper = TestLeafWrapper
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'article.md'
            path.write_text('unchanged', encoding='utf-8')
            with patch.dict(sys.modules, {'toolkit.converter': converter, 'toolkit.theme': theme, 'toolkit.recommendation_quality': quality, 'leaf_autofix': leaf}), patch.object(sys, 'argv', ['preview', directory, str(path), 'default']), patch.object(sys, 'path', list(sys.path)):
                skill_preview.main()
            engine.convert.assert_called_once_with('unchanged')
            self.assertIn('<p>unchanged</p>', path.with_name('article_preview.html').read_text(encoding='utf-8'))
            self.assertTrue(json.loads(path.with_suffix('.quality.json').read_text())['blocked'])
            self.assertEqual(json.loads(path.with_suffix('.render.json').read_text())['renderer'], 'toolkit.converter.MarkdownConverter')

    def test_no_images_chat_typesets_without_rewriting_or_generating(self):
        article = '已确认正文。'
        session = {'id': 'no-images', 'current_step': 5, 'article': article,
                   'framework': {}, 'images': [{'url': '/old.jpg'}],
                   'review': {'gate': 'passed', 'article_sha256': skill_runtime.digest(article)}}
        def typeset(current):
            self.assertEqual(current['images'], [])
            current['typeset_html'] = '<p>' + current['article'] + '</p>'
        with patch.object(w, '_get_session', return_value=session), \
             patch.object(w, '_save_session') as save, \
             patch.object(w.skill_runtime, 'context', return_value=('rules', [])), \
             patch.object(w, '_json_text', return_value={'action': 'typeset', 'image_policy': 'none'}), \
             patch.object(w, '_typeset', side_effect=typeset), \
             patch.object(w, '_images') as images, \
             patch.object(w, '_image_plan') as plan, \
             patch.object(w, '_draft') as draft:
            result = w.chat('no-images', '不要图片直接排版', user_id='user')
        images.assert_not_called()
        plan.assert_not_called()
        draft.assert_not_called()
        self.assertEqual(result['article'], article)
        self.assertEqual(result['current_step'], 6)
        self.assertEqual(result['image_policy'], 'none')
        self.assertEqual(session['images'], [{'url': '/old.jpg'}])
        save.assert_called_once()

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
