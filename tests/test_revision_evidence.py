import unittest
from unittest.mock import patch
from server import workbench as w
from server.revision_evidence import (orphaned_list_error, revision_evidence, introduced_duplicate_error,
                                      repeated_editing_cues)


class RevisionEvidenceTests(unittest.TestCase):
    def test_collapsed_list_with_untouched_intro_is_rejected_and_retried(self):
        intro = '可以提前为自己准备三套简单的选项：'
        entries = '状态好时，做一件事；\n\n状态一般时，缩短任务；\n\n状态很差时，优先休息。'
        article = intro + '\n\n' + entries + '\n\n最后一句。'
        payload = {'edits': [{'issue_index': 0, 'after': '先判断状态，再选择安排。'}]}
        with patch.object(w, '_json_text', return_value=payload) as model:
            with self.assertRaises(w.ProviderError):
                w._validated_local_edits(article, 'edit', True, anchors=[entries])
        self.assertEqual(2, model.call_count)
        self.assertIn('列举引导语', model.call_args.args[0])

    def test_complete_list_or_repaired_intro_can_pass(self):
        before = '有三种选项：\n\n学习；\n\n散步；\n\n休息。'
        self.assertIsNone(orphaned_list_error(before, before))
        self.assertIsNone(orphaned_list_error(before, '可以按状态选择。\n\n学习、散步或休息。'))
        self.assertIsNone(orphaned_list_error(before, '有三种选项：\n\n学习；散步；休息。'))

    def test_counts_do_not_treat_punctuation_as_substantive(self):
        evidence = revision_evidence('正文，原话。', '正文 原话。')
        self.assertFalse(evidence['text_changed'])
        self.assertNotEqual(evidence['before_sha256'], evidence['after_sha256'])
        self.assertEqual(1, evidence['removed_chars'])
        self.assertEqual(1, evidence['added_chars'])

    def test_ordinary_colon_and_single_paragraph_are_not_lists(self):
        self.assertIsNone(orphaned_list_error('结论：\n\n建议先休息。', '结论：\n\n可以休息。'))

    def test_edit_cannot_duplicate_the_next_paragraph(self):
        next_paragraph = '回家后先确认自己的状态，再选择相应的安排，不必每天打卡。'
        article = '这段需要精简。\n\n' + next_paragraph
        payload = {'edits': [{'issue_index': 0, 'after': next_paragraph}]}
        with patch.object(w, '_json_text', return_value=payload):
            with self.assertRaises(w.ProviderError):
                w._validated_local_edits(article, 'edit', True, anchors=['这段需要精简。'])
        repeated = next_paragraph + '\n\n' + next_paragraph
        self.assertIsNone(introduced_duplicate_error(repeated, repeated))

    def test_repeated_example_introductions_are_only_review_clues(self):
        article = ('可以借用这样的示范表达：\n\n“先听清楚。”\n\n'
                   '下面是示范表达：\n\n“这件事怎么做？”\n\n'
                   '示范表达可以是：\n\n“我需要一点时间。”')
        cues = repeated_editing_cues(article)
        self.assertEqual(cues[0]['occurrences'], 3)
        self.assertNotIn('先听清楚', str(cues))
        self.assertEqual([], repeated_editing_cues('示范表达：\n\n“这是一处示范。”'))
        self.assertEqual(repeated_editing_cues('示范表达：\n\n示范表达：\n\n示范表达：')[0]['occurrences'], 3)
