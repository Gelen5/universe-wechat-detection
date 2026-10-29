"""gpt-image-2.5 rejects any explicit size; the frame is enforced afterwards.

The gateway answers ``size must be one of: auto for gpt-image-2.5``, so the
request always carries ``auto``. The wanted ratio still goes into the prompt to
nudge the composition, and the returned image is cropped and scaled to the exact
requested pixels because that is the only way this model yields a 3:4 card.
"""
import unittest

from server import image_provider


class RequestSizeTests(unittest.TestCase):
    def test_auto_only_models_are_sent_auto(self):
        for model in ('gpt-image-2.5', 'gpt-image-2', 'gpt-image-1'):
            with self.subTest(model=model):
                self.assertEqual('auto', image_provider._request_size('768x1024', model))

    def test_size_honouring_models_keep_the_requested_value(self):
        self.assertEqual('768x1024',
                         image_provider._request_size('768x1024', 'grok-imagine-image-2.0'))

    def test_crop_target_is_still_the_requested_size(self):
        # The crop helper must see the caller's size, not "auto".
        result = {'data': []}
        self.assertEqual(result, image_provider._fit_images(result, '768x1024'))


if __name__ == '__main__':
    unittest.main()
