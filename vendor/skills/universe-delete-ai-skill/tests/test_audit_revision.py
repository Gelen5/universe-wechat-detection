import unittest

from scripts.audit_revision import audit


class AuditRevisionTests(unittest.TestCase):
    def test_reports_before_after_and_protected_spans(self) -> None:
        result = audit(
            "说白了，项目在2026年上线。",
            "项目在2026年上线。",
            "minimal",
        )
        self.assertEqual(result["mode"], "minimal")
        self.assertEqual(result["original"]["signal_total"], 1)
        self.assertEqual(result["revision"]["signal_total"], 0)
        self.assertEqual(result["missing_protected_spans"], {})


if __name__ == "__main__":
    unittest.main()
