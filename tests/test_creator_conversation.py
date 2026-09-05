import unittest
from unittest.mock import patch

from server import creator_conversation as c


class CreatorConversationTests(unittest.TestCase):
    def test_diagnosis_uses_actual_adapter_not_model_facts(self):
        responses = [{'type': 'tool', 'name': 'diagnose_account', 'arguments': {'account_name': 'test'}},
                     {'type': 'answer', 'reply': 'done'}]
        with patch.object(c.workbench, '_json_text', side_effect=responses), \
             patch.object(c.diagnosis_service, 'run', return_value={'report': {'scores': {}}}) as run, \
             patch.object(c.accounts, 'save_workbench_session'):
            result = c.chat('diagnose', 'diagnose test', 'user')
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], 'test')
        self.assertEqual(result['artifacts']['report'], {'scores': {}})

    def test_morning_layout_preserves_text_and_images(self):
        source = {'id': 'session123', 'conversation_skill': 'morning', 'conversation': [],
                  'parameters': {'mode': 'article'},
                  'artifacts': {'draft': {'copies': ['original'], 'images': [{'index': 1, 'url': '/saved'}]}}}
        responses = [{'type': 'tool', 'name': 'change_layout', 'arguments': {'columns': 2}},
                     {'type': 'answer', 'reply': 'done'}]
        with patch.object(c.accounts, 'load_workbench_session', return_value=source), \
             patch.object(c.accounts, 'save_workbench_session'), \
             patch.object(c.workbench, '_json_text', side_effect=responses), \
             patch.object(c.creator_tools, 'morning_draft') as generate:
            result = c.chat('morning', 'two columns only', 'user', 'session123')
        generate.assert_not_called()
        self.assertEqual(result['artifacts']['draft']['copies'], ['original'])
        self.assertEqual(result['artifacts']['draft']['images'], [{'index': 1, 'url': '/saved'}])
        self.assertEqual(result['artifacts']['draft']['columns'], 2)

    def test_completed_images_are_not_generated_or_charged_again(self):
        source = {'id':'session123', 'conversation_skill':'morning', 'conversation':[],
                  'artifacts': {'draft': {'cards':[{'index':1}], 'images':[{'index':1, 'url':'/saved'}]}}}
        responses = [{'type':'tool','name':'generate_images','arguments':{}}, {'type':'answer','reply':'done'}]
        with patch.object(c.accounts, 'load_workbench_session', return_value=source), \
             patch.object(c.accounts, 'save_workbench_session'), \
             patch.object(c.accounts, 'reserve_points') as charge, \
             patch.object(c.workbench, '_json_text', side_effect=responses), \
             patch.object(c.creator_tools, 'generate_card_image') as generate:
            result = c.chat('morning', 'continue images', 'user', 'session123')
        charge.assert_not_called()
        generate.assert_not_called()
        self.assertEqual(len(result['artifacts']['draft']['images']), 1)

    def test_review_does_not_rewrite_article(self):
        responses = [
            {'type': 'tool', 'name': 'review_article', 'arguments': {'title': 'title', 'body': 'original'}},
            {'type': 'answer', 'reply': 'reviewed'},
        ]
        with patch.object(c.workbench, '_json_text', side_effect=responses), \
             patch.object(c.creator_tools, 'detect_article', return_value={'suggestions': []}) as detect, \
             patch.object(c.creator_tools, 'rewrite_article') as rewrite, \
             patch.object(c.accounts, 'save_workbench_session'):
            result = c.chat('hit-detector', 'check this', 'user')
        detect.assert_called_once()
        rewrite.assert_not_called()
        self.assertEqual(result['parameters']['body'], 'original')
        self.assertIn('report', result['artifacts'])

    def test_draft_tool_receives_no_image_request_and_saves(self):
        responses = [
            {'type': 'tool', 'name': 'generate_draft',
             'arguments': {'topic': 'morning', 'image_count': 0}},
            {'type': 'answer', 'reply': 'done'},
        ]
        with patch.object(c.workbench, '_json_text', side_effect=responses), \
             patch.object(c.creator_tools, 'xiaohongshu_package', return_value={'body': 'text', 'cards': []}) as generate, \
             patch.object(c.accounts, 'save_workbench_session') as save:
            result = c.chat('xiaohongshu', 'text only', 'user')
        self.assertEqual(generate.call_args.kwargs['image_count'], 0)
        self.assertEqual(result['artifacts']['draft']['cards'], [])
        self.assertEqual(save.call_args.args[0], 'user')

    def test_missing_owned_session_is_not_recreated(self):
        with patch.object(c.accounts, 'load_workbench_session', return_value=None) as load:
            with self.assertRaises(KeyError):
                c.chat('xiaohongshu', 'go', 'other-user', 'existing')
        load.assert_called_once_with('existing', 'other-user')
