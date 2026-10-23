import unittest
from unittest.mock import Mock
from server.qihaoshou_rewrite import rewrite_html

OK = dict(facts_preserved=True, stance_preserved=True, conditions_preserved=True, no_invention=True, readable=True, issues=[])

class RewriteTests(unittest.TestCase):
    def test_substantial_edit_preserves_markup_links_heading(self):
        source = '<h1>标题</h1><p style="color:red">在当今时代，写作至关重要。<strong>2026年每天10分钟</strong>，不把工具当作结果。<a href="https://example.com">来源</a></p>'
        model = Mock(side_effect=[{'edits':[{'id':'0','text':'写作可以从每天记录开始。'},{'id':'1','text':'2026年每天10分钟'},{'id':'2','text':'，不把工具当作结果。'}]}, OK])
        html, changes = rewrite_html(source, '轻松口语', model)
        self.assertIn('<strong>2026年每天10分钟</strong>', html)
        self.assertIn('<h1>标题</h1>', html)
        self.assertIn('href="https://example.com"', html)
        self.assertIn('style="color:red"', html)
        self.assertEqual(len(changes), 1)
        self.assertEqual(model.call_count, 2)

    def test_rejects_changed_numbers_duplicate_ids_and_noop(self):
        for edits in [[{'id':'0','text':'2027年每天20分钟。'}], [{'id':'0','text':'2026年每天10分钟。'}], [{'id':'7','text':'2026年每天10分钟，开始记录。'}]]:
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                rewrite_html('<p>2026年每天10分钟。</p>', '口语', Mock(return_value={'edits':edits}))

    def test_semantic_review_vetoes_negation_drift(self):
        model = Mock(side_effect=[{'edits':[{'id':'0','text':'工具就是结果。'}]}, {**OK, 'stance_preserved':False, 'issues':['否定被删除']}])
        with self.assertRaises(ValueError):
            rewrite_html('<p>不把工具当作结果。</p>', '口语', model)

    def test_direct_quote_cannot_change(self):
        model = Mock(return_value={'edits':[{'id':'0','text':'他说：“必然成功”。'}]})
        with self.assertRaises(ValueError):
            rewrite_html('<p>他说：“未必成功”。</p>', '口语', model)
        self.assertEqual(model.call_count, 1)
