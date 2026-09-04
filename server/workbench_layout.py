"""Compose immutable article text with the installed Skill's component styles."""
import re
from bs4 import BeautifulSoup


def compose(fragment, root, plan):
    source = (root / 'references/components.md').read_text(encoding='utf-8')
    def example(number):
        part = source.split(f'### 组件{number}：',1)[1].split('\n### ',1)[0]
        code = re.search(r'```html[^\n]*\n(.*?)```',part,re.S)
        if not code:
            raise ValueError(f'Skill组件{number}缺少HTML示例')
        return BeautifulSoup(code.group(1),'html.parser')
    container, heading, body, quote, media = (example(i) for i in (1,3,4,8,10))
    soup = BeautifulSoup(fragment,'html.parser')
    # Do not allow article-supplied scripts, events, or active embedded content.
    for node in soup.select('script,style,iframe,object,embed,form,input,button,link,meta'):
        node.decompose()
    for node in soup.find_all(True):
        for key in list(node.attrs):
            if key in ('class','id') or key.startswith(('on','data-')):
                del node[key]
        if node.name == 'a' and not str(node.get('href','')).startswith(('https://','http://')):
            node.attrs.pop('href',None)
    wrapper = soup.new_tag('section')
    wrapper['style'] = container.section['style']
    for node in list(soup.contents):
        wrapper.append(node.extract())
    soup.append(wrapper)
    for node in soup.find_all('p'):
        node['style'] = body.p['style']
    for node in soup.find_all(['h2','h3']):
        node['style'] = heading.h2['style'] + ';margin:32px 0 16px;'
    for node in soup.find_all('h1'):
        node['style'] = 'font-size:22px;line-height:1.4;color:#1D1D1F;margin:16px 0 24px;font-weight:bold;'
        text = node.get_text()
        # Preserve the approved title and break only at an existing semantic
        # boundary, avoiding the one-character tail on narrow mobile screens.
        if 16 <= len(text) <= 32 and '，' in text:
            left,right = text.split('，',1)
            if len(left)>=3 and len(right)>=5:
                node.clear()
                node.append(left+'，')
                node.append(soup.new_tag('br'))
                node.append(right)
    emphasis = str(plan.get('emphasis') or '').strip()
    for node in soup.find_all('p'):
        if emphasis and node.get_text(strip=True) == emphasis:
            box = soup.new_tag('section')
            box['style'] = quote.section['style']
            node.wrap(box)
            node['style'] = quote.p['style']
            break
    for node in soup.find_all('img'):
        if not str(node.get('src','')).startswith('data:image/'):
            raise ValueError('排版图片必须先下载并内嵌')
        node['style'] = media.img['style'] + ';height:auto;max-width:100%;'
    for node in soup.find_all('p'):
        if node.get_text().startswith('图注：'):
            node['style'] = media.p['style']
    return str(soup)
