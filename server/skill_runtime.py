"""File-backed Skill context and deterministic script execution; no provider secrets."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.py$")


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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


def length_issue(article, requirements):
    ranges = list(re.finditer(r'(\d{2,5})\s*[—–\-~～至到]\s*(\d{2,5})\s*字', requirements))
    if not ranges:
        return None
    low, high = map(int, ranges[-1].groups())
    count = len(re.findall(r'[\u4e00-\u9fff]', article))
    return f'正文汉字数 {count}，要求 {low}—{high} 字' if not low <= count <= high else None
