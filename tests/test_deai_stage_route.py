import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from tests import support  # noqa: F401
from server import skill_host, workbench
from server.agent import tool_loop
from server.skills.tool_result import ToolResult
from vendor.skills.wechat_writer.adapter import create_tools


class DeaiStageRouteTests(unittest.TestCase):
    def test_explicit_deai_skips_model_tool_selection(self):
        model = unittest.mock.Mock()
        invoked = []
        tool = tool_loop.ExecutableTool(
            {'name': 'review_article', 'parameters': {'type': 'object',
             'properties': {'article': {'type': 'string'}}, 'required': ['article']}},
            lambda args, _context: invoked.append(args['article']) or ToolResult({'article': '新稿'}))
        with patch.object(tool_loop.conversation_repository, 'create_tool_call',
                          return_value=({'id': 't1', 'status': 'running'}, False)), \
             patch.object(tool_loop.conversation_repository, 'get_run',
                          return_value={'conversation_id': 'c'}), \
             patch.object(tool_loop.conversation_repository, 'finish_tool_call'), \
             patch.object(tool_loop, 'get_storage', return_value=object()), \
             patch.object(tool_loop, 'notify'):
            answer = tool_loop.run_tool_loop(
                model_service=model, messages=[], tools={'review_article': tool},
                run_id='r', user_id='u', skill_id='wechat_writer', max_tool_calls=1,
                timeout_seconds=30, required_tool='review_article',
                direct_tool_args={'article': '原稿。'})
        model.create_response.assert_not_called()
        self.assertEqual(['原稿。'], invoked)
        self.assertIn('已完成', answer)

    def test_deai_uses_structural_rewrite_and_syncs_state(self):
        context = SimpleNamespace(conversation_id='c', user_id='u', run_id='r',
                                  input_artifacts=lambda: [{'type': 'article', 'content': '原稿。',
                                                            'title': '原稿'}],
                                  emit=lambda *_args: None, is_cancelled=lambda: False)
        with patch.object(skill_host, 'enabled', return_value=True), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_run',
                   return_value={'stage': 'deai', 'trigger_message_id': 'm'}), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_message',
                   return_value={'content': '去 AI'}), \
             patch.object(workbench, 'provider_overrides', return_value=nullcontext()), \
             patch.object(workbench, '_deep_structure_review',
                          return_value=('重组后的正文。', {'gate': 'passed', 'changed': True})) as rewrite, \
             patch.object(skill_host, 'for_conversation') as workflow, \
             patch.object(skill_host, 'load_state', return_value=object()) as load, \
             patch.object(skill_host, 'apply_revision') as apply, \
             patch.object(skill_host, 'save_state') as save:
            result = create_tools()['review_article'](
                {'title': '原稿', 'requirements': '去 AI'}, context)
        rewrite.assert_called_once()
        workflow.assert_not_called()
        load.assert_called_once()
        apply.assert_called_once_with(load.return_value, '重组后的正文。')
        save.assert_called_once()
        self.assertEqual('重组后的正文。', result.artifacts[0].content)


if __name__ == '__main__':
    unittest.main()
