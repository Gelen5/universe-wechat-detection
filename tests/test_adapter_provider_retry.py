import unittest
from unittest.mock import patch

from server import workbench
from server.providers import ProviderRequestError
from server.skills.adapter_support import with_provider


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

        with patch("server.skills.adapter_support.time.sleep"):
            self.assertEqual(with_provider(invoke), "ok")
        self.assertEqual(calls, 3)

    def test_nontransient_error_is_not_retried(self):
        calls = 0

        def invoke():
            nonlocal calls
            calls += 1
            raise workbench.ProviderError("invalid response")

        with self.assertRaises(workbench.ProviderError):
            with_provider(invoke)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
