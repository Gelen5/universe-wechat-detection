"""Deterministic, paginated visual design for immutable source datasets."""
import io
import math
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


STYLES = {
    'A': ('醒目完整排行', '#111e38', '#ffe44f', '#ffffff', 'bar'),
    'B': ('杂志数据专题', '#f6f0e5', '#ac3d2b', '#252c35', 'editorial'),
    'C': ('分组收藏图卡', '#ecf4ff', '#305bdd', '#152944', 'cards'),
}


def plans(dataset):
    count = len(dataset['rows'])
    return [dict(id=key, name=style[0], summary=summary,
                 keep='全部名称、数值、单位与原始顺序', change=style[0],
                 why_original='重新设计信息层级与版式，原始数据不改写',
                 page_count=math.ceil(count / 12), design_style=key,
                 data_contract=dataset, image_brief=summary,
                 headline=dataset.get('title') or '数据对比')
            for key, style, summary in ((k, v, s) for (k,v),s in zip(STYLES.items(),
                ('高对比标题与精确比例条形，完整标明每项数据。',
                 '杂志式大数字与双栏排版，重点鲜明、适合收藏。',
                 '分组数据卡片与清晰序号，拆页展示，手机轻松阅读。')))]


def pages(dataset):
    return [{'row_start': n, 'row_end': min(n + 12, len(dataset['rows']))}
            for n in range(0, len(dataset['rows']), 12)]


def render(dataset, style, page):
    bg, accent, ink, mode = STYLES.get(style, STYLES['A'])[1:]
    image = Image.new('RGB', (1200,1600), bg)
    draw = ImageDraw.Draw(image)
    path = next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc', 'C:/Windows/Fonts/msyh.ttc') if Path(p).exists()), None)
    if not path:
        raise ValueError('中文字体缺失，无法安全排版数据')
    def text(x,y,value,size=30,color=ink,width=1040):
        value = str(value)
        while size >= 22:
            font = ImageFont.truetype(path,size)
            if draw.textlength(value,font=font) <= width:
                draw.text((x,y),value,font=font,fill=color)
                return
            size -= 1
        raise ValueError('文字过长，请缩短标题或拆分数据标签')
    start, end = page['row_start'], page['row_end']
    rows = dataset['rows'][start:end]
    draw.rounded_rectangle((60,64,1140,78),radius=7,fill=accent)
    text(60,112,dataset.get('title') or '数据对比',64)
    text(60,208,' / '.join(str(dataset.get(k) or '') for k in ('period','unit')),30,accent)
    text(60,270,f'完整数据 · 第 {start+1}—{end} 项 / 共 {len(dataset["rows"])} 项',26)
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
            y=370+i*83
            text(60,y,str(absolute+1).zfill(2),26,accent,70)
            text(130,y,row['label'],30,width=220)
            value=numbers[absolute]
            if value is not None and maximum > 0:
                length=round(value/maximum*560)
                if length: draw.rounded_rectangle((370,y+5,370+length,y+36),radius=6,fill=accent if absolute < 3 else '#5296cf')
            text(960,y,row['value'],30,width=180)
        elif mode == 'editorial':
            y=360+i*83
            text(60,y,f'{absolute+1:02d}',26,accent,75)
            text(155,y,row['label'],34,width=510)
            text(830,y-7,row['value'],48,accent,300)
            draw.line((155,y+65,1140,y+65),fill='#d4c8b5',width=1)
        else:
            col=i%2; line=i//2; x=60+col*550; y=365+line*158
            draw.rounded_rectangle((x,y,x+520,y+140),radius=18,fill='#ffffff' if mode=='cards' else '#e8dfcf')
            text(x+22,y+15,f'{absolute+1:02d}  {row["label"]}',28,'#152944',470)
            text(x+22,y+58,row['value'],52,accent,470)
    draw.line((60,1390,1140,1390),fill=accent,width=2)
    text(60,1420,'原图标注来源 · 未独立核实',26)
    source=str(dataset.get('source_text') or '原图未标注来源')
    # Source notes wrap; they must never be silently truncated.
    chunks=[source[i:i+36] for i in range(0,len(source),36)]
    if len(chunks)>2: raise ValueError('来源说明过长，请精简后重试')
    for i,chunk in enumerate(chunks): text(60,1460+i*40,chunk,24)
    output=io.BytesIO(); image.save(output,format='PNG')
    return output.getvalue()
