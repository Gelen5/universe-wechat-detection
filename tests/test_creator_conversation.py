import unittest
from contextlib import nullcontext
from unittest.mock import patch

from server import creator_conversation as c


class CreatorConversationTests(unittest.TestCase):
    def setUp(self):
        provider = patch.object(c.workbench, 'provider_overrides', side_effect=nullcontext)
        provider.start()
        self.addCleanup(provider.stop)

    def test_tie_tu_does_not_generate_in_the_same_turn_as_plan(self):
        def execute(session, message, instructions, generate, tools, **kwargs):
            tools['generate_draft']['execute'](session, {'topic': '主题', 'image_count': 2})
            tools['generate_images']['execute'](session, {'indices': [1]})
        draft = {'session_id':'plan1', 'cards':[{'index':1}, {'index':2}], 'images':[]}
        with patch.object(c.accounts, 'save_workbench_session'), \
             patch.object(c.accounts, 'reserve_points') as charge, \
             patch.object(c.creator_tools, 'tie_tu_plan', return_value=draft), \
             patch.object(c, 'run_turn', side_effect=execute):
            with self.assertRaisesRegex(ValueError, '查看卡片计划'):
                c.chat('tie-tu', '帮我生成贴图', 'user')
        charge.assert_not_called()

    def test_tie_tu_first_confirmation_generates_only_pilot(self):
        source = {'id':'session123', 'conversation_skill':'tie-tu', 'conversation':[],
                  'artifacts': {'draft': {'session_id':'plan1', 'cards':[{'index':1}, {'index':2}], 'images':[]}}}
        def execute(session, message, instructions, generate, tools, **kwargs):
            tools['generate_images']['execute'](session, {'indices': [1, 2]})
            return session
        with patch.object(c.accounts, 'load_workbench_session', return_value=source), \
             patch.object(c.accounts, 'save_workbench_session'), \
             patch.object(c.accounts, 'pricing_rule', return_value={'points': 1}), \
             patch.object(c.accounts, 'reserve_points', return_value='usage'), \
             patch.object(c.accounts, 'settle_usage'), \
             patch.object(c.creator_tools, 'generate_card_image', return_value={'index':1, 'url':'/test'}) as image, \
             patch.object(c, 'run_turn', side_effect=execute):
            result = c.chat('tie-tu', '确认当前卡片计划，只生成第 1 张试图', 'user', 'session123')
        self.assertEqual(image.call_count, 1)
        self.assertEqual(len(result['artifacts']['draft']['images']), 1)
        state = result['artifacts']['draft']
        self.assertEqual(state['approval_state']['stages']['card_plan'], 'approved')
        self.assertNotEqual(state['approval_state']['stages'].get('pilot_image'), 'approved')
        self.assertEqual(state['generation_state']['pilot_status'], 'generated')

    def test_tie_tu_pilot_confirmation_records_batch_completion(self):
        source = {'id':'session123', 'conversation_skill':'tie-tu', 'conversation':[],
                  'artifacts': {'draft': {'session_id':'plan1', 'cards':[{'index':1}, {'index':2}], 'images':[{'index':1, 'url':'/pilot'}]}}}
        def execute(session, message, instructions, generate, tools, **kwargs):
            tools['generate_images']['execute'](session, {'indices': [2]})
            return session
        with patch.object(c.accounts, 'load_workbench_session', return_value=source), \
             patch.object(c.accounts, 'save_workbench_session'), \
             patch.object(c.accounts, 'pricing_rule', return_value={'points': 1}), \
             patch.object(c.accounts, 'reserve_points', return_value='usage'), \
             patch.object(c.accounts, 'settle_usage'), \
             patch.object(c.creator_tools, 'generate_card_image', return_value={'index':2, 'url':'/second'}), \
             patch.object(c, 'run_turn', side_effect=execute):
            result = c.chat('tie-tu', '确认试图，生成剩余未生成的图片', 'user', 'session123')
        draft = result['artifacts']['draft']
        self.assertEqual(draft['approval_state']['stages']['pilot_image'], 'approved')
        self.assertEqual(draft['generation_state']['batch_status'], 'completed')

    def test_tie_tu_failed_pilot_is_refunded_and_not_recorded_as_generated(self):
        source = {'id':'session123', 'conversation_skill':'tie-tu', 'conversation':[],
                  'artifacts': {'draft': {'session_id':'plan1', 'cards':[{'index':1}], 'images':[]}}}
        def execute(session, message, instructions, generate, tools, **kwargs):
            tools['generate_images']['execute'](session, {'indices': [1]})
        with patch.object(c.accounts, 'load_workbench_session', return_value=source), \
             patch.object(c.accounts, 'save_workbench_session') as save, \
             patch.object(c.accounts, 'pricing_rule', return_value={'points': 1}), \
             patch.object(c.accounts, 'reserve_points', return_value='usage'), \
             patch.object(c.accounts, 'settle_usage') as settle, \
             patch.object(c.accounts, 'refund_usage') as refund, \
             patch.object(c.creator_tools, 'generate_card_image', side_effect=RuntimeError('image error')), \
             patch.object(c, 'run_turn', side_effect=execute):
            with self.assertRaisesRegex(RuntimeError, 'image error'):
                c.chat('tie-tu', '确认当前卡片计划，生成第 1 张试图', 'user', 'session123')
        refund.assert_called_once()
        settle.assert_not_called()
        save.assert_not_called()
        self.assertEqual(source['artifacts']['draft']['images'], [])
        self.assertNotEqual(source['artifacts']['draft'].get('generation_state', {}).get('pilot_status'), 'generated')

    def test_tie_tu_remaining_images_require_pilot_confirmation(self):
        source = {'id':'session123', 'conversation_skill':'tie-tu', 'conversation':[],
                  'artifacts': {'draft': {'session_id':'plan1', 'cards':[{'index':1}, {'index':2}], 'images':[{'index':1}]}}}
        def execute(session, message, instructions, generate, tools, **kwargs):
            tools['generate_images']['execute'](session, {'indices': [2]})
            return session
        with patch.object(c.accounts, 'load_workbench_session', return_value=source), \
             patch.object(c.creator_tools, 'generate_card_image') as image, \
             patch.object(c, 'run_turn', side_effect=execute):
            with self.assertRaisesRegex(ValueError, '确认首张试图'):
                c.chat('tie-tu', '继续生成', 'user', 'session123')
        image.assert_not_called()
    def test_morning_empty_optional_fields_use_defaults(self):
        response = {'type': 'tool', 'name': 'generate_draft', 'arguments': {'topic': '', 'size': '', 'image_count': 0}, 'finish': True}
        with patch.object(c.workbench, '_json_text', return_value=response), patch.object(c.creator_tools, 'morning_draft', return_value={'copies': ['text'], 'cards': []}) as draft, patch.object(c.accounts, 'save_workbench_session'):
            c.chat('morning', 'generate greetings', 'user')
        self.assertEqual(draft.call_args.kwargs['size'], '768x1024')
        self.assertTrue(draft.call_args.kwargs['topic'])

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
