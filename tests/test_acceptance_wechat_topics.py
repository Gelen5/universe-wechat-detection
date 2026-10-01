import unittest

from scripts.acceptance_wechat_topics_http import assert_body_image_position


class BodyImageAcceptanceTests(unittest.TestCase):
    def test_accepts_image_between_article_paragraphs(self):
        assert_body_image_position(
            '<main id="article-content"><h1>标题</h1><p>第一段正文有足够的文字内容。</p>'
            '<img src="data:image/png;base64,AA"><p>图注：配图</p>'
            '<p>第二段正文也有足够的文字内容。</p></main>')

    def test_rejects_image_before_or_after_article(self):
        for html in (
            '<main id="article-content"><img src="data:image/png;base64,AA">'
            '<p>第一段正文有足够的文字内容。</p><p>第二段正文也有足够的文字内容。</p></main>',
            '<main id="article-content"><p>第一段正文有足够的文字内容。</p>'
            '<p>第二段正文也有足够的文字内容。</p><img src="data:image/png;base64,AA"></main>',
        ):
            with self.subTest(html=html), self.assertRaises(AssertionError):
                assert_body_image_position(html)


if __name__ == "__main__":
    unittest.main()
