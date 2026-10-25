"""Build an exact original-bound manifest; supply entity and terminology inventory."""
import argparse
import json
from pathlib import Path
try:
    from .preservation import build_manifest, read
except ImportError:
    from preservation import build_manifest, read

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('original', type=Path)
    p.add_argument('--entity', action='append', default=[])
    a = p.parse_args()
    print(json.dumps(build_manifest(read(a.original), a.entity), ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
