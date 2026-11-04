"""gpt-image-2.5 rejects any explicit size; the frame is enforced afterwards.

The gateway answers ``size must be one of: auto for gpt-image-2.5``, so the
request always carries ``auto``. The wanted ratio still goes into the prompt to
nudge the composition, and the returned image is cropped and scaled to the exact
requested pixels because that is the only way this model yields a 3:4 card.
"""
import unittest
import base64
import io
from unittest.mock import patch

from PIL import Image, ImageDraw

from server import image_provider


class RequestSizeTests(unittest.TestCase):
    def test_original_mode_bypasses_resize_and_returns_provider_response(self):
        result = {'data': [{'b64_json': 'example'}]}
        with patch.object(image_provider.accounts, 'provider_settings', return_value={'image_api_key':'test'}), \
             patch.object(image_provider.workbench, '_setting', return_value='test'), \
             patch('server.providers.OpenAICompatibleProvider'), \
             patch('server.providers.ModelService') as service, \
             patch.object(image_provider, '_fit_images') as fit:
            service.return_value.generate_image.return_value = result
            returned = image_provider.generate({'prompt':'test', 'size':'768x1024', 'preserve_original':True})
        self.assertIs(returned, result)
        fit.assert_not_called()

    def test_original_jpeg_converts_to_png_without_resize(self):
        source = Image.new('RGB', (400, 200), 'red')
        raw = io.BytesIO()
        source.save(raw, format='JPEG')
        result = image_provider.ensure_png(raw.getvalue())
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual('PNG', image.format)
            self.assertEqual((400, 200), image.size)

    def test_auto_only_models_are_sent_auto(self):
        for model in ('gpt-image-2.5', 'gpt-image-2', 'gpt-image-1'):
            with self.subTest(model=model):
                self.assertEqual('auto', image_provider._request_size('768x1024', model))

    def test_size_honouring_models_keep_the_requested_value(self):
        self.assertEqual('768x1024',
                         image_provider._request_size('768x1024', 'grok-imagine-image-2.0'))

    def test_preserve_frame_retains_content_at_all_four_edges(self):
        # A wide source has distinguishable edge strips that a center crop loses.
        source = Image.new('RGB', (400, 200), 'white')
        draw = ImageDraw.Draw(source)
        draw.rectangle((0, 0, 24, 199), fill='red')
        draw.rectangle((375, 0, 399, 199), fill='blue')
        draw.rectangle((25, 0, 374, 24), fill='green')
        draw.rectangle((25, 175, 374, 199), fill='yellow')
        buf = io.BytesIO(); source.save(buf, format='PNG')
        response = {'data': [{'b64_json': base64.b64encode(buf.getvalue()).decode()}]}
        result = image_provider._fit_images(response, '300x400', preserve_frame=True)
        image = Image.open(io.BytesIO(base64.b64decode(result['data'][0]['b64_json']))).convert('RGB')
        self.assertEqual(image.size, (300, 400))
        # Foreground is 300x150 centered vertically; verify all edge strips.
        self.assertEqual(image.getpixel((5, 200)), (255, 0, 0))
        self.assertEqual(image.getpixel((294, 200)), (0, 0, 255))
        self.assertEqual(image.getpixel((150, 130)), (0, 128, 0))
        self.assertEqual(image.getpixel((150, 269)), (255, 255, 0))

    def test_default_fit_still_crops_for_other_callers(self):
        source = Image.new('RGB', (400, 200), 'white')
        buf = io.BytesIO(); source.save(buf, format='PNG')
        response = {'data': [{'b64_json': base64.b64encode(buf.getvalue()).decode()}]}
        result = image_provider._fit_images(response, '300x400')
        image = Image.open(io.BytesIO(base64.b64decode(result['data'][0]['b64_json'])))
        self.assertEqual(image.size, (300, 400))

    def test_crop_target_is_still_the_requested_size(self):
        # The crop helper must see the caller's size, not "auto".
        result = {'data': []}
        self.assertEqual(result, image_provider._fit_images(result, '768x1024'))


if __name__ == '__main__':
    unittest.main()
