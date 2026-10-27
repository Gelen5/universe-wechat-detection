from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import workbench as w, skill_runtime
from server.providers import call_context, OpenAICompatibleProvider
from tests.test_providers import FakeSession, FakeResponse

class ReviewDeliveryTests(unittest.TestCase):
    def run_review(self, *, missing=False, unchanged=False, failed_audit=False):
        original = '这段文字值得注意的是，表达重复。'
        revised = original if unchanged else '这段文字表达重复。'
        diagnosis = {'issues': [{'quote': '值得注意的是，', 'reason': '模板过渡', 'fix': '删除过渡'}],
                     'reason': '定位到模板表达', 'fidelity_ok': True, 'readability_ok': True}
        audit = {'status': 'success', 'complete_sentence_ratio': 1, 'missing_protected_spans': {}}
        post = dict(audit, missing_protected_spans={'quoted_text': ['真实原话']} if missing else {})
        if failed_audit:
            post['status'] = 'unavailable'
        progress = []
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(w, 'OUTPUT_DIR', Path(directory)), \
             patch.object(w, '_review_skill_context', return_value=('rules', [])), \
             patch.object(skill_runtime, 'script', return_value={}), \
             patch.object(skill_runtime, 'length_issue', return_value=None), \
             patch.object(w, '_json_text', return_value=diagnosis), \
             patch.object(w, '_anti_ai_audit', side_effect=[audit, post]), \
             patch.object(w, '_validated_local_edits', return_value=({'edits': [] if unchanged else [{'after': ''}], 'retained_issue_indexes': [0] if unchanged else []}, revised)) as edit, \
             patch.dict('os.environ', {'WECHAT_REVIEW_ROUNDS': '1'}):
            result, report = w._review(original, {'id': 'regression', 'brief': '审稿'}, lambda step, detail: progress.append(detail['label']))
        self.assertEqual(edit.call_count, 1)
        self.assertGreaterEqual(len(progress), 3)
        return result, report

    def test_single_round_really_edits_before_delivery(self):
        result, report = self.run_review()
        self.assertEqual('这段文字表达重复。', result)
        self.assertTrue(report['changed'])
        self.assertEqual('passed', report['gate'])
        self.assertIn('post_edit_audit', report['rounds'][0])

    def test_retained_text_is_explicitly_reported(self):
        _, report = self.run_review(unchanged=True)
        self.assertFalse(report['changed'])
        self.assertIn('未修改', report['summary'])
        self.assertTrue(report['pending_review_notes'])

    def test_partially_applied_diagnosis_is_reported_as_pending(self):
        article = '第一句空泛。第二句重复。'
        diagnosis = {'issues': [{'quote': '第一句空泛。', 'reason': '空泛', 'fix': '改具体'},
                                {'quote': '第二句重复。', 'reason': '重复', 'fix': '精简'}],
                     'reason': '两处阅读问题', 'fidelity_ok': True, 'readability_ok': True}
        audit = {'status': 'success', 'complete_sentence_ratio': 1, 'missing_protected_spans': {}}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(w, 'OUTPUT_DIR', Path(directory)), \
             patch.object(w, '_review_skill_context', return_value=('rules', [])), \
             patch.object(skill_runtime, 'script', return_value={}), \
             patch.object(skill_runtime, 'length_issue', return_value=None), \
             patch.object(w, '_json_text', return_value=diagnosis), \
             patch.object(w, '_anti_ai_audit', return_value=audit), \
             patch.object(w, '_validated_local_edits', return_value=({'edits': [{'issue_index': 0, 'after': '第一句具体。'}, {'issue_index': 1, 'after': '第二句重复。'}]}, '第一句具体。第二句重复。')), \
             patch.dict('os.environ', {'WECHAT_REVIEW_ROUNDS': '1'}):
            _, report = w._review(article, {'id': 'pending', 'brief': '审稿'})
        self.assertEqual(report['pending_review_notes'][0]['quote'], '第二句重复。')
        self.assertIn('部分问题仍待处理', report['summary'])

    def test_fact_loss_after_edit_cannot_be_marked_passed(self):
        with self.assertRaises(w.ProviderError):
            self.run_review(missing=True)

    def test_failed_post_edit_audit_delivers_original_instead_of_unverified_candidate(self):
        result, report = self.run_review(failed_audit=True)
        self.assertEqual('这段文字值得注意的是，表达重复。', result)
        self.assertEqual('needs_review', report['gate'])
        self.assertFalse(report['changed'])

    def test_review_budget_applies_without_agent_wrapper(self):
        remaining = []
        def review(*args):
            remaining.append(call_context.remaining_seconds())
            return args[0], {}
        with patch.object(w, '_review_impl', side_effect=review) as impl:
            w._review('正文。', {})
        left = remaining[0]
        self.assertLessEqual(left, 240)
        self.assertGreater(left, 0)
        self.assertEqual(impl.call_count, 1)

    def test_review_retries_only_the_failed_request_once(self):
        from server.providers import ProviderRequestError, ProviderResponse
        token = w.REVIEW_REASONING.set('medium')
        try:
            with patch('server.providers.OpenAICompatibleProvider'), \
                 patch('server.providers.ModelService') as service, \
                 patch.object(w.time, 'sleep'), \
                 patch.dict('os.environ', {'WECHAT_TEXT_API_KEY': 'test'}), \
                 call_context.bind(deadline=w.time.monotonic() + 240):
                service.return_value.create_response.side_effect = [
                    ProviderRequestError('upstream unavailable', transient=True), ProviderResponse(text='OK')]
                self.assertEqual('OK', w._text('diagnose'))
                self.assertEqual(2, service.return_value.create_response.call_count)
                self.assertLessEqual(service.return_value.create_response.call_args.kwargs['timeout'], 120)
        finally:
            w.REVIEW_REASONING.reset(token)

    def test_missing_question_mark_is_restored_without_changing_sentence_kind(self):
        payload = {'edits': [{'issue_index': 0, 'after': '你准备好了'}]}
        with patch.object(w, '_json_text', return_value=payload):
            _, revised = w._validated_local_edits('你真的准备好了吗？下一句。', 'edit', True,
                                                   anchors=['你真的准备好了吗？'])
        self.assertEqual('你准备好了？下一句。', revised)

    def test_wrapped_relay_502_has_actionable_failure(self):
        from server.agent.failures import describe
        from server.providers import ProviderRequestError
        try:
            raise w.ProviderError('text API 请求失败：provider HTTP 502') from ProviderRequestError(
                'provider HTTP 502', code='http_error', transient=True)
        except w.ProviderError as exc:
            detail = describe(exc)
        self.assertEqual('provider', detail['error_kind'])
        self.assertIn('中转服务暂时不可用', detail['reason'])
        self.assertTrue(detail['retryable'])

    def test_empty_replacement_can_remove_only_a_formulaic_transition(self):
        with patch.object(w, '_json_text', return_value={'edits': [{'issue_index': 0, 'after': ''}]}):
            _, revised = w._validated_local_edits('值得注意的是，正文。', 'edit', anchors=['值得注意的是，'], require_edits=True)
            self.assertEqual('正文。', revised)
            with self.assertRaises(w.ProviderError):
                w._validated_local_edits('真实原话。', 'edit', anchors=['真实原话。'], require_edits=True)

    def test_explicit_redundancy_deletion_preserves_rest_of_article(self):
        with patch.object(w, '_json_text', return_value={'edits': [{'issue_index': 0, 'after': ''}]}):
            _, revised = w._validated_local_edits('具体步骤。重复总结。', 'edit', anchors=['重复总结。'], require_edits=True, deletable_indexes={0})
            self.assertEqual('具体步骤。', revised)
            with self.assertRaises(w.ProviderError):
                w._validated_local_edits('“真实引语”。具体步骤。', 'edit', anchors=['“真实引语”。'], require_edits=True, deletable_indexes={0})
            with self.assertRaises(w.ProviderError):
                w._validated_local_edits('全部正文。', 'edit', anchors=['全部正文。'], require_edits=True, deletable_indexes={0})

    def test_sol_uses_responses_and_medium(self):
        session = FakeSession([FakeResponse({'status': 'completed', 'output': []})])
        provider = OpenAICompatibleProvider(api_key='test', base_url='https://relay.test/v1',
            text_model='gpt-6.1-sol', reasoning_effort='medium', session=session)
        provider.create_response([{'role': 'user', 'content': 'test'}])
        request = session.requests[0]
        self.assertTrue(provider.responses_api)
        self.assertEqual('medium', request[2]['json']['reasoning']['effort'])

if __name__ == '__main__': unittest.main()
