import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PIL import Image
from server import creator_tools as tools


class RemixMultiTests(unittest.TestCase):
    def test_joint_vision_receives_every_image(self):
        stream = io.BytesIO()
        Image.new('RGB', (80, 120), 'green').save(stream, 'PNG')
        source = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
        payload = {'ideas':[{'id':key} for key in 'ABC'], 'claims':[], 'visual_contract':{'asset_type':'poster','palette':'navy blue'}}
        response = Mock()
        response.json.return_value = {'choices':[{'message':{'content':json.dumps(payload)}}]}
        with patch.object(tools.workbench, '_setting', return_value='test'), patch.object(tools.workbench, '_headers', return_value={}), patch.object(tools.requests, 'post', return_value=response) as post:
            result = tools.viral_remix_analysis([source,source])
        content = post.call_args.kwargs['json']['messages'][0]['content']
        self.assertEqual(len([c for c in content if c['type']=='image_url']),2)
        self.assertEqual(len(result['measurement']),2)
        with self.assertRaises(ValueError):
            tools.viral_remix_analysis([source]*9)

    def test_programmatic_chinese_series_without_image_provider(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(tools,'OUTPUT_DIR',Path(folder)), patch('server.image_provider.generate') as generate:
            result = tools.generate_viral_remix_image('testsession123',{'visual_contract':{'asset_type':'text'},'headline':'测试','image_brief':'','cards':[{'headline':'中文排版\n第一张','render_mode':'text-only'},{'headline':'中文排版\n第二张','render_mode':'text-only'}]})
            self.assertEqual(len(result['images']),2)
            self.assertTrue((Path(folder)/'tie-tu/testsession123/remix-01.jpg').exists())
            generate.assert_not_called()

    def test_poster_cannot_silently_become_a_text_card(self):
        stream=io.BytesIO()
        Image.new('RGB',(768,1024),'#051b40').save(stream,'PNG')
        contract={'asset_type':'poster','palette':'navy and electric blue','purpose':'product promotion','title_color':'#FFFFFF','accent_color':'#FFE16A'}
        with tempfile.TemporaryDirectory() as folder, patch.object(tools,'OUTPUT_DIR',Path(folder)), patch('server.image_provider.generate',return_value={'data':[{'b64_json':base64.b64encode(stream.getvalue()).decode()}]}) as generate:
            tools.generate_viral_remix_image('poster-test123',{'visual_contract':contract,'cards':[{'headline':'原创海报','render_mode':'text-only','image_brief':'glowing panels'}]})
            self.assertEqual(generate.call_count,1)
            self.assertIn('navy and electric blue',generate.call_args.args[0]['prompt'])
            spec=json.loads((Path(folder)/'tie-tu/poster-test123/case-01.json').read_text(encoding='utf-8'))
            self.assertTrue(spec.get('base'))
            self.assertTrue(spec.get('layers'))

if __name__ == '__main__':
    unittest.main()
