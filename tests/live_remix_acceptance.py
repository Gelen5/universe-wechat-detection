"""Manual live-provider check; never imported by pytest."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
from PIL import Image,ImageDraw,ImageFont
from server import workbench

ROOT=Path('/tmp/remix-qa-v2')
for name in ('remix_contract','remix_design','remix_quality','creator_tools'):
    spec=importlib.util.spec_from_file_location('server.'+name,ROOT/(name+'.py'))
    module=importlib.util.module_from_spec(spec);module.__file__='/app/server/'+name+'.py'
    sys.modules['server.'+name]=module;spec.loader.exec_module(module)
from server import creator_tools,remix_contract,remix_quality

font=ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',38)
product=Image.new('RGB',(600,800),'#f7f1df');draw=ImageDraw.Draw(product)
draw.rounded_rectangle((200,150,400,680),radius=45,fill='#225b4a')
draw.rounded_rectangle((230,105,370,180),radius=20,fill='#173e33')
draw.text((220,390),'500 mL',font=font,fill='white')
buffer=io.BytesIO();product.save(buffer,format='PNG')
reference='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
samples=[('product',{'product_reference':reference,'content_ledger':remix_contract.build({'content_type':'product','content_core':{'product_specs':['500 mL'],'facts':['绿色圆柱水瓶、深绿色瓶盖']}},'保留产品形态规格'),
    'visual_contract':{'asset_type':'poster','subject':'绿色水瓶'},'layout':'居中产品、侧边大字、奶油色摄影棚背景',
    'cards':[{'headline':'轻装出发','subtitle':'500 mL','image_brief':'Premium green bottle studio photography, cream backdrop, dynamic light, clear Chinese typography.','content':'绿色水瓶，500 mL'}]}),
    ('tutorial',{'content_ledger':remix_contract.build({'content_type':'tutorial','content_core':{'steps':['打开应用','输入内容','保存作品']}},'三步教程'),
    'visual_contract':{'asset_type':'poster'},'layout':'三个清晰步骤与简洁插图，标题醒目',
    'cards':[{'headline':'三步保存作品','image_brief':'Chinese illustrated tutorial poster, three numbered steps with simple icons, bright cobalt and white.','content':'1 打开应用；2 输入内容；3 保存作品','source_ids':['steps-1','steps-2','steps-3']}]
    })]
with workbench.provider_overrides():
    for name,idea in samples:
        idea['id']='A'; directory=ROOT/name;directory.mkdir(exist_ok=True)
        page=idea['cards'][0]
        result=creator_tools.generate_remix_card(idea,page,1,1,directory)
        report=remix_quality.inspect_image(directory/'remix-01.jpg',idea,{**page,'page_index':1})
        if not report['passed']:
            page={**page,'repair_instruction':report['repair']}
            creator_tools.generate_remix_card(idea,page,1,1,directory)
            report=remix_quality.inspect_image(directory/'remix-01.jpg',idea,{**page,'page_index':1})
        (directory/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'sample':name,'report':report},ensure_ascii=False),flush=True)
