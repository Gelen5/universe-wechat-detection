from copy import deepcopy
from PIL import ImageDraw
from server.remix_studio_data import render


def test_full_data_and_long_source_are_drawn_once_without_clipping(monkeypatch):
    rows=[{'label':f'地区{index}','value':str(31-index)} for index in range(31)]
    document={'source':{'rows':rows,'title':'各地数量','period':'2025','unit':'万对',
        'source_text':'原图来源'+('较长来源说明'*60),'uncertain':['来源未独立核实']},
        'design':{'headline':'哪些地方更多？','data_layout':{'height':1500,'chart_top':500,'chart_bottom':1200}}}
    texts=[];original=ImageDraw.ImageDraw.text
    def draw(self,xy,text,*args,**kwargs):
        texts.append((xy,str(text),self._image.size))
        return original(self,xy,text,*args,**kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw,'text',draw)
    image=render(document)
    assert image.height>2200
    for row in rows:
        assert [text for xy,text,size in texts].count(row['label'])==1
        assert row['value'] in [text for xy,text,size in texts]
    assert all(0<=xy[1]<size[1]-20 for xy,text,size in texts)


def test_headline_revision_preserves_chart_design_and_source():
    old={'source':{'rows':[{'label':'甲','value':'2'},{'label':'乙','value':'1'}]},
         'design':{'data_layout':{'background':'#ffffff','chart_top':500,'chart_bottom':1200,'columns':1,'headline_lines':['旧标题']}}}
    updated=deepcopy(old);updated['design']['data_layout'].update(background='#000000',chart_top=700,headline_lines=['新标题'])
    render(updated,['headline'],old)
    assert updated['design']['data_layout']['background']=='#ffffff'
    assert updated['design']['data_layout']['chart_top']==500
    assert updated['design']['data_layout']['headline_lines']==['新标题']
    assert updated['source']==old['source']
