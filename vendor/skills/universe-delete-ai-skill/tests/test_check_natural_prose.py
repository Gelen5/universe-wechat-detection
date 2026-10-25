import unittest

from scripts.check_natural_prose import analyze


class NaturalProseStructureTests(unittest.TestCase):
    def test_flags_repeated_symmetric_judgments_and_closed_paragraphs(self) -> None:
        text = """李清照那么聪明，怎么还会嫁错人？

真正值得看的，是她后来发现自己想岔了以后干了什么。

聪明不等于任何时候都能看穿一个人，也不等于人在低谷里还能像局外人一样拿主意。

书读得多，不代表不会看错人，也不代表她能预先知道每段关系的结局。

留下有留下的代价，离开有离开的代价，哪条路都不免费。

所以我越来越觉得，历史人物也是人，不是一辈子不会出错的人设。"""

        result = analyze(text)

        self.assertEqual(result["formula_pattern_counts"]["对称判断句"], 2)
        self.assertEqual(result["formula_pattern_counts"]["对称代价句"], 1)
        self.assertGreaterEqual(result["paragraph_end_judgment_ratio"], 0.8)
        self.assertIn(
            "较多段落以抽象判断收束，检查是否每段都被解释得过于闭环",
            result["warnings"],
        )

    def test_does_not_force_plain_narrative_into_judgment_pattern(self) -> None:
        text = """上午下过一阵雨。她把箱子挪到门边，没有马上出门。

隔壁有人来借剪刀，她找了半天，只翻出一把生锈的。

中午雨停了。她把箱子打开，又把最上面的两件衣服拿回柜子。

车站离家不远，走过去要二十分钟。她最后叫了一辆车。

司机问去哪里，她报了地址，低头回了一条消息。

车开出巷口时，晒衣绳上的床单还在滴水。"""

        result = analyze(text)

        self.assertEqual(result["paragraph_end_judgment_ratio"], 0.0)
        self.assertNotIn("对称判断句", result["formula_pattern_counts"])
        self.assertNotIn("对称代价句", result["formula_pattern_counts"])

    def test_does_not_treat_inner_yinci_or_length_uniformity_as_ai_rule(self) -> None:
        text = "项目不会因此失败。团队不会因此停工。大家不会因此离开。"
        result = analyze(text, mode="minimal")

        self.assertNotIn("translation_leading_connector", result["template_marker_counts"])
        self.assertFalse(any("句长变化很小" in warning for warning in result["warnings"]))
        self.assertTrue(any("只作节奏观察" in item for item in result["observations"]))


if __name__ == "__main__":
    unittest.main()
