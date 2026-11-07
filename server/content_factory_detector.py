"""Zhuque result normalization; callers must budget and persist attempts."""
from __future__ import annotations

import math
import os
import requests

ENDPOINT = 'https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify'
PROVIDER = '@makers/zhuque-text'


def detect(text, *, key=None, timeout=45, post=None):
    """Return explicit states, never raw provider errors or credentials."""
    token = (key if key is not None else os.getenv('MAKERS_MODELS_KEY', '')).strip()
    if not token:
        return {'status': 'unavailable', 'error': 'not_configured'}
    if not isinstance(text, str) or not text.strip():
        return {'status': 'failed', 'error': 'empty_text'}
    try:
        response = (post or requests.post)(ENDPOINT, headers={'Authorization': 'Bearer ' + token},
                        json={'text': text, 'is_merge': True}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get('status') != 'success':
            raise ValueError('bad status')
        human = float(payload['labels_ratio']['0'])
        if not math.isfinite(human) or not 0 <= human <= 1:
            raise ValueError('bad ratio')
        usage = payload.get('makers_models_usage') or {}
        tokens = usage.get('total_tokens') if isinstance(usage, dict) else None
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            tokens = None
        return {'status': 'success', 'provider': PROVIDER, 'human_ratio': human,
                'makers_tokens': tokens}
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        return {'status': 'failed', 'error': 'provider_or_response_error'}
