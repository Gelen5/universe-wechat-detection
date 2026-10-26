/* One UTF-8 rich-text path for every publisher copy entry. No source-code copy. */
(() => {
  const allowed = new Set('SECTION DIV P SPAN H1 H2 H3 H4 H5 H6 STRONG B EM I U S DEL BR HR BLOCKQUOTE UL OL LI A IMG TABLE THEAD TBODY TFOOT TR TD TH PRE CODE'.split(' '));
  function fragment(item) {
    const source = item?.content_json?.article_html;
    const doc = new DOMParser().parseFromString(source || item?.content || '', 'text/html');
    const article = source ? doc.body : doc.querySelector('#article-content, #articleContent');
    if (!article) throw new Error('未找到完整文章正文，请重新排版后复制');
    const clone = article.cloneNode(true);
    for (const el of clone.querySelectorAll('*')) {
      if (!allowed.has(el.tagName)) throw new Error('正文包含不支持的标签，请重新排版');
      for (const attr of [...el.attributes]) {
        if (attr.name.startsWith('on')) throw new Error('正文包含不安全的属性');
        if (!['style','src','href','alt','title','leaf','colspan','rowspan','start','type'].includes(attr.name)) el.removeAttribute(attr.name);
      }
      const style = el.getAttribute('style') || '';
      if (/url\s*\(|expression\s*\(|@|position\s*:|display\s*:\s*grid|(?:animation|transform|float|z-index)\s*:/i.test(style)) throw new Error('正文包含不可移植的样式，请重新排版');
      if (el.tagName === 'A' && !/^https?:\/\//i.test(el.getAttribute('href') || '')) throw new Error('正文存在异常链接');
      if (el.tagName === 'IMG') {
        const match = /^data:image\/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)$/.exec(el.getAttribute('src') || '');
        if (!match) throw new Error('图片尚未内嵌，不能完整复制，请重新排版');
        let bytes;
        try { bytes = atob(match[2].replace(/\s/g, '')); } catch { throw new Error('图片编码异常，请重新排版'); }
        if (bytes.length > 980 * 1024) throw new Error('图片超过复制大小限制，请压缩后重新排版');
        if (match[1] === 'png' ? !bytes.startsWith('\x89PNG\r\n\x1a\n') : !bytes.startsWith('\xff\xd8\xff')) throw new Error('图片内容异常，未复制');
      }
    }
    if (!clone.textContent.trim() || clone.textContent.includes('\ufffd')) throw new Error('正文为空或包含异常编码，未复制');
    return clone.innerHTML;
  }
  function plain(html) {
    const source = html.replace(/<br\s*\/?\s*>/gi, '\n').replace(/<\/(p|h[1-6]|li|blockquote|tr|pre|section)>/gi, '</$1>\n');
    return new DOMParser().parseFromString(source, 'text/html').body.textContent.trim();
  }
  async function copy(item) {
    const html = fragment(item);
    const text = plain(html);
    if (navigator.clipboard?.write && window.ClipboardItem) {
      try {
        await navigator.clipboard.write([new ClipboardItem({
          'text/html': new Blob([html], {type:'text/html;charset=utf-8'}),
          'text/plain': new Blob([text], {type:'text/plain;charset=utf-8'}),
        })]);
        return;
      } catch { /* Fall back to a selected rich-text node, never plain source. */ }
    }
    const active = document.activeElement;
    const selection = getSelection();
    const ranges = Array.from({length:selection.rangeCount}, (_,i)=>selection.getRangeAt(i).cloneRange());
    const node = document.createElement('div');
    node.contentEditable = 'true'; node.setAttribute('aria-hidden','true');
    node.style.cssText = 'position:fixed;left:-100000px;top:0;width:640px;background:white;';
    node.innerHTML = html; document.body.append(node);
    try {
      node.focus(); const range = document.createRange(); range.selectNodeContents(node);
      selection.removeAllRanges(); selection.addRange(range);
      if (!document.execCommand('copy')) throw new Error('浏览器未允许复制，请使用支持富文本剪贴板的浏览器');
    } finally {
      node.remove(); selection.removeAllRanges(); ranges.forEach(range=>selection.addRange(range)); active?.focus({preventScroll:true});
    }
  }
  function preview(item) {
    return '<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="margin:0;padding:24px 20px;background:white;overflow-wrap:anywhere;">'+fragment(item)+'</body></html>';
  }
  window.PublisherCopy = {fragment, plain, copy, preview};
})();
