"""Read-only repository map and local entrypoint-link check."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def link_audit(text, root):
    links = re.findall(r'\]\(([^)]+)\)', text)
    paths = re.findall(r'(?<![\w/])scripts/[\w-]+\.py', text)
    paths += re.findall(r'`((?:references|approved-works)/[^`]+\.(?:md|jsonl))`', text)
    local = sorted(set(x for x in links + paths if not x.startswith(('https:', 'http:', '#'))))
    return {'checked': local, 'missing': [x for x in local if not (root / x.split('#')[0]).is_file()]}


def audit(root, baseline=None):
    tracked = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'ls-files', '-z'], cwd=root).decode().split('\0')
    files = []
    for name in filter(None, tracked):
        path = root / name
        # During a refactor, the index can still name a path already deleted
        # from the working tree. Report it instead of crashing the audit.
        if not path.is_file():
            files.append({'path': name, 'status': 'missing_from_worktree'})
            continue
        raw = path.read_bytes()
        files.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    result = {'tracked_files': files, 'entrypoint': link_audit((root/'SKILL.md').read_text(encoding='utf-8'), root)}
    if baseline:
        old = subprocess.check_output(['git', 'show', baseline + ':SKILL.md'], cwd=root).decode('utf-8')
        result['baseline_commit'] = baseline
        result['baseline_entrypoint'] = link_audit(old, root)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline')
    a = p.parse_args()
    result = audit(Path(__file__).resolve().parents[1], a.baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['entrypoint']['missing'] else 0

if __name__ == '__main__':
    raise SystemExit(main())
