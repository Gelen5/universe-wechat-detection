import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import workbench as w, skill_runtime as r


class SkillRuntimeTests(unittest.TestCase):
    def test_modified_article_invalidates_gate(self):
        session = {'article': '原稿', 'review': {'gate': 'passed', 'article_sha256': r.digest('原稿')}}
        self.assertTrue(w._review_is_current(session))
        session['article'] = '修改稿'
        self.assertFalse(w._review_is_current(session))
        with patch.object(w, '_get_session', return_value=session):
            with self.assertRaises(w.ProviderError):
                w.preview('test', user_id='test')
            with self.assertRaises(w.ProviderError):
                w.publish('test', user_id='test')

    def test_brief_survives_topic_selection(self):
        self.assertIn('800—1000字', r.brief({'topic':'选中标题','conversation':[{'role':'user','content':'800—1000字'}]}))

    def test_length_requirement(self):
        self.assertIsNone(r.length_issue('字'*900, '800—1000字'))
        self.assertIsNotNone(r.length_issue('字'*1800, '800—1000字'))

    def test_review_gate(self):
        for issues, candidate, succeeds in [([], '原稿。', True), ([{'quote':'原稿','reason':'空泛'}], '原稿。', False)]:
            with self.subTest(succeeds=succeeds), tempfile.TemporaryDirectory() as d:
                session={'id':'test','brief':'保留事实'}
                with patch.object(w,'OUTPUT_DIR',Path(d)), patch.object(r,'context',return_value=('Skill instructions',[])), patch.object(r,'script',return_value={'signals':[]}), patch.object(w,'_json_text',return_value={'issues':issues,'reason':'逐句核对','fidelity_ok':True,'readability_ok':True}), patch.object(w,'_text',return_value=candidate), patch.object(w,'_anti_ai_audit',return_value={'status':'success','complete_sentence_ratio':1,'missing_protected_spans':{}}):
                    if succeeds:
                        result, review=w._review('原稿。',session)
                        self.assertFalse(review['changed'])
                        self.assertEqual(review['gate'],'passed')
                    else:
                        with self.assertRaises(w.ProviderError): w._review('原稿。',session)
                        self.assertEqual(session['review_run']['status'],'blocked')

    def test_unavailable_audit_blocks(self):
        with tempfile.TemporaryDirectory() as d, patch.object(w,'OUTPUT_DIR',Path(d)), patch.object(r,'context',return_value=('Skill',[])), patch.object(r,'script',return_value={}), patch.object(w,'_json_text',return_value={'issues':[],'reason':'检查','fidelity_ok':True,'readability_ok':True}), patch.object(w,'_text',return_value='原稿。'), patch.object(w,'_anti_ai_audit',return_value={'status':'unavailable'}):
            with self.assertRaises(w.ProviderError): w._review('原稿。',{'id':'test'})

    def test_draft_passes_requirements_and_retries_length(self):
        with patch.object(r,'context',return_value=('REAL SKILL CONTENT',[])), patch.object(w,'_text',side_effect=['字'*1100,'字'*900]) as call:
            article=w._draft('标题',{},'作者','800—1000字，不能编造')
            self.assertEqual(len(article),900)
            self.assertIn('REAL SKILL CONTENT',call.call_args_list[0].args[0])
            self.assertNotIn('1800至2600',call.call_args_list[0].args[0])
