"""Manual provider QA; no customer sessions or wallet mutations."""
import base64
import importlib.util
import json
from pathlib import Path
from server import workbench

root=Path('/tmp/remix-reliability-20261104')
spec=importlib.util.spec_from_file_location('server.creator_tools_qa',root/'creator_tools.py')
module=importlib.util.module_from_spec(spec)
module.__file__='/app/server/creator_tools.py'
spec.loader.exec_module(module)
module.ROOT=Path('/app')
source='data:image/jpeg;base64,'+base64.b64encode((root/'reference.jpg').read_bytes()).decode()
with workbench.provider_overrides(),workbench.provider_overrides(text_model='qa-unavailable-remix-primary'):
    result=module.viral_remix_analysis(source)
print(json.dumps({'model':result.get('vision_model'),'ideas':len(result['ideas']),
    'rows':len((result.get('data_contract') or {}).get('rows',[])),
    'timings':result.get('timings')},ensure_ascii=False),flush=True)
assert result['vision_model']=='gpt-6.1-sol'
assert len(result['ideas'])==3
