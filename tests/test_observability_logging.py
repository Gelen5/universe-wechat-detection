"""Structured events must actually reach the container log.

Under the web container the ``universe`` logger had no handler, so every
``event()`` call at INFO was dropped: the provider-outage signal added for the
relay incident never appeared in ``docker logs``.
"""
import io
import json
import logging
import unittest

from server import observability


class ObservabilityLoggingTests(unittest.TestCase):
    def test_logger_carries_its_own_handler(self):
        logger = logging.getLogger('universe')
        self.assertTrue(logger.handlers, 'no handler: INFO events would be dropped')
        self.assertFalse(logger.propagate, 'propagate would duplicate lines under Celery')
        self.assertLessEqual(logger.level, logging.INFO)

    def test_event_writes_one_json_line(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger = logging.getLogger('universe')
        logger.addHandler(handler)
        try:
            observability.event('probe.test', ok=True, path='/api/x')
        finally:
            logger.removeHandler(handler)
        lines = [line for line in stream.getvalue().splitlines() if line.strip()]
        self.assertEqual(1, len(lines))
        payload = json.loads(lines[0])
        self.assertEqual('probe.test', payload['event'])
        self.assertTrue(payload['ok'])
        self.assertEqual('/api/x', payload['path'])
        self.assertIn('timestamp_ms', payload)

    def test_unset_fields_are_omitted(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger('universe')
        logger.addHandler(handler)
        try:
            observability.event('probe.empty', user_id=None, note='x')
        finally:
            logger.removeHandler(handler)
        payload = json.loads(stream.getvalue().strip())
        self.assertNotIn('user_id', payload)
        self.assertEqual('x', payload['note'])


if __name__ == '__main__':
    unittest.main()
