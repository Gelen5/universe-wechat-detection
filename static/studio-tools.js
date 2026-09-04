/* awesome-design / Linear: explicit task input, quiet output, progressive detail. */
(() => {
  const tools = [
    ['xiaohongshu','小红书创作','填写主题与读者 → 生成内容包 → 编辑并复制','xhs','标题、正文与图文方案','输入主题后生成内容包。可以补充账号定位和真实素材，让内容更贴合你的账号。'],
    ['tie-tu','微信贴图号','填写主题与风格 → 确认卡片计划 → 逐张生成图片','tie','卡片计划与图片','先生成每张卡片的内容计划，确认后再生成图片。'],
    ['hit-detector','发布前复核','粘贴标题与正文 → 查看问题 → 修改后复核','hit','复核结果与修改建议','提交完整文章后，查看事实、表达和结构问题。检测结果不代表阅读量或爆款概率。'],
  ];
  for (const [id,title,path,prefix,outTitle,hint] of tools) {
    const page = document.getElementById(id);
    page.classList.add('studio-tool');
    const heading = document.createElement('header');
    heading.className = 'tool-heading';
    const h1 = document.createElement('h1'); h1.textContent = title;
    const p = document.createElement('p'); p.textContent = path;
    heading.append(h1,p); page.prepend(heading);
    const empty = document.getElementById(prefix+'-empty');
    empty.replaceChildren();
    const h2 = document.createElement('h2'); h2.textContent = outTitle;
    const description = document.createElement('p'); description.textContent = hint;
    empty.append(h2,description);
    const output = page.querySelector('.skill-output-col');
    const result = document.getElementById(prefix+'-result');
    const form = page.querySelector('form');
    const button = form.querySelector('[type=submit]');
    const status = document.createElement('p'); status.className='tool-status'; status.setAttribute('role','status');
    form.append(status);
    let wasBusy = false;
    new MutationObserver(() => {
      const busy = button.disabled;
      status.textContent = busy ? '正在处理，请稍候。完成后结果将显示在右侧或表单下方。' : '';
      output.setAttribute('aria-busy',String(busy));
      if (wasBusy && !busy && !result.hidden && matchMedia('(max-width: 900px)').matches) {
        output.scrollIntoView({behavior:'smooth',block:'start'});
      }
      wasBusy = busy;
    }).observe(button,{attributes:true,attributeFilter:['disabled']});
  }
  // Static marketing placeholders must not look like live product data.
  document.querySelectorAll('#home .proof, #home .recent-line, #diagnose .proof, #diagnose .v3-meta .r').forEach(el=>el.remove());
  const homeTitle = document.querySelector('#home h1'); homeTitle.textContent='今天，想完成什么？';
  document.querySelector('#home .lede').textContent='选择一个工具开始。填写需求、检查结果，再复制或导出到你的发布平台。';
  const morning = document.querySelector('#morning-generator');
  morning.querySelector('h1').textContent='早安祝福';
  morning.querySelector('.morning-intro p').textContent='选择内容和图片风格，预览效果后生成，再复制或下载。';
  const frame=morning.querySelector('iframe');
  const sizeFrame=()=>{
    try {
      const doc=frame.contentDocument;
      if (!doc?.body) return;
      frame.style.height=Math.ceil(doc.body.scrollHeight+4)+'px';
    } catch {}
  };
  frame.addEventListener('load',()=>{
    sizeFrame();
    new ResizeObserver(sizeFrame).observe(frame.contentDocument.body);
  });
  if(frame.contentDocument?.readyState==='complete') {
    sizeFrame();
    if(frame.contentDocument.body) new ResizeObserver(sizeFrame).observe(frame.contentDocument.body);
  }
})();
