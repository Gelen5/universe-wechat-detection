"""File-backed Skill context and deterministic script execution; no provider secrets."""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.py$")

# An explicit range wins over a single target; the target accepts a tolerance
# band because a requested "1200字" never lands on exactly 1200 characters.
_LENGTH_RANGE = re.compile(r'(\d{2,5})\s*[—–\-~～至到]\s*(\d{2,5})\s*字')
_LENGTH_TARGET = re.compile(
    r'(不超过|最多|不多于|不少于|至少|不低于)?\s*约?\s*(\d{2,5})\s*个?\s*字\s*'
    r'(左右|上下|出头|以内|以下|以上)?')
DEFAULT_LENGTH_TOLERANCE = 0.2


def _length_tolerance() -> float:
    try:
        value = float(os.getenv('WECHAT_LENGTH_TOLERANCE', str(DEFAULT_LENGTH_TOLERANCE)))
    except (TypeError, ValueError):
        return DEFAULT_LENGTH_TOLERANCE
    return value if 0 <= value <= 0.5 else DEFAULT_LENGTH_TOLERANCE


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def node_rules(node):
    """Read the same node rules used by the vendored Skill's host contract."""
    path = Path(__file__).resolve().parents[1] / 'vendor/skill-extensions/weChat-autoCreate/node_rules.py'
    spec = importlib.util.spec_from_file_location('wechat_node_rules', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load(node)


def context(root: Path, references=()):
    documents, manifest = [], []
    for name in ('SKILL.md', *references):
        path = root / name
        raw = path.read_bytes()
        documents.append(f'\n--- {name} ---\n' + raw.decode('utf-8'))
        manifest.append({'file':name, 'sha256':hashlib.sha256(raw).hexdigest()})
    return '\n'.join(documents), manifest


def python_for(root: Path) -> str:
    """Run Skill-owned scripts with the Skill's dependency environment."""
    candidates = (
        root / '.venv' / 'Scripts' / 'python.exe',
        root / '.venv' / 'bin' / 'python',
        root / 'venv' / 'Scripts' / 'python.exe',
        root / 'venv' / 'bin' / 'python',
    )
    return str(next((path for path in candidates if path.exists()), Path(sys.executable)))


def script(root: Path, name: str, *args):
    root = root.resolve()
    if not SCRIPT_NAME.fullmatch(name) or Path(name).name != name:
        raise ValueError(f'非法 Skill 脚本名：{name}')
    scripts_root = (root / 'scripts').resolve()
    target = (scripts_root / name).resolve()
    if target.parent != scripts_root or not target.is_file():
        raise ValueError(f'Skill 脚本不存在或不在受控目录中：{name}')
    result = subprocess.run([python_for(root), '-X', 'utf8', str(target),
                             *map(str, args), '--json'], capture_output=True,
                            encoding='utf-8', errors='strict', timeout=60)
    if result.returncode:
        raise RuntimeError(f'{name} 执行失败：{result.stderr[-500:]}')
    return json.loads(result.stdout)


def brief(session):
    original = session.get('brief') or next((m['content'] for m in session.get('conversation', [])
                                             if m.get('role') == 'user'), session.get('topic', ''))
    changes = [m['content'] for m in session.get('conversation', []) if m.get('role') == 'user']
    return str(original) + '\n后续要求（冲突时以最新明确要求为准）：\n' + '\n'.join(changes[1:])


def length_bounds(requirements):
    """Return ``(low, high, description)`` for the requested body length.

    An explicit range (``800—1000字``) is exact. A single target (``1200字``,
    ``1200 字左右``) becomes a tolerance band. Open-ended forms
    (``不超过800字``, ``至少1500字``) leave one side unbounded; ``high`` is
    ``None`` when only a floor applies.
    """
    ranges = list(_LENGTH_RANGE.finditer(requirements or ''))
    if ranges:
        low, high = map(int, ranges[-1].groups())
        return low, high, f'要求 {low}—{high} 字'
    matches = list(_LENGTH_TARGET.finditer(requirements or ''))
    if not matches:
        return None
    match = matches[-1]
    prefix, raw, suffix = match.group(1) or '', int(match.group(2)), match.group(3) or ''
    if prefix in ('不超过', '最多', '不多于') or suffix in ('以内', '以下'):
        return 1, raw, f'要求不超过 {raw} 字'
    if prefix in ('不少于', '至少', '不低于') or suffix == '以上':
        return raw, None, f'要求不少于 {raw} 字'
    tolerance = _length_tolerance()
    low = max(1, round(raw * (1 - tolerance)))
    high = round(raw * (1 + tolerance))
    return low, high, f'目标 {raw} 字（可接受 {low}—{high} 字）'


def length_issue(article, requirements):
    """Describe how the body misses the requested length, or ``None`` when it fits."""
    bounds = length_bounds(requirements)
    if not bounds:
        return None
    low, high, description = bounds
    count = len(re.findall(r'[\u4e00-\u9fff]', article))
    if count < low or (high is not None and count > high):
        return f'正文汉字数 {count}，{description}'
    return None
