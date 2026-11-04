"""Render immutable chart labels with a model-directed visual composition."""
from copy import deepcopy
import math
from pathlib import Path
import re
from PIL import Image,ImageDraw,ImageFont


def render(document,options=(),previous=None):
    source=document['source'];design=document['design']
    rows=source['rows'];config=deepcopy(design.get('data_layout') or {})
    if previous and 'headline' in options and 'new_direction' not in options:
        old=previous['design'].get('data_layout')
        if old:config={**old,**{key:config[key] for key in ('headline_lines','headline_size','headline_slant') if key in config}}
    regular=next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','C:/Windows/Fonts/msyh.ttc') if Path(p).exists()),None)
    bold=next((p for p in ('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc','C:/Windows/Fonts/msyhbd.ttc') if Path(p).exists()),regular)
    if not regular:raise ValueError('中文字体不可用，请联系管理员')
    def number(key,default,low,high):
        try:return max(low,min(high,int(config.get(key,default))))
        except (ValueError,TypeError):return default
    def color(value,default):return value if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value) else default
    def wrap(text,size,width):
        font=ImageFont.truetype(regular,size);lines=['']
        for char in str(text):
            if ImageDraw.Draw(Image.new('RGB',(1,1))).textlength(lines[-1]+char,font=font)>width:lines.append('')
            lines[-1]+=char
        return lines
    columns=number('columns',1,1,2)
    if config.get('chart_type')=='ranked_cards' and len(rows)>12:columns=2
    per_column=math.ceil(len(rows)/columns)
    top=number('chart_top',490,340,850)
    hero_count=number('hero_count',0,0,3)
    if hero_count:top=max(top,720)
    height=max(number('height',2200,1500,6000),top+per_column*52+260)
    bottom=min(height-240,max(top+per_column*52,number('chart_bottom',height-260,top+100,height-240)))
    bg=color(config.get('background'),'#fff9ef');ink=color(config.get('ink'),'#151515');accent=color(config.get('accent'),'#ffda00')
    image=Image.new('RGB',(1200,height),bg);draw=ImageDraw.Draw(image)
    palette=[color(c,'#1476b8') for c in (config.get('bar_palette') or design.get('palette') or ['#1563b9','#15a6ba'])][:8]
    title_lines=config.get('headline_lines') or [design.get('headline') or source.get('title','数据一览')]
    title_lines=[str(x) for x in title_lines][:3]
    if 'no_title' not in options:
        size=number('headline_size',138,80,160)
        while size>48 and (any(draw.textlength(line,font=ImageFont.truetype(bold,size))>1030 for line in title_lines) or len(title_lines)*(size+14)>top-165-(180 if hero_count else 0)):size-=2
        header_height=top-140-(180 if hero_count else 0)
        header=Image.new('RGBA',(1120,header_height),(0,0,0,0));hd=ImageDraw.Draw(header)
        hd.rounded_rectangle((0,0,1119,header_height-1),radius=12,fill=color(config.get('header_fill'),accent))
        text_top=max(18,(header_height-len(title_lines)*(size+14))//2)
        for index,line in enumerate(title_lines):
            hd.text((34,text_top+index*(size+14)),line,font=ImageFont.truetype(bold,size),fill=ink,stroke_width=1,anchor='lt')
        slant=number('headline_slant',8,0,14)/100
        if slant:header=header.transform(header.size,Image.Transform.AFFINE,(1,slant,-slant*header.height/2,0,1,0),Image.Resampling.BICUBIC)
        image.paste(header,(40,38),header)
    subtitle=str(source.get('title') or '')
    if source.get('period') and str(source['period']) not in subtitle:subtitle=str(source['period'])+' · '+subtitle
    if source.get('unit') and str(source['unit']) not in subtitle:subtitle+=' · '+str(source['unit'])
    lines=wrap(subtitle,30,1090)
    for index,line in enumerate(lines[:2]):draw.text((55,top-100+index*38),line,font=ImageFont.truetype(regular,30),fill=ink)
    if hero_count:
        for index,row in enumerate(rows[:hero_count]):
            card_width=1090/hero_count;x=55+index*card_width;y=top-270
            draw.rounded_rectangle((x,y,x+card_width-14,y+145),radius=12,fill=palette[index%len(palette)])
            draw.text((x+18,y+12),str(row['value']),font=ImageFont.truetype(bold,65),fill='#ffffff',anchor='lt')
            draw.text((x+18,y+95),str(row['label'])+' · '+str(source.get('unit') or ''),font=ImageFont.truetype(regular,28),fill='#ffffff',anchor='lt')
    values=[]
    for row in rows:
        try:values.append(float(str(row['value']).replace(',','')))
        except ValueError:raise ValueError('数据值不是可绘制的数字，请确认原图')
    if any(not math.isfinite(value) or value<0 for value in values):raise ValueError('数据需使用可比较的非负数值')
    maximum=max(values) or 1
    step=(bottom-top)/per_column;column_width=1090/columns
    font_size=34
    for index,(row,value) in enumerate(zip(rows,values)):
        col=index//per_column;line=index%per_column;x=55+col*column_width;y=top+line*step
        label=str(row['label']);raw=str(row['value'])
        uncertain_value=any(label in str(note) for note in source.get('uncertain',[]))
        label_width=max(draw.textlength(str(r['label']),font=ImageFont.truetype(regular,font_size)) for r in rows)+18
        available=column_width-label_width-115-(30 if columns==2 else 0)
        start=x+label_width+38;available-=38;length=max(3,available*value/maximum)
        draw.text((x,y+5),f'{index+1:02}',font=ImageFont.truetype(regular,21),fill=ink)
        draw.text((x+38,y),label,font=ImageFont.truetype(bold if index==0 else regular,font_size),fill=ink)
        mode=config.get('chart_type','bars')
        if mode=='ranked_cards':
            draw.line((start,y+step-5,x+column_width-25,y+step-5),fill=palette[index%len(palette)],width=2)
            position=x+column_width-100
        elif mode=='dots':
            draw.line((start,y+step/2,start+available,y+step/2),fill=accent,width=2)
            draw.ellipse((start+length-8,y+step/2-8,start+length+8,y+step/2+8),fill=palette[index%len(palette)])
            position=start+length+14
        elif uncertain_value:
            draw.rounded_rectangle((start,y+9,start+24,y+step-12),radius=4,outline=palette[index%len(palette)],width=2)
            position=start+38
        else:
            draw.rounded_rectangle((start,y+9,start+length,y+step-12),radius=4,fill=palette[index%len(palette)])
            position=start+length+12
        draw.text((position,y),raw,font=ImageFont.truetype(bold if index==0 else regular,font_size),fill=ink)
        if uncertain_value:
            warning_x=position+draw.textlength(raw,font=ImageFont.truetype(regular,font_size))+7
            draw.text((warning_x,y),'*',font=ImageFont.truetype(bold,24),fill=ink)
    footer='原图标注来源（未独立核实）：'+str(source.get('source_text') or '用户提供原图')
    notes=[str(note) for note in source.get('uncertain',[]) if not ('来源' in str(note) and '未独立核实' in str(note)) and not ('裁切' in str(note) and '裁切' in footer)]
    facts=[str(fact) for fact in source.get('facts',[]) if any(word in str(fact) for word in ('暂无','不含','范围','口径','缺失')) and not ('港澳台' in str(fact) and '港澳台' in footer)]
    footer_lines=wrap(footer,23,1080)+[line for note in facts+notes for line in wrap(note,23,1080)]
    # Enlarge the one output rather than clipping a source note or deleting a row.
    required=bottom+55+len(footer_lines)*34+45
    if required>height:
        extended=Image.new('RGB',(1200,int(required)),bg);extended.paste(image,(0,0));image=extended;draw=ImageDraw.Draw(image)
    draw.line((55,bottom+30,1145,bottom+30),fill=accent,width=3)
    for index,line in enumerate(footer_lines):draw.text((55,bottom+55+index*34),line,font=ImageFont.truetype(regular,23),fill=ink)
    design['data_layout']={**config,'height':image.height,'chart_top':top,'chart_bottom':bottom,'columns':columns}
    return image
