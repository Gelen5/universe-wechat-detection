"""Rebuild CSS unicode ranges from checked-in WOFF2 cmaps, never from a CDN.

Developer-only helper: requires fonttools and brotli in the invoking interpreter.
Neither package is a web/worker runtime dependency. Use --check in asset QA.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


def generate(source: str, root: Path) -> str:
    from fontTools.ttLib import TTFont

    cache = {}

    def face(match):
        block = match.group(0)
        path = re.search(r"url\('([^']+)'\)", block)
        if not path:
            raise ValueError('Every font face must reference a local WOFF2 file')
        name = path[1].lstrip('/')
        file = (root / name).resolve()
        if not file.is_relative_to((root / 'static/vendor/fonts').resolve()):
            raise ValueError('Font must be in static/vendor/fonts')
        if name not in cache:
            with TTFont(file) as font:
                points = sorted(font.getBestCmap())
            intervals = []
            for point in points:
                if intervals and point == intervals[-1][1] + 1:
                    intervals[-1][1] = point
                else:
                    intervals.append([point, point])
            cache[name] = ','.join(
                f'U+{a:X}' if a == b else f'U+{a:X}-{b:X}' for a, b in intervals)
        declaration = 'unicode-range:' + cache[name] + ';'
        if 'unicode-range:' in block:
            return re.sub(r'unicode-range:[^;]+;', declaration, block)
        return block[:-1] + declaration + '\n}'

    return re.sub(r'@font-face\{[^}]*\}', face, source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    css = root / 'static/fonts.css'
    original = css.read_bytes().decode('utf-8')
    result = generate(original, root)
    if args.check:
        if result != original:
            raise SystemExit('Font unicode ranges are stale; run this helper without --check')
        print('All local font ranges match their actual cmaps')
    else:
        css.write_bytes(result.encode('utf-8'))
