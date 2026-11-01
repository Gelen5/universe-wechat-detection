(() => {
  const $ = s => document.querySelector(s);
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const mobile = ios || /Android/i.test(navigator.userAgent);
  let currentFile = null, currentUrl = null, requestVersion = 0, historyCursor = null, ownerId = null;
  const saveDialog = $('#remix-save-dialog'), historyDialog = $('#remix-history-dialog');
  function validUrl(raw) {
    try { const url = new URL(raw, location.origin); return url.origin === location.origin && url.pathname.startsWith('/api/creator-tools/assets/') ? url.href : null; }
    catch { return null; }
  }
  function status(text) { $('#remix-save-status').textContent = text; }
  function clearPreview() { if (currentUrl) URL.revokeObjectURL(currentUrl); currentUrl = null; currentFile = null; $('#remix-save-preview').removeAttribute('src'); }
  async function open(raw) {
    const url = validUrl(raw); if (!url) { alert('图片地址无效，请在历史记录中重试。'); return; }
    const version = ++requestVersion, button = $('#remix-save-action'); clearPreview();
    $('#remix-save-preview').src = url; button.disabled = true; button.textContent = '正在准备图片…'; status('正在准备原图…'); saveDialog.showModal();
    try {
      const response = await fetch(url, { credentials:'same-origin', cache:'no-store' });
      if (!response.ok) throw new Error(response.status === 404 ? '原图暂时不可用' : '图片读取失败');
      const blob = await response.blob(); if (!blob.type.startsWith('image/')) throw new Error('图片格式无法识别');
      if (version !== requestVersion) return;
      const ext = blob.type === 'image/png' ? 'png' : blob.type === 'image/webp' ? 'webp' : 'jpg';
      currentFile = new File([blob], `爆款贴图复刻.${ext}`, {type:blob.type});
      // A data URL gives iOS a normal image element for the long-press menu.
      const reader = new FileReader(); reader.onload = () => { if (version === requestVersion) $('#remix-save-preview').src = reader.result; }; reader.readAsDataURL(blob);
      button.disabled = false; button.textContent = mobile ? '保存到相册 / 分享' : '下载原图';
      status(mobile ? '点击保存，或长按图片选择“保存图片”。' : '原图已准备好，可以下载。');
    } catch (error) { if (version === requestVersion) { status(error.message + '；如果图片仍显示，可尝试长按保存。'); button.textContent = '图片暂时不可下载'; } }
  }
  $('#remix-save-close').onclick = () => saveDialog.close();
  saveDialog.addEventListener('close', () => { requestVersion++; clearPreview(); });
  $('#remix-save-action').onclick = async () => {
    if (!currentFile) return;
    if (mobile) {
      try { if (navigator.share && navigator.canShare?.({files:[currentFile]})) { await navigator.share({files:[currentFile],title:'爆款贴图复刻'}); status('如需保存到相册，请在系统面板选择保存图片。'); return; } }
      catch (error) { if (error.name === 'AbortError') { status('已取消，也可以长按图片保存。'); return; } }
      status(ios?'请长按上方图片并选择“存储图像”；如果当前应用不支持，请使用 Safari 打开。':'请长按上方图片并选择“保存图片”；如果当前应用不支持，请使用手机浏览器打开。'); return;
    }
    const url = URL.createObjectURL(currentFile), a = document.createElement('a'); a.href=url; a.download=currentFile.name; document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),60000); status('正在下载原图。');
  };
  function saveButton(url, label='保存 / 下载') { const button=document.createElement('button');button.type='button';button.className='remix-save-button';button.textContent=label;button.onclick=()=>open(url);return button; }
  async function loadHistory(append=false) {
    const content=$('#remix-history-content'), more=$('#remix-history-more'); more.hidden=true;
    if (!append) { historyCursor=null; content.textContent='正在加载…'; }
    try {
      const response=await fetch('/api/viral-remix/history'+(historyCursor?'?before='+encodeURIComponent(historyCursor):''),{credentials:'same-origin',cache:'no-store'});
      const data=await response.json().catch(()=>({})); if(!response.ok) throw new Error(response.status===401?'请先登录后查看':data.detail||'历史记录加载失败');
      if(!append)content.replaceChildren();
      if(!data.jobs.length && !append){content.textContent='还没有生成记录。';return;}
      for(const job of data.jobs){const group=document.createElement('section');group.className='remix-history-job';const heading=document.createElement('h3');const date=new Date(job.created_at);heading.textContent=(Number.isNaN(date.valueOf())?'':date.toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}))+' · '+({succeeded:'已完成',running:'生成中',queued:'排队中',failed:'未完成',canceled:'已取消'}[job.status]||job.status);group.append(heading);const grid=document.createElement('div');grid.className='remix-history-grid';for(const image of job.images||[]){const url=validUrl(image.url);if(!url)continue;const card=document.createElement('div');card.className='remix-history-card';const img=document.createElement('img');img.src=url;img.alt='生成的图片';img.loading='lazy';card.append(img,saveButton(url,'保存图片'));grid.append(card)}if(!grid.childElementCount){const note=document.createElement('p');note.textContent=job.status==='running'||job.status==='queued'?'图片生成后会显示在这里。':'这次任务没有可展示的图片。';group.append(note)}else group.append(grid);content.append(group)}
      historyCursor=data.next_before||null;more.hidden=!historyCursor;
    }catch(error){if(!append)content.textContent=error.message;else alert(error.message)}
  }
  $('#remix-history-open').onclick=()=>{historyDialog.showModal();loadHistory()}; $('#remix-history-close').onclick=()=>historyDialog.close(); $('#remix-history-more').onclick=()=>loadHistory(true);
  function setOwner(next){next=next||null;if(ownerId===next)return;ownerId=next;if(historyDialog.open)historyDialog.close();if(saveDialog.open)saveDialog.close();$('#remix-history-content').replaceChildren();historyCursor=null}
  window.RemixSave={open,saveButton,setOwner};
})();
