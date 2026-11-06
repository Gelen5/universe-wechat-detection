import base64
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import creator_tools, image_provider


class CreatorToolsTests(unittest.TestCase):
    def test_xiaohongshu_package_uses_six_card_contract(self):
        payload = {
            "stage": "starter",
            "titles": [{"text": "标题", "keyword": "关键词", "reason": "具体", "promise": "步骤"}] * 3,
            "selected_title": "具体标题",
            "body": "第一步，完成一件具体事情。" * 20,
            "cards": [
                {"index": index, "role": "cover" if index == 1 else "step", "headline": f"第{index}页", "message": "一个重点", "action": "不同动作", "visual_prompt": "明亮工作台"}
                for index in range(1, 7)
            ],
            "precheck": {"status": "ready", "issues": []},
        }
        with patch.object(creator_tools.workbench, "_json_text", return_value=payload):
            result = creator_tools.xiaohongshu_package("主题", "账号", "读者", "教育", "", "流程拆解型")
        self.assertEqual(len(result["cards"]), 6)
        self.assertEqual(result["evidence_state"], "unknown")
        self.assertEqual(result["skill"], "xiaohongshu-creator-skill")

    def test_tie_tu_plan_preserves_count_and_contract(self):
        enriched = {
            "angle": "从生活场景切入",
            "copy": "配套文案",
            "cta": "收藏后慢慢看",
            "cards": [
                {"index": index, "overlay_text": f"卡片{index}", "caption": "短句", "visual_subject": "主体", "composition": "3:4", "scene": f"场景{index}", "action": f"动作{index}"}
                for index in range(1, 5)
            ],
        }
        with patch.object(creator_tools.workbench, "_json_text", return_value=enriched):
            result = creator_tools.tie_tu_plan("生活方式", "慢旅行", "旅行换一种玩法", "list", 4, "温暖", "40+", "off")
        self.assertEqual(result["image_count"], 4)
        self.assertEqual(len(result["cards"]), 4)
        self.assertEqual(result["cards"][1]["card_brief"]["action"], "动作2")

    def test_tie_tu_accepts_all_display_labels_and_empty_portrait_mode(self):
        for canonical, label in creator_tools.CONTENT_TYPES.items():
            with self.subTest(label=label):
                enriched = {'cards': [{'index': 1, 'overlay_text': '标题', 'caption': '文字',
                                       'visual_subject': '茶杯', 'composition': '留白'}]}
                with patch.object(creator_tools.workbench, '_json_text', return_value=enriched):
                    result = creator_tools.tie_tu_plan('生活', '主题', '', label, 1, '', '', '')
                self.assertEqual(result['content_type'], canonical)

    def test_tie_tu_does_not_silently_accept_unknown_type(self):
        with self.assertRaisesRegex(ValueError, '不支持的贴图号内容类型'):
            creator_tools.tie_tu_plan('生活', '主题', '', '未知类型', 1, '', '', 'auto')

    def test_tie_tu_rejects_person_when_user_requests_no_people(self):
        enriched = {'cards': [{'index': 1, 'overlay_text': '封面', 'caption': '文字',
                              'visual_subject': '成年女性在窗边', 'composition': '3:4'}]}
        with patch.object(creator_tools.workbench, '_json_text', return_value=enriched):
            with self.assertRaisesRegex(creator_tools.workbench.ProviderError, '无人物画面方案'):
                creator_tools.tie_tu_plan('生活方式', '下班休息', '', 'list', 1, '', '', 'off')

    def test_tie_tu_auto_falls_back_when_visual_repair_fails(self):
        original = {'copy': '原文案', 'cards': [{'index': 1, 'overlay_text': '保留标题', 'caption': '保留短句',
                    'visual_subject': '成年女性在窗边', 'composition': '3:4'}]}
        with patch.object(creator_tools.workbench, '_json_text', side_effect=[original, RuntimeError('provider error')]):
            result = creator_tools.tie_tu_plan('生活方式', '下班休息', '', 'list', 1, '', '', 'auto')
        self.assertFalse(result['portrait_enabled'])
        self.assertEqual(result['cards'][0]['overlay_text'], '保留标题')
        self.assertEqual(result['cards'][0]['visual_subject'], '与内容主题相关的静物主体')
        self.assertIn('通用静物', result['visual_fallback_notice'])

    def test_tie_tu_no_people_explicit_negative_is_not_conflict(self):
        original = {'cards': [{'index': 1, 'overlay_text': '标题', 'caption': '短句',
                    'visual_subject': '桌面静物，没有手部', 'composition': '3:4'}]}
        with patch.object(creator_tools.workbench, '_json_text', return_value=original) as model:
            result = creator_tools.tie_tu_plan('生活', '主题', '', 'list', 1, '', '', 'auto')
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result['cards'][0]['visual_subject'], '桌面静物，没有手部')

    def test_tie_tu_repairs_only_visual_when_portrait_disabled(self):
        original = {'copy': '原文案', 'cards': [{'index': 1, 'overlay_text': '保留标题', 'caption': '保留短句',
                    'visual_subject': '成年女性在窗边', 'composition': '3:4'}]}
        repaired = {'cards': [{'index': 1, 'visual_subject': '桌上的茶杯', 'scene': '暖光客厅', 'action': '茶杯静置'}]}
        with patch.object(creator_tools.workbench, '_json_text', side_effect=[original, repaired]) as model:
            result = creator_tools.tie_tu_plan('生活方式', '下班休息', '', 'list', 1, '', '', 'off')
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result['cards'][0]['overlay_text'], '保留标题')
        self.assertEqual(result['cards'][0]['visual_subject'], '桌上的茶杯')
        self.assertEqual(result['copy'], '原文案')

    def test_tie_tu_rejects_missing_or_duplicate_cards(self):
        enriched = {'cards': [{'index': 1, 'overlay_text': '封面', 'caption': '文字',
                              'visual_subject': '茶杯', 'composition': '3:4'}]}
        with patch.object(creator_tools.workbench, '_json_text', return_value=enriched):
            with self.assertRaisesRegex(creator_tools.workbench.ProviderError, '数量'):
                creator_tools.tie_tu_plan('生活方式', '下班休息', '', 'list', 2, '', '', 'off')

    def test_image_generation_saves_api_result(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(creator_tools, "OUTPUT_DIR", Path(folder)), patch.object(
                image_provider,
                "generate",
                return_value={"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]},
            ):
                result = creator_tools.generate_card_image("tie-tu", "session123", {"index": 1, "overlay_text": "早安"}, "温暖")
            self.assertGreater(result["bytes"], 0)
            self.assertIn("/api/creator-tools/assets/tie-tu/session123/card-01.png", result["url"])

    def test_tie_tu_preserves_source_frame_and_requests_complete_text(self):
        from PIL import Image, ImageDraw
        source = Image.new('RGB', (400, 200), 'white')
        draw = ImageDraw.Draw(source)
        draw.rectangle((0, 0, 24, 199), fill='red')
        draw.rectangle((375, 0, 399, 199), fill='blue')
        buf = io.BytesIO()
        source.save(buf, format='PNG')

        def provider(payload):
            self.assertTrue(payload['preserve_original'])
            self.assertIn('宽高比必须为 3:4', payload['prompt'])
            self.assertIn('把在意说清楚', payload['prompt'])
            self.assertIn('从一句真诚的话开始。', payload['prompt'])
            self.assertIn('at least 10% clear margin', payload['prompt'])
            return {'data': [{'b64_json': base64.b64encode(buf.getvalue()).decode()}]}

        with tempfile.TemporaryDirectory() as folder, patch.object(creator_tools, 'OUTPUT_DIR', Path(folder)), \
             patch.object(image_provider, 'generate', side_effect=provider):
            creator_tools.generate_card_image('tie-tu', 'sample', {'index': 1, 'overlay_text': '把在意说清楚',
                                               'caption': '从一句真诚的话开始。'}, size='768x1024')
            with Image.open(Path(folder) / 'tie-tu' / 'sample' / 'card-01.png') as image:
                image = image.convert('RGB')
                self.assertEqual((400, 200), image.size)
                self.assertEqual((255, 0, 0), image.getpixel((5, 100)))
                self.assertEqual((0, 0, 255), image.getpixel((394, 100)))

    def test_tie_tu_no_people_is_carried_to_image_prompt(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as folder, patch.object(creator_tools, 'OUTPUT_DIR', Path(folder)), patch.object(
            image_provider, 'generate', return_value={'data': [{'b64_json': base64.b64encode(png).decode('ascii')}]}
        ) as generate:
            creator_tools.generate_card_image('tie-tu', 'session', {'index': 1, 'overlay_text': '休息', 'portrait_enabled': False})
        prompt = generate.call_args.args[0]['prompt']
        self.assertIn('Do not depict people', prompt)
        self.assertNotIn('Keep the same fictional adult person', prompt)

    def test_resolve_portrait_mode_reads_the_users_own_wording(self):
        cases = [
            ('', '图片中要有人物', 'required'),
            ('auto', '中老年人如何安排退休生活，图片中要有人物', 'required'),
            ('auto', '要有真人出镜', 'required'),
            ('auto', '人物', 'required'),
            ('auto', '画面里不要出现人物', 'off'),
            ('auto', '不需要任何人物，纯静物', 'off'),
            ('auto', '要有人物，不要静物', 'required'),
            ('auto', '退休生活', 'auto'),
            ('auto', '无聊的时候做什么', 'auto'),
            # An explicit dropdown choice is never overridden by free text.
            ('off', '图片中要有人物', 'off'),
            ('required', '退休生活', 'required'),
        ]
        for requested, text, expected in cases:
            with self.subTest(requested=requested, text=text):
                self.assertEqual(creator_tools.resolve_portrait_mode(requested, intent=text), expected)

    def test_tie_tu_auto_detects_people_from_the_requirement_field(self):
        captured = {}

        def enrich(prompt, *args, **kwargs):
            captured['prompt'] = prompt
            return {'angle': '生活视角', 'copy': '文案', 'cta': '收藏', 'cards': [
                {'index': index, 'overlay_text': f'标题{index}', 'caption': '短句',
                 'visual_subject': '中年女性在客厅整理书架', 'composition': '3:4 留白',
                 'scene': f'居家场景{index}', 'action': '伸手放书'} for index in (1, 2)]}

        with patch.object(creator_tools.workbench, '_json_text', side_effect=enrich):
            result = creator_tools.tie_tu_plan('生活方式', '退休生活怎么安排', '', None, 2,
                                               '温暖', '50岁', 'auto', '图片中要有人物')
        self.assertTrue(result['portrait_enabled'])
        self.assertEqual(result['portrait_route'], 'clean-lifestyle')
        self.assertTrue(result['cards'][0]['portrait_spec'].get('negative_prompt'))
        self.assertIn('画面必须出现人物', captured['prompt'])
        self.assertIn('自然生活感', captured['prompt'])
        self.assertNotIn('画面不能出现人物', captured['prompt'])

    def test_tie_tu_auto_respects_an_explicit_no_people_requirement(self):
        enriched = {'cards': [{'index': 1, 'overlay_text': '封面', 'caption': '短句',
                              'visual_subject': '窗边的书桌', 'composition': '3:4', 'scene': '书房',
                              'action': '阳光落在桌面上'}]}
        with patch.object(creator_tools.workbench, '_json_text', return_value=enriched) as model:
            result = creator_tools.tie_tu_plan('生活方式', '安静地读完一本书', '', 'list', 1,
                                               '', '', 'auto', '画面不要出现人物')
        self.assertFalse(result['portrait_enabled'])
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result['cards'][0]['portrait_spec'], {})

    def test_tie_tu_image_prompt_carries_the_skill_portrait_spec(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        card = {
            'index': 1, 'overlay_text': '退休后先做这三件事', 'caption': '从一张日程表开始',
            'composition': '3:4 留白', 'scene': '居家客厅', 'action': '整理书架',
            'portrait_enabled': True,
            'portrait_spec': {
                'subject': 'fictional clearly adult East Asian woman',
                'direction': 'natural lifestyle portrait, soft daylight',
                'pose': 'three-quarter body direction',
                'camera': '3:4 vertical portrait, 50mm',
                'lighting': 'motivated natural light',
                'texture': 'natural skin pores',
                'model_bible': {'continuity': 'same fictional adult model across all portrait cards'},
                'negative_prompt': 'plastic skin, deformed hands, child, minor',
            },
        }
        with tempfile.TemporaryDirectory() as folder, patch.object(creator_tools, 'OUTPUT_DIR', Path(folder)), patch.object(
            image_provider, 'generate',
            return_value={'data': [{'b64_json': base64.b64encode(png).decode('ascii')}]}
        ) as generate:
            creator_tools.generate_card_image('tie-tu', 'session', card)
        prompt = generate.call_args.args[0]['prompt']
        for expected in ('Portrait subject: fictional clearly adult East Asian woman',
                         'Visual direction: natural lifestyle portrait',
                         'Pose and action: three-quarter body direction',
                         'Camera: 3:4 vertical portrait, 50mm',
                         'Continuity: same fictional adult model',
                         'Avoid (portrait quality): plastic skin, deformed hands, child, minor'):
            with self.subTest(expected=expected):
                self.assertIn(expected, prompt)
        self.assertNotIn('Do not depict people', prompt)

    def test_tie_tu_image_prompt_hides_portrait_spec_when_people_are_off(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        card = {'index': 1, 'overlay_text': '安静', 'portrait_enabled': False,
                'portrait_spec': {'subject': 'fictional clearly adult East Asian woman',
                                  'negative_prompt': 'plastic skin'}}
        with tempfile.TemporaryDirectory() as folder, patch.object(creator_tools, 'OUTPUT_DIR', Path(folder)), patch.object(
            image_provider, 'generate',
            return_value={'data': [{'b64_json': base64.b64encode(png).decode('ascii')}]}
        ) as generate:
            creator_tools.generate_card_image('tie-tu', 'session', card)
        prompt = generate.call_args.args[0]['prompt']
        self.assertIn('Do not depict people', prompt)
        self.assertNotIn('Portrait subject', prompt)
        self.assertNotIn('Avoid (portrait quality)', prompt)

    def test_hit_detector_returns_editorial_gate(self):
        body = "退休以后，先记录真实开支，再和家人确认生活计划。\n\n" * 30
        result = creator_tools.detect_article("退休以后，先做这三件事", body)
        self.assertIn(result["editorial_gate"]["label"], {"暂缓发布", "修改后复核", "可进入人工终审"})
        self.assertIn("scores", result)
        self.assertEqual(result["skill"], "wechat-hit-detector-skill")


if __name__ == "__main__":
    unittest.main()
