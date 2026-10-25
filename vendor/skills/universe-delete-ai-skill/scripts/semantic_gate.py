"""CLI for preservation checks; rejected candidates never overwrite an input."""
import argparse
import json
from pathlib import Path
try:
    from .preservation import gate, read, review_template
except ImportError:
    from preservation import gate, read, review_template

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('original', type=Path)
    p.add_argument('revision', type=Path)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--review', type=Path)
    p.add_argument('--base', type=Path)
    p.add_argument('--mode', choices=['minimal', 'standard', 'deep'], default='minimal')
    p.add_argument('--review-template', action='store_true')
    a = p.parse_args()
    original, revision = read(a.original), read(a.revision)
    manifest, plan = json.loads(read(a.manifest)), json.loads(read(a.plan))
    if a.review_template:
        result = review_template(original, revision, manifest, plan)
    else:
        result = gate(original, revision, manifest, plan, json.loads(read(a.review)) if a.review else None,
                      a.mode, read(a.base) if a.base else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if a.review_template or result['status'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
