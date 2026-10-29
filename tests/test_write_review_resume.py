import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import support  # noqa: F401
from server import skill_host, workbench
from vendor.skills.wechat_writer import adapter


class WriteReviewResumeTests(unittest.TestCase):
    def test_review_uses_same_brief_and_provider_failure_keeps_draft(self):
        state = SimpleNamespace(draft='已生成的正文', selected_title='模型拟定的新标题',
                                quality_report={}, outline=[], writing_strategy={})
        calls = []

        def run(_conversation, _user, *, brief, upto, persona):
            calls.append((brief, upto))
            if upto == 'review':
                raise workbench.ProviderError('upstream returned no text')
            return state

        context = SimpleNamespace(conversation_id='c', user_id='u', run_id=None,
                                  input_artifacts=lambda: [{'type': 'outline', 'id': 'o'}],
                                  emit=lambda *_args: None)
        with patch.object(skill_host, 'enabled', return_value=True), \
             patch.object(skill_host, 'for_conversation', side_effect=run), \
             patch.object(skill_host, 'enforce_length', return_value=state), \
             patch.object(skill_host, 'save_state'), \
             patch.object(skill_host, 'score_article', return_value={}), \
             patch.object(skill_host, 'downgraded_claims', return_value=[]):
            result = adapter.create_tools()['write_article'](
                {'title': '用户选定的标题', 'requirements': '写完整正文'}, context)
        self.assertEqual(calls[0][0], calls[1][0])
        self.assertEqual(['draft', 'review'], [item[1] for item in calls])
        self.assertEqual('已生成的正文', result.data['article'])
        self.assertEqual('needs_review', result.data['review']['gate'])
        self.assertEqual('article', result.artifacts[0].type)

    def test_same_article_title_survives_stage_requirement_change(self):
        state = SimpleNamespace(draft='已生成的正文',
                                user_request='同一篇公众号文章的标题\n只生成大纲')
        self.assertFalse(skill_host.is_new_creation(
            state, '同一篇公众号文章的标题\n现在生成正文'))


if __name__ == '__main__':
    unittest.main()
