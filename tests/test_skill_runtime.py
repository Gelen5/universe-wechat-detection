import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import workbench as w, skill_runtime as r


class SkillRuntimeTests(unittest.TestCase):
    def test_sentence_audit_excludes_markdown_headings_but_keeps_prose(self):
        article = "# 主标题没有句号\n\n**第一部分也没有句号**\n\n正文残句没有标点"
        prose = w._markdown_prose_for_sentence_audit(article)
        self.assertNotIn("主标题", prose)
        self.assertNotIn("第一部分", prose)
        self.assertIn("正文残句没有标点", prose)

    def test_actual_skill_sentence_audit_does_not_count_markdown_headings(self):
        if not w.ANTI_AI_SKILL_DIR.exists():
            self.skipTest("Installed anti-AI Skill not present")
        article = "# 主标题没有句号\n\n**第一部分没有句号**\n\n正文是完整句子。\n\n另一段也是完整句子。"
        with tempfile.TemporaryDirectory() as directory, patch.object(w, "OUTPUT_DIR", Path(directory)):
            audit = w._anti_ai_audit(article, article, {"id": "heading-audit"})
        self.assertEqual(audit["status"], "success")
        self.assertLess(audit["raw_complete_sentence_ratio"], .9)
        self.assertEqual(audit["complete_sentence_ratio"], 1)
        self.assertTrue(audit["markdown_structure_excluded"])

    def test_modified_article_invalidates_gate(self):
        session = {'article': '原稿', 'review': {'gate': 'passed', 'article_sha256': r.digest('原稿')}}
        self.assertTrue(w._review_is_current(session))
        session['article'] = '修改稿'
        self.assertFalse(w._review_is_current(session))
        with patch.object(w, '_get_session', return_value=session):
            with self.assertRaises(w.ProviderError):
                w.publish('test', user_id='test')

    def test_preview_does_not_require_rewriting(self):
        session = {'id': 'test', 'article': '修改稿', 'review': None, 'score': {},
                   'typeset_html': '<p>修改稿</p>', 'preview_document': '<p>修改稿</p>'}
        with tempfile.TemporaryDirectory() as directory, patch.object(w, 'OUTPUT_DIR', Path(directory)), \
             patch.object(w, '_save_session'), patch.object(w, '_score', return_value={}), \
             patch.object(w, '_review') as review:
            result = w._preview_session(session)
            self.assertTrue((Path(directory) / 'test/preview.html').exists())
        review.assert_not_called()
        self.assertEqual(result['article'], '修改稿')
        self.assertIsNone(result['review'])
        self.assertRegex(result['preview_url'], r'^/api/workbench/preview/test\?v=[0-9a-f]{16}$')
        self.assertRegex(result['html_download_url'], r'^/api/workbench/html/test\?v=[0-9a-f]{16}$')

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

    def test_review_treats_keep_only_findings_as_retained(self):
        diagnosis = {
            'issues': [{'quote': '具体列举。', 'reason': '语境自然', 'fix': '保留'}],
            'retained_signals': [], 'reason': '逐句核对',
            'fidelity_ok': True, 'readability_ok': True,
        }
        audit = {'status': 'success', 'complete_sentence_ratio': 1, 'missing_protected_spans': {}}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(w, 'OUTPUT_DIR', Path(directory)), \
             patch.object(r, 'context', return_value=('Skill', [])), \
             patch.object(r, 'script', return_value={}), \
             patch.object(w, '_json_text', return_value=diagnosis), \
             patch.object(w, '_anti_ai_audit', return_value=audit), \
             patch.object(w, '_text') as edit:
            article, review = w._review('具体列举。', {'id': 'keep-finding'})
        self.assertEqual(review['gate'], 'passed')
        self.assertEqual(review['rounds'][0]['diagnosis']['issues'], [])
        self.assertEqual(len(review['rounds'][0]['diagnosis']['retained_signals']), 1)
        edit.assert_not_called()

    def test_review_treats_explicit_no_change_reason_as_retained(self):
        issue = {'quote': '原句。', 'reason': '当前版本此处无误，无需修改'}
        self.assertTrue(w._review_issue_is_retained(issue, {'保留', '无需修改'}))

    def test_local_edits_retry_ambiguous_and_preserve_quoted_words(self):
        candidate = '他说“原话”。他说“原话”。最后一句。'
        invalid = {'edits': [{'before': '他说“原话”。', 'after': '他说得很直接。'}]}
        valid = {'edits': [{'before': '最后一句。', 'after': '最后一句更完整。'}]}
        with patch.object(w, '_json_text', side_effect=[invalid, valid]) as generate:
            payload, revised = w._validated_local_edits(candidate, 'prompt', require_edits=True)
        self.assertEqual(payload, valid)
        self.assertIn('“原话”', revised)
        self.assertIn('最后一句更完整。', revised)
        self.assertEqual(generate.call_count, 2)

    def test_local_edits_use_verified_issue_anchor_not_model_recopy(self):
        payload = {'edits': [{'issue_index': 0, 'before': '模型抄错的片段', 'after': '替换后。'}]}
        with patch.object(w, '_json_text', return_value=payload):
            _, revised = w._validated_local_edits('准确的原始片段。', 'prompt', True, ['准确的原始片段。'])
        self.assertEqual(revised, '替换后。')

    def test_unavailable_audit_blocks(self):
        with tempfile.TemporaryDirectory() as d, patch.object(w,'OUTPUT_DIR',Path(d)), patch.object(r,'context',return_value=('Skill',[])), patch.object(r,'script',return_value={}), patch.object(w,'_json_text',return_value={'issues':[],'reason':'检查','fidelity_ok':True,'readability_ok':True}), patch.object(w,'_text',return_value='原稿。'), patch.object(w,'_anti_ai_audit',return_value={'status':'unavailable'}):
            with self.assertRaises(w.ProviderError): w._review('原稿。',{'id':'test'})

    def test_draft_passes_requirements_and_retries_length(self):
        with patch.object(r,'context',return_value=('REAL SKILL CONTENT',[])), patch.object(w,'_text',side_effect=['字'*1100,'字'*900]) as call:
            article=w._draft('标题',{},'作者','800—1000字，不能编造')
            self.assertEqual(len(article),900)
            self.assertIn('REAL SKILL CONTENT',call.call_args_list[0].args[0])
            self.assertNotIn('1800至2600',call.call_args_list[0].args[0])
