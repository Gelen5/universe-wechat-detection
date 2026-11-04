/* One reference, one output, owner-scoped iterative edits. */
(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const root = $('#viral-remix-result');
  if (!root) return;
  let owner = null, epoch = 0, busy = false, current = null;
  const choices = new Set();
  const requestId = () => crypto.randomUUID ? crypto.randomUUID() : Array.from(crypto.getRandomValues(new Uint8Array(20)),value=>value.toString(16).padStart(2,'0')).join('');
  const active = job => ['queued', 'running'].includes(job.status);
  const key = () => `remix-studio:${owner}`;
  const labels = {queued:'任务已保存，等待生成',understanding:'正在理解原图与要求',designing:'正在重新设计画面',generating:'正在生成图片',validating:'正在检查成图',repairing:'正在优化成图',running:'正在处理'};
  async function api(path, body) {
    const response = await fetch('/api/remix-studio/' + path, {credentials:'same-origin',cache:'no-store',...(body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求未完成，请稍后重试');
    return data;
  }
  function node(tag, text, className) { const el=document.createElement(tag); if(text)el.textContent=text;if(className)el.className=className;return el; }
  function button(text, fn) { const el=node('button',text);el.type='button';el.onclick=fn;return el; }
  function visible() { root.hidden=false;$('#viral-remix-empty').hidden=true; }
  function lock(value) {busy=value;$('#viral-remix-start').disabled=value;}
  function render(job) {
    current=job;visible();root.replaceChildren();
    root.append(node('p',active(job)?labels[job.stage]||labels[job.status]:'本次创作','studio-status'));
    if(active(job)){root.append(node('p','可以离开页面，任务和结果会按账号保存。'));return;}
    if(job.status!=='succeeded'){root.append(node('p',job.error||job.error_message||'本次没有生成可交付图片，预扣积分会退还。'));return;}
    const image=job.images?.[0];
    if(!image || !/^\/api\/creator-tools\/assets\//.test(image.url)){root.append(node('p','图片暂时不可用，请从历史记录重新加载。'));return;}
    const img=node('img');img.src=image.url;img.alt='二创成图';img.className='studio-output-image';root.append(img);
    if(window.RemixSave)root.append(window.RemixSave.saveButton(image.url,'保存 / 下载图片'));
    const editor=node('section',null,'studio-editor');editor.append(node('h3','哪里还想调整？'),node('p','选择方向或写下具体要求，修改这张图；原版本会保留。'));
    const selected=new Set(), chips=node('div',null,'studio-guidance');
    for(const [id,label] of Object.entries({headline:'标题更抓眼球',subject:'主体更突出',cleaner:'画面更简洁',new_direction:'换一种设计',no_title:'去掉标题'})){
      const chip=button(label,()=>{selected.has(id)?selected.delete(id):selected.add(id);chip.setAttribute('aria-pressed',String(selected.has(id)));});chip.setAttribute('aria-pressed','false');chips.append(chip);
    }
    const field=node('label','补充修改要求'), input=node('textarea');input.maxLength=1200;input.placeholder='例如：标题放大，突出第一名；其他数据和配色保留。';field.append(input);
    const send=button('按要求修改这张图 →',async()=>{
      if(busy)return;
      if(!input.value.trim()&&!selected.size){input.focus();return;}
      const token=epoch;lock(true);send.disabled=true;
      try{const data=await api(encodeURIComponent(job.id)+'/revise',{goal:input.value.trim(),options:[...selected],requestId:requestId()});if(token!==epoch)return;await track(data.job,token);}
      catch(error){if(token===epoch){showToast(error.message,'error');send.disabled=false;}}
      finally{if(token===epoch)lock(false);}
    });
    editor.append(chips,field,node('p','生成和修改每次预扣 2 积分；未交付成功会退还。'),send);root.append(editor);
  }
  async function track(job, token) {
    localStorage.setItem(key(),job.id);
    while(token===epoch){render(job);if(!active(job))return;
      await new Promise(resolve=>setTimeout(resolve,2500));if(token!==epoch)return;
      try{job=(await api('jobs/'+encodeURIComponent(job.id))).job;}
      catch(error){if(token===epoch)root.append(node('p','连接暂时中断，任务继续运行；正在重新连接。'));await new Promise(resolve=>setTimeout(resolve,5000));}
    }
  }
  async function submit() {
    if(busy)return;
    if(!currentAccount?.id){showToast('请先登录后开始创作','error');return;}
    if(!viralFiles.length){showToast('请先上传一张原图','error');return;}
    const token=epoch;lock(true);
    try{
      const imageData=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('图片读取失败'));reader.readAsDataURL(viralFiles[0]);});
      if(token!==epoch)return;
      const data=await api('create',{imageData,goal:$('#viral-remix-goal').value.trim(),options:[...choices],requestId:requestId()});
      if(token===epoch)await track(data.job,token);
    }catch(error){if(token===epoch)showToast(error.message,'error');}finally{if(token===epoch)lock(false);}
  }
  function reset(){if(busy){showToast('请等待当前任务完成后再新建','error');return;}epoch++;current=null;localStorage.removeItem(key());choices.clear();document.querySelectorAll('[data-studio-option]').forEach(el=>el.setAttribute('aria-pressed','false'));resetViralRemixImage();$('#viral-remix-goal').value='';root.replaceChildren();root.hidden=true;$('#viral-remix-empty').hidden=false;}
  document.querySelectorAll('[data-studio-option]').forEach(chip=>chip.onclick=()=>{const id=chip.dataset.studioOption;choices.has(id)?choices.delete(id):choices.add(id);chip.setAttribute('aria-pressed',String(choices.has(id)));});
  const historyButton=button('查看二创与修改历史',async()=>{
    if(busy){showToast('请等待当前任务完成','error');return;}
    const token=epoch;
    try{const data=await api('history');if(token!==epoch)return;visible();root.replaceChildren();root.append(node('h3','二创与修改历史'));if(!data.jobs.length)root.append(node('p','还没有创作记录。'));
      for(const job of data.jobs){const item=button(`${new Date(job.created_at).toLocaleString('zh-CN')} · ${job.parent_id?'修改版本':'原创版本'} · ${active(job)?'处理中':job.status==='succeeded'?'已完成':'未完成'}`,async()=>{if(busy)return;lock(true);try{await track(job,token);}finally{if(token===epoch)lock(false);}});item.className='studio-history-item';root.append(item);}
    }catch(error){if(token===epoch)showToast(error.message,'error');}
  });
  $('#viral-remix-form').after(historyButton);
  async function syncOwner(){const next=currentAccount?.id||null;if(next===owner)return;owner=next;const token=++epoch;current=null;lock(false);root.replaceChildren();root.hidden=true;$('#viral-remix-empty').hidden=false;
    if(!owner)return;const id=localStorage.getItem(key());if(!id)return;
    try{const data=await api('jobs/'+encodeURIComponent(id));if(token!==epoch)return;lock(true);await track(data.job,token);}catch{}finally{if(token===epoch)lock(false);}
  }
  window.addEventListener('account-changed',syncOwner);
  window.RemixStudio={submit,reset};syncOwner();
})();
