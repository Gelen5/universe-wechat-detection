import unittest

from scripts.check_ai_tone_signals import analyze


class ExplicitSignalTests(unittest.TestCase):
    def test_locates_supported_rule_families(self) -> None:
        text = """真正的问题不是工具，而是判断。

采集、存储、展示都由同一个模块完成。

答案很简单——专注。

核心是：先解决支付失败。

它像一位智慧的导师，替团队指出方向。

团队完成了对流程的优化。

说白了，这个项目预算不足。

这是一个能够让团队在不增加人手的情况下显著提升审核速度的工具。

当所有人都能生成内容时，内容本身不再稀缺。

对于早期团队来说，招人最难。

然而，这个方案不适用于所有场景。

这意味着产品已经找到了方向。

前一段已经说明了数据来源。

值得注意的是，样本仍然不足。"""

        result = analyze(text, mode="minimal")
        rules = set(result["signal_counts"])

        self.assertTrue(
            {
                "flip_rhetoric",
                "dense_enumeration",
                "revelation_dash",
                "prompt_colon",
                "idealized_role_metaphor",
                "nominalized_action",
                "banned_opener",
                "translation_long_premodifier",
                "translation_when_front",
                "translation_topic_shell",
                "translation_leading_connector",
                "translation_this_means",
                "paragraph_zero_subject_comment",
            }.issubset(rules)
        )

    def test_detects_adjacent_isomorphic_sentences(self) -> None:
        text = "项目上线以后，用户反馈明显变多。团队复盘以后，修复速度明显变快。"
        result = analyze(text, mode="minimal")
        self.assertIn("adjacent_isomorphic_sentences", result["signal_counts"])

    def test_detects_three_ordered_headings_and_empty_list_intro(self) -> None:
        text = """## 一、准备材料
正文。

## 二、核对事实
正文。

## 三、开始改写
正文。

常见问题：
- 主语不清
- 标点混乱
"""
        result = analyze(text, mode="minimal")
        self.assertEqual(result["signal_counts"]["ordered_headings"], 3)
        self.assertEqual(result["signal_counts"]["empty_list_intro"], 1)

    def test_preserves_normal_chinese_and_special_formats(self) -> None:
        text = """他说：“明天再谈。”

首先，我们核对原始记录。项目不会因此失败。

这个系统像一把旧雨伞，用着不漂亮，但能挡雨。

法律要求列明：姓名、日期、金额。

- 采集、存储、展示

## 一、准备
正文。

## 二、执行
正文。
"""
        result = analyze(text, mode="minimal")
        rules = set(result["signal_counts"])

        self.assertNotIn("prompt_colon", rules)
        self.assertNotIn("translation_leading_connector", rules)
        self.assertNotIn("idealized_role_metaphor", rules)
        self.assertNotIn("dense_enumeration", rules)
        self.assertNotIn("ordered_headings", rules)

    def test_structural_rules_follow_mode_permissions(self) -> None:
        text = """聪明不等于不会犯错，也不等于总能看清别人。

留下有留下的代价，离开有离开的代价。

所以这件事没有简单答案。

这说明判断需要时间。

更现实的是，人只能边走边看。

说到底，结局不会提前出现。"""

        minimal = analyze(text, mode="minimal")
        standard = analyze(text, mode="standard")
        deep = analyze(text, mode="deep")

        self.assertNotIn("symmetric_judgment", minimal["signal_counts"])
        self.assertIn("symmetric_judgment", standard["signal_counts"])
        self.assertIn("symmetric_cost", standard["signal_counts"])
        self.assertNotIn("paragraph_overclosure", standard["signal_counts"])
        self.assertIn("paragraph_overclosure", deep["signal_counts"])

    def test_heading_does_not_turn_first_prose_paragraph_into_zero_subject(self) -> None:
        result = analyze("# 标题\n\n值得注意的是，样本仍然不足。", mode="minimal")
        self.assertNotIn(
            "paragraph_zero_subject_comment", result["signal_counts"]
        )

    def test_detects_new_content_signals_and_hard_artifacts(self) -> None:
        text = """真正值得注意的是，这件事很复杂。\n\n关键是：\n\n这段话总结得很准确。\n\n可能也许大概会改变结果。\n\n欢迎留言，你会感谢我。\n\n[待填写来源] citeturn0search0 https://example.com/?utm_source=chatgpt.com"""
        result = analyze(text, mode="minimal")
        rules = set(result["signal_counts"])
        self.assertTrue(
            {
                "performed_insight",
                "infomercial_hook",
                "recap_flattery",
                "hedge_stack",
                "social_cta_closer",
                "ai_placeholder",
                "ai_citation_markup",
                "ai_utm_source",
            }.issubset(rules)
        )

    def test_does_not_flag_normal_negation_or_hedging(self) -> None:
        text = "我不是不想去，只是今天确实没有时间。\n\n这件事可能会有变化，但目前还没有确定消息。"
        result = analyze(text, mode="minimal")
        self.assertNotIn("stacked_negation", result["signal_counts"])
        self.assertNotIn("hedge_stack", result["signal_counts"])


if __name__ == "__main__":
    unittest.main()
