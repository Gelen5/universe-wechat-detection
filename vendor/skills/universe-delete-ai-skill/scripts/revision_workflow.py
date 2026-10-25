"""Execute a finite queue of editor-authored plans/reviews with automatic rollback.

The host Skill creates candidates; this runner never invents a semantic review.
"""
import argparse
import json
from pathlib import Path
try:
    from .preservation import apply_plan, build_manifest, digest, gate, read, validate_text
except ImportError:
    from preservation import apply_plan, build_manifest, digest, gate, read, validate_text


def validate_feedback(result, expected_sha):
    """Validate user-imported results without claiming a specific detector schema."""
    if result is None:
        return None
    if not isinstance(result, dict) or result.get('text_sha256') != expected_sha:
        raise ValueError('detector_feedback_not_bound_to_text')
    if result.get('risk') is None:
        raise ValueError('detector_feedback_missing_risk')
    value = result['risk']
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError('detector_feedback_invalid_risk')
    if not result.get('checked_at') or not result.get('source') or not result.get('comparison_id'):
        raise ValueError('detector_feedback_missing_provenance')
    return result


def run(original, manifest, rounds, *, mode='minimal', baseline_feedback=None,
        max_rounds=3, target=0., min_improvement=.01):
    if type(max_rounds) is not int or not 1 <= max_rounds <= 3 or not 0 <= target <= 1 or not 0 <= min_improvement <= 1:
        raise ValueError('invalid_iteration_limits')
    if not isinstance(rounds, list):
        raise ValueError('rounds_must_be_list')
    validate_text(original)
    if manifest != build_manifest(original, manifest.get('entities', [])):
        raise ValueError('invalid_manifest')
    current, best, logs = original, original, []
    baseline = validate_feedback(baseline_feedback, digest(original))
    best_risk = baseline['risk'] if baseline else None
    unchanged = 0
    stopped = 'round_limit' if rounds else 'no_revision_requested'
    for n, item in enumerate(rounds[:max_rounds], 1):
        try:
            plan = item['plan']
            candidate = apply_plan(current, plan)
        except (ValueError, KeyError, TypeError, AttributeError):
            logs.append({'version': n, 'semantic_check': 'FAIL', 'decision': 'rollback', 'reason': 'invalid_plan'})
            stopped = 'invalid_plan'
            break
        report = gate(original, candidate, manifest, plan, item.get('review'), mode, current)
        review = item.get('review') if isinstance(item.get('review'), dict) else {}
        dimensions = review.get('dimensions') if isinstance(review.get('dimensions'), dict) else {}
        readability = dimensions.get('readability') if isinstance(dimensions.get('readability'), dict) else {}
        entry = {'version': n, 'change_type': plan.get('change_type'), 'text_sha256': digest(candidate),
                 'semantic_check': report['status'], 'facts_check': report['facts_check'],
                 'readability_check': readability.get('status', 'REVIEW_REQUIRED'),
                 'change_ratio': report['diff']['ratios'] if report['diff'] else None,
                 'changed_sentences': report['diff']['counts']['sentences']['changed'] if report['diff'] else None,
                 'errors': report['errors'], 'pending': report['pending'],
                 'detector_feedback': None}
        logs.append(entry)
        if report['status'] != 'PASS':
            entry['decision'] = 'rollback'
            stopped = 'preservation_or_readability_gate'
            break
        feedback = item.get('detector_feedback')
        if feedback is None:
            best = candidate
            entry['decision'] = 'accepted_offline_not_detector_validated'
            stopped = 'detector_feedback_not_provided'
            break  # No black-box feedback: do not keep rewriting blindly.
        try:
            feedback = validate_feedback(feedback, digest(candidate))
            if baseline is None:
                raise ValueError('baseline_feedback_required_for_comparison')
            if feedback['comparison_id'] != baseline['comparison_id'] or feedback['source'] != baseline['source']:
                raise ValueError('detector_feedback_not_comparable')
            if best_risk <= target:
                stopped = 'target_already_met'
                entry['decision'] = 'keep_original'
                break
            entry['detector_feedback'] = feedback
        except ValueError as exc:
            entry['decision'] = 'rollback_invalid_detector_feedback'
            entry['detector_error'] = str(exc)
            stopped = 'invalid_detector_feedback'
            break
        improvement = best_risk - feedback['risk']
        if improvement >= min_improvement and improvement > 0:
            best, current, best_risk, unchanged = candidate, candidate, feedback['risk'], 0
            entry['decision'] = 'accepted'
        else:
            unchanged += 1
            entry['decision'] = 'rollback_no_significant_improvement'
        if best_risk <= target or unchanged >= 2:
            stopped = 'target_met' if best_risk <= target else 'two_rounds_no_improvement'
            break
    return {'final_text': best, 'original_sha256': digest(original), 'final_sha256': digest(best),
            'original_chars': len(original), 'final_chars': len(best), 'baseline': baseline,
            'rounds': logs, 'stop_reason': stopped,
            'rollback_count': sum(x.get('decision', '').startswith('rollback') for x in logs)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('original', type=Path)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--rounds', type=Path, required=True, help='JSON array of plan/review objects')
    p.add_argument('--output', type=Path, required=True, help='New output file; never overwrites an existing file')
    p.add_argument('--mode', choices=['minimal', 'standard', 'deep'], default='minimal')
    p.add_argument('--baseline-feedback', type=Path,
                   help='Optional user-recorded detector JSON; this script never uploads text')
    a = p.parse_args()
    if a.output.exists():
        p.error('output_must_not_exist')
    try:
        baseline = json.loads(read(a.baseline_feedback)) if a.baseline_feedback else None
        result = run(read(a.original), json.loads(read(a.manifest)),
                     json.loads(read(a.rounds)), mode=a.mode,
                     baseline_feedback=baseline)
        with a.output.open('x', encoding='utf-8', newline='') as stream:
            stream.write(result.pop('final_text'))
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'status': 'not_executed', 'reason': 'input_or_configuration_error'}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['rollback_count'] else 0

if __name__ == '__main__':
    raise SystemExit(main())
