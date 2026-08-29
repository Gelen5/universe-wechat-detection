import tempfile
import unittest
from pathlib import Path

from toolkit.tie_tu import (
    add_source,
    build_plan,
    generate_batch,
    generate_pilot,
    build_card_prompt,
    record_batch,
    record_pilot,
    set_approval,
    validate_plan,
)


class TieTuContractTests(unittest.TestCase):
    def test_plan_uses_independent_protocol(self):
        plan = build_plan("城市", "长沙新老城区变化", image_count=2)
        self.assertEqual(plan.mode, "tie_tu")
        self.assertEqual(plan.content_brief.mode, "tie_tu")
        self.assertIn("card_plan", plan.approval_state.stages)
        add_source(plan, "ai-1", "ai", title="AI生成底图", status="illustrative")
        set_approval(plan, "card_plan", "approved")
        self.assertEqual(plan.source_ledger.records[0].source_id, "ai-1")
        self.assertTrue(validate_plan(plan)["ok"])

    def test_generation_state_tracks_pilot_and_batch(self):
        plan = build_plan("生活方式", "复古女性写真", image_count=2)
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "pilot.png"
            image.write_bytes(b"placeholder")
            record_pilot(plan, 1, str(image))
            self.assertEqual(plan.generation_state.pilot_status, "generated")
            record_batch(plan, "completed")
            self.assertEqual(plan.generation_state.batch_status, "completed")

    def test_host_generation_never_creates_api_fallback_request(self):
        plan = build_plan("城市", "长沙新老城区变化", image_count=2, portrait_mode="off")
        set_approval(plan, "card_plan", "approved")
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "内置 Image"):
                generate_pilot(plan, temp_dir)
            self.assertEqual(list(Path(temp_dir).glob("*.request.json")), [])
            set_approval(plan, "pilot_image", "approved")
            self.assertEqual(generate_batch(plan, temp_dir), 0)
            self.assertEqual(plan.generation_state.batch_status, "pending")
            self.assertEqual(list(Path(temp_dir).glob("*.request.json")), [])

    def test_prompt_requires_text_in_same_host_image_call(self):
        plan = build_plan("旅游", "带父母慢旅行", title="别再带父母去热门景点", image_count=1, portrait_mode="off")
        prompt = build_card_prompt(plan, plan.cards[0])
        self.assertIn('Text (verbatim): "别再带父母去热门景点"', prompt)
        self.assertIn("same image-generation call", prompt)
        self.assertNotIn("do not render words", prompt.lower())


if __name__ == "__main__":
    unittest.main()
