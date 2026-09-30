import unittest
from contextlib import nullcontext
from unittest.mock import patch

from server import workbench
from server.providers import ProviderRequestError
from server.skills.adapter_support import with_provider
from vendor.skills.wechat_writer.adapter import create_tools


class AdapterProviderRetryTests(unittest.TestCase):
    def test_transient_error_retries_only_failing_tool(self):
        calls = 0

        def invoke():
            nonlocal calls
            calls += 1
            if calls < 3:
                try:
                    raise ProviderRequestError("connection reset", transient=True)
                except ProviderRequestError as exc:
                    raise workbench.ProviderError("text API failed") from exc
            return "ok"

        with patch("server.skills.adapter_support.time.sleep"), patch(
            "server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()
        ):
            self.assertEqual(with_provider(invoke), "ok")
        self.assertEqual(calls, 3)

    def test_nontransient_error_is_not_retried(self):
        calls = 0

        def invoke():
            nonlocal calls
            calls += 1
            raise workbench.ProviderError("invalid response")

        with patch("server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()), self.assertRaises(workbench.ProviderError):
            with_provider(invoke)
        self.assertEqual(calls, 1)

    def test_typeset_session_contains_topic(self):
        def fake_typeset(session):
            self.assertEqual(session["topic"], "测试标题")
            return "<p>正文</p>"

        with patch("server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()), patch(
            "vendor.skills.wechat_writer.adapter.workbench._typeset", side_effect=fake_typeset
        ):
            result = create_tools()["typeset_article"](
                {"title": "测试标题", "article": "正文"}, None)
        self.assertEqual(result.data["html"], "<p>正文</p>")


if __name__ == "__main__":
    unittest.main()
