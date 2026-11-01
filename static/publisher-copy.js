/* One UTF-8 rich-text path for every publisher copy entry. No source-code copy. */
(() => {
  const allowed = new Set('SECTION DIV P SPAN H1 H2 H3 H4 H5 H6 STRONG B EM I U S DEL BR HR BLOCKQUOTE UL OL LI A IMG TABLE THEAD TBODY TFOOT TR TD TH PRE CODE'.split(' '));
  function isStale(item, article) {
    if (!item || !article) return false;
    const source = item.content_json?.source_article_id;
    if (source) return source !== article.id;
    // Existing HTML predates source metadata; use timestamps conservatively.
    const htmlTime = Date.parse(item.updated_at || item.created_at || '');
    const articleTime = Date.parse(article.updated_at || article.created_at || '');
    return !Number.isFinite(htmlTime) || !Number.isFinite(articleTime) || articleTime > htmlTime;
  }
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

  /* ---- 通用富文本复制 ----------------------------------------------------
   * 公众号后台只认行内 style：<style> 块和 class 一律会被丢掉。所以复制前
   * 先把样式压平，再用 Write→回读→降级 三步确认剪贴板里真的有 text/html。
   * 单独做成 copyHtml，是因为 Plus 的排版产物和旧工作台不是同一条生成链路，
   * 但「粘贴后没样式」的原因是同一个。
   */
  const UNSAFE = /<(script|iframe|object|embed|style|link|meta|form|input|button)\b[^>]*>[\s\S]*?<\/\1>|<(script|iframe|object|embed|style|link|meta|form|input|button)\b[^>]*\/?>/gi;

  function flattenStyles(html) {
    const host = document.createElement('div');
    host.innerHTML = html;
    const rules = [];
    // 先把 <style> 里的规则抽出来，再删掉这些标签——公众号会直接丢弃它们。
    for (const style of [...host.querySelectorAll('style')]) {
      const css = style.textContent || '';
      const re = /([^{}@]+)\{([^{}]*)\}/g;
      let match;
      while ((match = re.exec(css))) {
        const selector = match[1].trim();
        const body = match[2].trim();
        if (!selector || !body || selector.startsWith('@') || /::?|@/.test(selector)) continue;
        if (/\b(animation|transition|transform|position|float|z-index|filter|clip-path)\s*:/i.test(body)) continue;
        rules.push([selector, body]);
      }
      style.remove();
    }
    for (const [selector, body] of rules) {
      let targets = [];
      try { targets = [...host.querySelectorAll(selector)]; } catch { continue; }  // 选择器不认识就跳过，不影响复制
      for (const element of targets) {
        // 行内已有的声明优先：作者在标签上写死的值不该被主题覆盖。
        const inline = element.getAttribute('style') || '';
        const declared = new Set(inline.split(';').map(part => part.split(':')[0].trim().toLowerCase()).filter(Boolean));
        const extra = body.split(';').map(part => part.trim()).filter(part => {
          const name = part.split(':')[0].trim().toLowerCase();
          return name && !declared.has(name);
        }).join('; ');
        if (extra) element.setAttribute('style', inline ? inline.replace(/;?\s*$/, '; ') + extra : extra);
      }
    }
    for (const element of host.querySelectorAll('[class]')) element.removeAttribute('class');
    for (const element of host.querySelectorAll('*')) {
      for (const attr of [...element.attributes]) {
        if (/^on/i.test(attr.name)) element.removeAttribute(attr.name);
        else if (/^(href|src)$/i.test(attr.name) && /^\s*javascript:/i.test(attr.value)) element.removeAttribute(attr.name);
      }
    }
    return {html: host.innerHTML, inlined: rules.length > 0};
  }

  function plainOf(html) {
    const source = html.replace(/<br\s*\/?\s*>/gi, '\n').replace(/<\/(p|h[1-6]|li|blockquote|tr|pre|section|div)>/gi, '</$1>\n');
    return new DOMParser().parseFromString(source, 'text/html').body.textContent.trim();
  }

  function richWrite(html, text) {
    return navigator.clipboard.write([new ClipboardItem({
      'text/html': new Blob([html], {type:'text/html;charset=utf-8'}),
      'text/plain': new Blob([text], {type:'text/plain;charset=utf-8'}),
    })]);
  }

  function richFallback(html) {
    const active = document.activeElement;
    const selection = getSelection();
    const ranges = Array.from({length:selection.rangeCount}, (_,i)=>selection.getRangeAt(i).cloneRange());
    const node = document.createElement('div');
    node.contentEditable = 'true'; node.setAttribute('aria-hidden','true');
    node.style.cssText = 'position:fixed;left:-100000px;top:0;width:640px;background:white;';
    node.innerHTML = html; document.body.append(node);
    try {
      node.focus();
      const range = document.createRange(); range.selectNodeContents(node);
      selection.removeAllRanges(); selection.addRange(range);
      if (!document.execCommand('copy')) throw new Error('浏览器未允许复制，请改用 Chrome 或 Edge 打开本页');
    } finally {
      node.remove(); selection.removeAllRanges(); ranges.forEach(range=>selection.addRange(range)); active?.focus({preventScroll:true});
    }
  }

  async function copyHtml(raw) {
    // 顺序很重要：先压平 <style>（要读到规则），再删掉危险/无效标签。
    const {html: flattened, inlined} = flattenStyles(String(raw || ''));
    const html = flattened.replace(UNSAFE, '').replace(/<!--[\s\S]*?-->/g, '');
    if (!html.replace(/<[^>]+>/g, '').trim()) throw new Error('正文为空，未复制');
    const text = plainOf(html);
    let mode = 'clipboard';
    let verified = false;
    if (navigator.clipboard?.write && window.ClipboardItem) {
      try {
        await richWrite(html, text);
        // 回读确认：如果剪贴板里只有纯文本，粘贴到公众号就会一点样式都没有。
        if (navigator.clipboard.read) {
          const [item] = await navigator.clipboard.read();
          const type = item.types.find(name => name === 'text/html');
          if (!type) throw new Error('剪贴板未收到富文本');
          const written = await (await item.getType(type)).text();
          verified = /style\s*=/.test(written);
          if (!verified) throw new Error('剪贴板富文本缺少行内样式');
        } else {
          verified = true;  // 没有读取权限时无法校验，按浏览器契约视为成功
        }
      } catch {
        richFallback(html);
        mode = 'fallback';
        verified = true;
      }
    } else {
      richFallback(html);
      mode = 'fallback';
      verified = true;
    }
    if (!verified) throw new Error('复制结果未通过校验，请重试');
    return {mode, inlined, styleCount: (html.match(/style\s*=/g) || []).length};
  }

  window.PublisherCopy = {fragment, plain, copy, preview, isStale, copyHtml};
})();
