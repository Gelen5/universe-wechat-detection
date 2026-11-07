"""Fail-closed publication decisions for generated products.

Individual check results are explicit: unknown checks never pass by default.
"""
from __future__ import annotations

import math
import re
from urllib.parse import urlparse


def publication_decision(product_type, *, title, content, source, checks, detector=None):
    if product_type not in ('article', 'image'):
        raise ValueError('unsupported product type')
    reasons = []
    if not isinstance(title, str) or not title.strip():
        reasons.append('missing_title')
    if not isinstance(content, str) or not content.strip():
        reasons.append('missing_content')
    source = source if isinstance(source, dict) else {}
    checks = checks if isinstance(checks, dict) else {}
    detector = detector if isinstance(detector, dict) else {}
    try:
        url = urlparse((source or {}).get('url') or '')
        valid_source = url.scheme in ('http', 'https') and bool(url.hostname)
    except (TypeError, ValueError):
        valid_source = False
    if not valid_source or not (source or {}).get('id') or not (source or {}).get('observed_at'):
        reasons.append('missing_source')
    required = ['facts', 'copyright', 'safety', 'title_consistency', 'editorial_quality', 'storage']
    if product_type == 'article':
        length = len(re.sub(r'\s+', '', content if isinstance(content, str) else ''))
        if not 1000 <= length <= 1200:
            reasons.append('article_length')
        try:
            human = float(detector['human_ratio'])
            if (detector or {}).get('status') != 'success' or not math.isfinite(human) or not 0.8 <= human <= 1:
                reasons.append('detector_not_passed')
        except (TypeError, ValueError, KeyError):
            reasons.append('detector_not_passed')
    else:
        required += ['image_decode', 'image_dimensions', 'image_text', 'visual_quality']
    for name in required:
        if (checks or {}).get(name) is not True:
            reasons.append('check_not_passed:' + name)
    return {'status': 'held' if reasons else 'eligible', 'reasons': reasons,
            'note': '检测结果不构成版权安全或平台推荐保证'}
