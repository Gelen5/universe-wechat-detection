"""Manual publication copy acceptance against real generated dataset pages."""
import importlib.util
import json
from pathlib import Path
import sys
from server import workbench
root=Path('/tmp/remix-qa-v2')
for name in ('editorial_quality','creator_tools'):
    spec=importlib.util.spec_from_file_location('server.'+name,root/(name+'.py'))
    module=importlib.util.module_from_spec(spec);module.__file__='/app/server/'+name+'.py'
    sys.modules['server.'+name]=module;spec.loader.exec_module(module)
from server import creator_tools
with workbench.provider_overrides():
    copy=creator_tools.publication_copy_from_files([root/f'A-{n}.png' for n in range(1,4)])
    (root/'publication.json').write_text(json.dumps(copy,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(copy,ensure_ascii=False),flush=True)
