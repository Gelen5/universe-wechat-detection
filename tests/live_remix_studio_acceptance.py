"""Manual paid-provider acceptance, isolated from customer jobs and wallets."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
from server import workbench, image_provider, creator_tools
from PIL import Image
import io

root=Path('/tmp/remix-studio-qa-20261104')
spec=importlib.util.spec_from_file_location('server.remix_studio',root/'remix_studio.py')
studio=importlib.util.module_from_spec(spec)
sys.modules['server.remix_studio']=studio
spec.loader.exec_module(studio)
spec=importlib.util.spec_from_file_location('server.remix_studio_data',root/'remix_studio_data.py')
data_renderer=importlib.util.module_from_spec(spec);spec.loader.exec_module(data_renderer)
reference='data:image/jpeg;base64,'+base64.b64encode((root/'reference.jpg').read_bytes()).decode()
with workbench.provider_overrides():
    design=json.loads((root/'design.json').read_text()) if '--resume' in sys.argv else studio.plan(reference,'保留完整数据，重新设计一张比原图更抓眼球的社交图片',['stronger','facts'])
    (root/'design.json').write_text(json.dumps(design,ensure_ascii=False),encoding='utf-8')
    print('Source understood; generating',flush=True)
    repair=''
    output=root/'created.jpg'
    for attempt in range(2):
        data_renderer.render(design,['stronger','facts']).save(output,quality=95)
        report=studio.inspect(reference,output,design,'更抓眼球，完整数据',['stronger','facts'])
        (root/'created-report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'attempt':attempt,'report':report},ensure_ascii=False),flush=True)
        if report['passed']:break
        repair=report['repair']
        design=studio.plan(reference,'更抓眼球，完整数据；修复：'+repair,['stronger','facts'],{'source':design['source'],'design':design['design'],'_repair':True})
    if not report['passed']:raise RuntimeError('Create acceptance failed')
    previous={'source':design['source'],'design':design['design']}
    revised=studio.plan(reference,'只修改标题排版，其他数据和配色保留',['headline'],previous)
    target=root/'revised.jpg'
    data_renderer.render(revised,['headline'],previous).save(target,quality=95)
    report=studio.inspect(reference,target,revised,'只修改标题排版，其他数据和配色保留',['headline'],True,studio._url(output))
    (root/'revised-report.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'revision':report},ensure_ascii=False),flush=True)
    if not report['passed']:raise RuntimeError('Revision acceptance failed')
