"""The host runtime asks exactly what the workflow asked for."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from toolkit.host_prompts import render  # noqa: E402
from toolkit.host_runtime import parse_result, run_node_with  # noqa: E402


class RenderTests(unittest.TestCase):
    def test_prompt_carries_purpose_rules_state_and_contract(self):
        request = {
            "purpose": "根据读者认知和证据设计结构",
            "read": ["references/frameworks.md"],
            "rules": ["只使用可追溯的事实"],
            "state_fields": {"topic": "素材库"},
            "output_contract": {"outline": "array<object>"},
        }
        prompt = render(request, ROOT)
        self.assertIn("根据读者认知和证据设计结构", prompt)
        self.assertIn("只使用可追溯的事实", prompt)
        self.assertIn("素材库", prompt)
        self.assertIn("array<object>", prompt)
        # The reference file really is inlined, not just named.
        self.assertIn("references/frameworks.md", prompt)
        self.assertGreater(len(prompt), 2000)

    def test_missing_reference_file_does_not_break_rendering(self):
        prompt = render({"purpose": "x", "read": ["references/nope.md"],
                         "output_contract": {}}, ROOT)
        self.assertIn("x", prompt)


class ParseTests(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual({"a": 1}, parse_result('{"a": 1}'))

    def test_fenced_json(self):
        self.assertEqual({"a": 1}, parse_result('```json\n{"a": 1}\n```'))

    def test_non_object_is_rejected(self):
        for raw in ('[1, 2]', 'not json', ''):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_result(raw)


class RuntimeTests(unittest.TestCase):
    def test_draft_retries_malformed_json_instead_of_failing_run(self):
        class Node:
            status = "awaiting_host"
            request = {"purpose": "write", "read": [], "rules": [], "output_contract": {}}
            message = ""

        class State:
            nodes = {"draft": Node()}

        import toolkit.host_runtime as runtime
        original_run, original_apply = runtime.run_node, runtime.apply_host_result
        prompts = []
        applied = []
        try:
            runtime.run_node = lambda state, node, output_dir=None: None
            runtime.apply_host_result = lambda state, node, result: (
                applied.append(result), setattr(state.nodes[node], "status", "passed"))
            replies = iter(['{"draft": "bad "quote""}', '{"draft": "complete article"}'])
            state = run_node_with(State(), "draft", lambda prompt: prompts.append(prompt) or next(replies))
        finally:
            runtime.run_node, runtime.apply_host_result = original_run, original_apply
        self.assertEqual("passed", state.nodes["draft"].status)
        self.assertEqual([{"draft": "complete article"}], applied)
        self.assertEqual(2, len(prompts))
        self.assertIn("合法 JSON", prompts[1])

    def test_a_node_that_does_not_need_the_host_is_left_alone(self):
        class Node:
            status = "passed"
            request = {}

        class State:
            nodes = {"strategy": Node()}

        import toolkit.host_runtime as runtime
        original_run = runtime.run_node
        calls = []
        try:
            runtime.run_node = lambda state, node, output_dir=None: None
            state = run_node_with(State(), "strategy",
                                  lambda prompt: calls.append(prompt) or "{}")
        finally:
            runtime.run_node = original_run
        self.assertEqual([], calls)
        self.assertEqual("passed", state.nodes["strategy"].status)

    def test_awaiting_node_is_rendered_and_applied(self):
        applied = []

        class Node:
            status = "awaiting_host"
            request = {"purpose": "P", "read": [], "rules": [], "output_contract": {}}
            message = ""

        class State:
            nodes = {"strategy": Node()}

        import toolkit.host_runtime as runtime
        original_run, original_apply = runtime.run_node, runtime.apply_host_result
        try:
            runtime.run_node = lambda state, node, output_dir=None: None
            runtime.apply_host_result = lambda state, node, result: (
                applied.append(result), setattr(state.nodes[node], "status", "passed"))
            prompts = []
            state = run_node_with(State(), "strategy",
                                  lambda prompt: prompts.append(prompt) or '{"outline": []}')
        finally:
            runtime.run_node, runtime.apply_host_result = original_run, original_apply
        self.assertEqual(1, len(prompts))
        self.assertIn("P", prompts[0])
        self.assertEqual([{"outline": []}], applied)


if __name__ == "__main__":
    unittest.main()
class CoerceTests(unittest.TestCase):
    def test_extra_source_and_claim_fields_are_dropped(self):
        from toolkit.host_runtime import _coerce
        payload = {'evidence_pack': {
            'sources': {'records': [{'source_id': 's1', 'url': 'https://e.com',
                                     'verification': 'checked'}]},
            'claims': [{'claim_id': 'c1', 'text': 't', 'kind': 'fact',
                        'materiality': 'key', 'status': 'verified', 'extra': 1}],
            'research_status': 'complete', 'limitations': []}}
        result = _coerce('research', json.loads(json.dumps(payload)))
        self.assertNotIn('verification', result['evidence_pack']['sources']['records'][0])
        self.assertNotIn('extra', result['evidence_pack']['claims'][0])

    def test_bare_array_sources_become_a_ledger(self):
        from toolkit.host_runtime import _coerce
        result = _coerce('research', {'evidence_pack': {'sources': [{'source_id': 's1'}]}})
        self.assertEqual({'records': [{'source_id': 's1'}]}, result['evidence_pack']['sources'])

