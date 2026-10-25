"""One file-backed rule source for the Web adapter and native Skill host requests."""
from __future__ import annotations

import hashlib
from pathlib import Path

REFERENCES = {
    'strategy': 'human-writing-strategy.md',
    'draft': 'human-writing-draft.md',
    'review': 'human-writing-review.md',
}


def load(node: str):
    name = REFERENCES.get(node)
    if not name:
        return '', []
    path = Path(__file__).resolve().parent / 'references' / name
    raw = path.read_bytes()
    return raw.decode('utf-8'), [{
        'file': f'skill-extensions/weChat-autoCreate/references/{name}',
        'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
    }]


def native_request(request: dict, node: str) -> dict:
    text, manifest = load(node)
    if not text:
        return request
    request['read'] = [*request['read'], *[row['path'] for row in manifest]]
    request['rules'] = [*request['rules'], text]
    request['rule_manifest'] = manifest
    if node == 'strategy':
        request['output_contract']['writing_strategy'] = (
            'object with article_type, expression_mode, available_materials, '
            'material_gaps, forbidden_additions; do not invent evidence'
        )
    return request
