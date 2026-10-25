"""Evaluate paired local artifacts. Unknown detector data never becomes zero."""
import argparse
import json
import statistics
from pathlib import Path
try:
    from .preservation import read
    from .revision_workflow import run
except ImportError:
    from preservation import read
    from revision_workflow import run


def evaluate(directory):
    items, improvements = [], []
    for metadata_path in sorted(directory.glob('*/metadata.json')):
        root = metadata_path.parent
        metadata = json.loads(read(metadata_path))
        original = read(root / 'original.md')
        manifest = json.loads(read(root / 'manifest.json'))
        rounds = json.loads(read(root / 'rounds.json'))
        result = run(original, manifest, rounds)
        artifact_matches = read(root / 'revision.md') == result['final_text']
        passed = bool(result['rounds']) and result['rounds'][-1]['semantic_check'] == 'PASS' and artifact_matches
        before, after = metadata.get('detector_original'), metadata.get('detector_revision')
        # User-imported evidence must match text hashes and the same manual comparison session.
        comparable = (passed and isinstance(before, dict) and isinstance(after, dict)
                      and before.get('text_sha256') == result['original_sha256']
                      and after.get('text_sha256') == result['final_sha256']
                      and before.get('comparison_id') and before.get('comparison_id') == after.get('comparison_id')
                      and before.get('source') and before.get('source') == after.get('source')
                      and before.get('checked_at') and after.get('checked_at'))
        delta = None
        if comparable:
            try:
                before_risk, after_risk = before['risk'], after['risk']
                if type(before_risk) not in (int, float) or type(after_risk) not in (int, float):
                    raise ValueError('invalid_detector_risk')
                delta = before_risk - after_risk
                if not -1 <= delta <= 1:
                    raise ValueError('invalid_detector_delta')
                improvements.append(delta)
            except (KeyError, TypeError, ValueError):
                comparable = False
                delta = None
        items.append({'case': root.name, 'kind': metadata.get('kind'), 'local_gate_pass': passed,
                      'saved_revision_matches_selected': artifact_matches,
                      'rollback_count': result['rollback_count'], 'rounds': result['rounds'],
                      'detector_comparable': bool(comparable), 'improvement': delta,
                      'positive': bool(passed and comparable and delta is not None and delta > 0
                                       and metadata.get('human_confirmed_meaning') is True
                                       and metadata.get('fact_damage') is False)})
    n = len(improvements)
    return {'cases': len(items), 'items': items, 'local_pass': sum(x['local_gate_pass'] for x in items),
            'rollback_count': sum(x['rollback_count'] for x in items),
            'detector_pairs': n, 'improved': sum(x > 0 for x in improvements),
            'mean_improvement': statistics.mean(improvements) if n else None,
            'median_improvement': statistics.median(improvements) if n else None,
            'variance': statistics.pvariance(improvements) if n else None,
            'improvement_rate': sum(x > 0 for x in improvements) / n if n else None,
            'positives': sum(x['positive'] for x in items),
            'note': 'Local fidelity audit is not an external fact check or detector effectiveness result.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    result = evaluate(a.directory)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        with a.output.open('x', encoding='utf-8') as stream:
            stream.write(payload)
    print(payload)
    return 0 if result['cases'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
