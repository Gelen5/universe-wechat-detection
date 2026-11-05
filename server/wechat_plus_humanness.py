"""Thin wrapper around the Skill's own ``humanness_score.py``.

No scoring logic lives here: the vendored script owns the statistical and
pattern layers and emits the repair plan.  Plus only writes the draft to a
file, runs the script with ``--json --no-tier3`` (no extra model call), and
returns the JSON.  A failing scorer is advisory: it must never block the
article pipeline.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from . import workbench


def diagnose(text: str, *, output_dir: Path | None = None,
             timeout: int = 60) -> dict:
    """Return the Skill's score report, or ``{'available': False, ...}``."""
    text = str(text or '')
    if not text.strip():
        return {'available': False, 'reason': 'empty_text'}
    temporary = None
    try:
        if output_dir is not None:
            directory = Path(output_dir)
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / 'draft_for_score.md'
            path.write_text(text, encoding='utf-8')
        else:
            temporary = tempfile.NamedTemporaryFile(
                'w', encoding='utf-8', suffix='.md', delete=False)
            temporary.write(text)
            temporary.close()
            path = Path(temporary.name)
        script = (Path(workbench.SKILL_DIR) / 'scripts' / 'humanness_score.py').resolve()
        command = [workbench._skill_python(), '-X', 'utf8', str(script),
                   str(path.resolve()), '--json', '--no-tier3']
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding='utf-8',
                errors='replace', cwd=str(Path(workbench.SKILL_DIR).resolve()),
                timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'available': False, 'reason': 'timeout'}
        if result.returncode:
            detail = (result.stderr or result.stdout or '').strip()[-600:]
            return {'available': False,
                    'reason': detail or f'returncode={result.returncode}'}
        try:
            payload = json.loads(result.stdout)
        except ValueError:
            return {'available': False, 'reason': 'invalid_json'}
        if not isinstance(payload, dict):
            return {'available': False, 'reason': 'invalid_payload'}
        payload['available'] = True
        return payload
    finally:
        if temporary is not None:
            Path(temporary.name).unlink(missing_ok=True)
