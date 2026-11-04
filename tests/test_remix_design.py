import io
from PIL import Image
from server import remix_design


def dataset():
    return dict(title='2025各省离婚数量（万对）',period='2025',unit='万对',
                source_text='用户提供原图',complete=True,
                rows=[dict(label=name,value=value) for name,value in
                      [('河南','29.3'),('广东','26.6'),('四川','26'),('山东','25.1'),('江苏','24.1'),
                       ('河北','20.2'),('安徽','19.1'),('湖南','17.8'),('湖北','15.9'),('浙江','15.3'),
                       ('贵州','15.1'),('云南','13.6'),('辽宁','12.7'),('广西','11.9'),('江西','11.4'),
                       ('黑龙江','11.3'),('新疆','11.2'),('重庆','10.9'),('陕西','10.7'),('福建','10.3'),
                       ('吉林','8.3'),('山西','8.3'),('内蒙古','7.3'),('北京','7'),('甘肃','6.5'),
                       ('上海','6'),('天津','4.4'),('海南','2.4'),('宁夏','2.4'),('青海','1.9'),('西藏','0.8')]])


def test_complete_pagination():
    data=dataset(); pages=remix_design.pages(data)
    assert len(pages)==3
    rebuilt=[r for p in pages for r in data['rows'][p['row_start']:p['row_end']]]
    assert rebuilt==data['rows']
    assert len({p['design_style'] for p in remix_design.plans(data)})==3


def test_render_all_styles(tmp_path):
    data=dataset()
    results=[]
    for style in 'ABC':
        raw=remix_design.render(data,style,remix_design.pages(data)[0],headline=remix_design.plans(data)['ABC'.index(style)]['headline'])
        assert Image.open(io.BytesIO(raw)).size==(1200,1600)
        (tmp_path/f'{style}.png').write_bytes(raw)
        results.append(raw)
    assert len(set(results))==3
