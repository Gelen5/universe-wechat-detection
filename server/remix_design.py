"""Deterministic, paginated visual design for immutable source datasets."""
import io
import math
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


STYLES = {
    'A': ('一张看完整排行', '#fffdf5', '#ffe500', '#141414', 'bar'),
    'B': ('杂志数据专题', '#f6f0e5', '#ac3d2b', '#252c35', 'editorial'),
    'C': ('分组收藏图卡', '#ecf4ff', '#305bdd', '#152944', 'cards'),
}


def plans(dataset):
    count = len(dataset['rows'])
    topic = re.sub(r'（.*?）|\(.*?\)|\d{4}年?', '', dataset.get('title') or '这份数据').strip()
    headlines = {'A':f'{topic}，谁在前面？','B':f'读懂{topic}，别只看排名','C':f'{topic}：你关心哪一项？'}
    if '离婚数量' in topic: headlines['A']='哪个省份，离婚数量更多？'
    return [dict(id=key, name=style[0], summary=summary,
                 keep='全部名称、数值、单位与原始顺序', change=style[0],
                 why_original='重新设计信息层级与版式，原始数据不改写',
                 page_count=len(pages(dataset,key)), design_style=key,
                 data_contract=dataset, image_brief=summary,
                 headline=headlines[key])
            for key, style, summary in ((k, v, s) for (k,v),s in zip(STYLES.items(),
                ('一张完整长图，强对比大标题和彩色条形，不拆散原图信息。',
                 '杂志式大数字与双栏排版，重点鲜明、适合收藏。',
                 '分组数据卡片与清晰序号，拆页展示，手机轻松阅读。')))]


def pages(dataset, style='C'):
    count=len(dataset['rows'])
    per_page=count if style=='A' else 16 if style=='B' else 12
    return [{'row_start': n, 'row_end': min(n + per_page, count)}
            for n in range(0, count, per_page)]


def render(dataset, style, page, headline=None):
    bg, accent, ink, mode = STYLES.get(style, STYLES['A'])[1:]
    row_count=page['row_end']-page['row_start']
    height=max(1300,570+row_count*54) if style=='A' else 1600
    if style=='B': height=max(1300,570+row_count*67)
    image = Image.new('RGB', (1200,height), bg)
    draw = ImageDraw.Draw(image)
    path = next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc', 'C:/Windows/Fonts/msyh.ttc') if Path(p).exists()), None)
    if not path:
        raise ValueError('中文字体缺失，无法安全排版数据')
    bold_path = next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc','C:/Windows/Fonts/msyhbd.ttc') if Path(p).exists()),path)
    def text(x,y,value,size=30,color=ink,width=1040):
        initial_size=size
        value = str(value)
        while size >= 22:
            font = ImageFont.truetype(bold_path if initial_size >= 60 else path,size)
            if draw.textlength(value,font=font) <= width:
                draw.text((x,y),value,font=font,fill=color)
                return
            size -= 1
        raise ValueError('文字过长，请缩短标题或拆分数据标签')
    start, end = page['row_start'], page['row_end']
    rows = dataset['rows'][start:end]
    draw.rounded_rectangle((60,64,1140,78),radius=7,fill=accent)
    if style=='A': draw.rectangle((40,50,1160,240),fill=accent)
    heading=headline or dataset.get('title') or '数据对比'
    pieces=re.split('[，：]',heading,maxsplit=1)
    if len(pieces)==1 and len(heading)>16: pieces=[heading[:14],heading[14:]]
    if style=='A':
        # Headline is a display mark, not body text: heavy, compressed and optically fitted.
        title=re.sub('[，：\\s]','',heading)
        title_font=ImageFont.truetype(bold_path,160)
        mask=Image.new('L',(max(2400,len(title)*180),240),0)
        mark=ImageDraw.Draw(mask)
        mark.text((10,0),title,font=title_font,fill=255,stroke_width=2)
        bounds=mask.getbbox()
        if not bounds: raise ValueError('标题为空，无法绘制')
        mark_image=mask.crop(bounds).resize((1020,128),Image.Resampling.LANCZOS)
        skewed=mark_image.transform((1050,128),Image.Transform.AFFINE,(1,.15,-19,0,1,0),resample=Image.Resampling.BICUBIC)
        image.paste(ink,(70,80),skewed)
    else:
        for line,value in enumerate(pieces): text(60,100+line*78,value,64)
    text(60,280,dataset.get('title') or ' / '.join(str(dataset.get(k) or '') for k in ('period','unit')),30,ink)
    if style!='A': text(60,335,f'完整数据 · 第 {start+1}—{end} 项 / 共 {len(dataset["rows"])} 项',26)
    numbers=[]
    for row in dataset['rows']:
        raw = str(row['value']).replace(',','')
        numbers.append(float(raw) if re.fullmatch(r'\d+(?:\.\d+)?', raw) else None)
    maximum = max((v for v in numbers if v is not None),default=0)
    if mode == 'bar' and (any(v is None for v in numbers) or maximum <= 0):
        # Ranges, signed numbers and mixed units are not comparable bar lengths.
        mode = 'editorial'
    for i,row in enumerate(rows):
        absolute=start+i
        if mode == 'bar':
            step=(height-560)/max(1,len(rows))
            y=350+i*step
            text(60,y,row['label'],36,width=190)
            value=numbers[absolute]
            if value is not None and maximum > 0:
                length=round(value/maximum*710)
                colors=['#1463b5','#168aca','#1cb4c1','#50b87b','#e2bd20','#e58a29','#c65a80','#8d55ad']
                if length: draw.rounded_rectangle((260,y+5,260+length,y+36),radius=3,fill=colors[absolute%len(colors)])
            else: length=0
            text(280+length,y,row['value'],36,width=180)
        elif mode == 'editorial':
            y=410+i*((height-600)/max(1,len(rows)))
            text(60,y,f'{absolute+1:02d}',26,accent,75)
            text(155,y,row['label'],40,width=510)
            text(830,y-7,row['value'],48,accent,300)
            draw.line((155,y+65,1140,y+65),fill='#d4c8b5',width=1)
        else:
            col=i%2; line=i//2; x=60+col*550
            spacing=(height-620)/max(1,math.ceil(len(rows)/2));y=415+line*spacing
            draw.rounded_rectangle((x,y,x+520,y+spacing-18),radius=18,fill='#ffffff' if mode=='cards' else '#e8dfcf')
            text(x+22,y+15,f'{absolute+1:02d}  {row["label"]}',36,'#152944',470)
            text(x+22,y+58,row['value'],52,accent,470)
    footer=height-170
    draw.line((60,footer,1140,footer),fill=accent,width=2)
    text(60,footer+25,'原图标注来源 · 未独立核实',26)
    source=str(dataset.get('source_text') or '原图未标注来源')
    # Source notes wrap; they must never be silently truncated.
    chunks=[source[i:i+36] for i in range(0,len(source),36)]
    if len(chunks)>2: raise ValueError('来源说明过长，请精简后重试')
    for i,chunk in enumerate(chunks): text(60,footer+65+i*36,chunk,24)
    output=io.BytesIO(); image.save(output,format='PNG')
    return output.getvalue()
