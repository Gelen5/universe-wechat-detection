import unittest
from unittest.mock import Mock

from server.conversation_agent import decide, deterministic_workbench_intent, run_turn


class ToolConversationTests(unittest.TestCase):
    def test_tool_result_and_history_are_used_before_answer(self):
        source = {'conversation': [{'role': 'user', 'content': 'no images'}]}
        generate = Mock(side_effect=[
            {'type': 'tool', 'name': 'layout', 'arguments': {}},
            {'type': 'answer', 'reply': 'ready'},
        ])
        def layout(state, args):
            state['html'] = '<p>draft</p>'
            return {'ready': True}
        result = run_turn(source, 'typeset', 'real rules', generate,
                          {'layout': {'description': 'format draft', 'execute': layout}})
        self.assertEqual(result['html'], '<p>draft</p>')
        self.assertNotIn('html', source)
        self.assertIn('no images', generate.call_args.args[0])
        self.assertIn('real rules', generate.call_args.args[0])
        self.assertIn('"ready": true', generate.call_args.args[0])

    def test_unknown_tool_never_executes(self):
        execute = Mock()
        with self.assertRaises(ValueError):
            run_turn({}, 'go', '', lambda _: {'type': 'tool', 'name': 'shell', 'arguments': {}},
                     {'layout': {'description': '', 'execute': execute}})
        execute.assert_not_called()

    def test_failed_tool_does_not_mutate_original(self):
        source = {'images': ['saved']}
        def fail(state, args):
            state['images'].clear()
            raise RuntimeError('failed')
        with self.assertRaises(RuntimeError):
            run_turn(source, 'go', '', lambda _: {'type': 'tool', 'name': 'layout', 'arguments': {}},
                     {'layout': {'description': '', 'execute': fail}})
        self.assertEqual(source['images'], ['saved'])


class ConversationDecisionTests(unittest.TestCase):
    def test_layout_intent_is_deterministic(self):
        result = deterministic_workbench_intent({'current_step': 5}, '不要图片，直接排版')
        self.assertEqual(result, {'action': 'typeset', 'image_policy': 'none', 'reply': ''})

    def test_theme_change_is_deterministic(self):
        result = deterministic_workbench_intent({'current_step': 7}, '换个排版主题')
        self.assertEqual(result['action'], 'change_theme')

    def test_rerender_command_is_deterministic_and_keeps_images(self):
        result = deterministic_workbench_intent({'current_step': 7}, '重新排版，保留之前生成的图片')
        self.assertEqual(result, {'action': 'typeset', 'image_policy': 'keep', 'reply': ''})

    def test_context_and_explicit_no_images_reach_decision(self):
        generate = Mock(return_value={'action': 'typeset', 'image_policy': 'none'})
        result = decide({'article': 'approved draft', 'current_step': 5,
                         'conversation': [{'role': 'user', 'content': 'earlier request'}]},
                        '不要图片直接排版', 'skill rules', generate)
        self.assertEqual(result['action'], 'typeset')
        self.assertEqual(result['image_policy'], 'none')
        prompt = generate.call_args.args[0]
        self.assertIn('earlier request', prompt)
        self.assertIn('approved draft', prompt)
        self.assertIn('skill rules', prompt)

    def test_unknown_or_publish_action_cannot_execute(self):
        for action in ('publish', 'shell', 'unknown'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                decide({}, 'request', '', lambda _: {'action': action})

    def test_empty_answer_is_rejected(self):
        with self.assertRaises(ValueError):
            decide({}, 'question', '', lambda _: {'action': 'respond', 'reply': ''})
