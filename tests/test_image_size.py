"""A wrong-shaped card is fixed by asking for the right size, not by cropping.

gpt-image-2.5 composes its own frame and ignores `size`, so a 3:4 贴图 came back
landscape; the previous fix centre-cropped and rescaled the paid image, which
destroys the composition the model chose. Vertical work now goes to
grok-imagine-image-2.0 with an explicit 1024x1536, and the delivered bytes are
reported, never rewritten.
"""
import base64
import io
import unittest

from PIL import Image

from server import image_provider


def _png(width, height):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), (10, 20, 30)).save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


class EffectiveSizeTests(unittest.TestCase):
    def test_vertical_request_becomes_1024x1536_on_a_size_honouring_model(self):
        for requested in ('768x1024', '1024x1365', '800x1200'):
            with self.subTest(requested=requested):
                self.assertEqual('1024x1536',
                                 image_provider._effective_size(requested, 'grok-imagine-image-2.0'))

    def test_square_and_horizontal_requests(self):
        self.assertEqual('1024x1024', image_provider._effective_size('768x768', 'grok-imagine-image-2.0'))
        self.assertEqual('1536x1024', image_provider._effective_size('1280x720', 'grok-imagine-image-2.0'))

    def test_other_models_keep_the_requested_size(self):
        self.assertEqual('768x1024', image_provider._effective_size('768x1024', 'gpt-image-2.5'))

    def test_unparseable_size_is_left_alone(self):
        self.assertEqual('auto', image_provider._effective_size('auto', 'grok-imagine-image-2.0'))


class NoCropTests(unittest.TestCase):
    def test_delivered_bytes_are_untouched_and_size_is_reported(self):
        original = _png(1536, 1024)  # model returned landscape for a 3:4 request
        result = {'data': [{'b64_json': original}]}
        returned = image_provider._describe_images(result)
        self.assertEqual(original, returned['data'][0]['b64_json'])
        self.assertEqual((1536, 1024),
                         (returned['data'][0]['width'], returned['data'][0]['height']))

    def test_missing_payload_does_not_raise(self):
        result = {'data': [{'note': 'no image'}]}
        self.assertEqual(result, image_provider._describe_images(result))

    def test_cropping_helper_is_gone(self):
        self.assertFalse(hasattr(image_provider, '_fit_images'))


if __name__ == '__main__':
    unittest.main()
