(() => {
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    const el = document.createElement('textarea'); el.value = text; document.body.append(el); el.select();
    const ok = document.execCommand('copy'); el.remove(); if (!ok) throw new Error('复制失败，请手动选择文字复制');
  }
  function render(job, options = {}) {
    const panel = document.createElement('section'); panel.className = 'remix-publication';
    if (!job.id && !options.endpoint) { panel.textContent = '这条旧记录缺少任务编号，暂时无法生成配文。'; return panel; }
    let data = job.publication;
    const endpoint = options.endpoint || `/api/viral-remix/image/${encodeURIComponent(job.id)}/publication`;
    function paint() {
      panel.replaceChildren();
      const head = document.createElement('h3'); head.textContent = options.context ? '标题与配文' : '发布文案'; panel.append(head);
      const tip = document.createElement('p'); tip.textContent = options.context ? '根据卡片计划生成 3 个标题、配文和标签，可编辑复制。离开页面前请保存内容。' : '根据这组图片生成，可编辑后保存。'; panel.append(tip);
      if (!data && !options.context) { const empty = document.createElement('p'); empty.textContent = '这组图片还没有发布文案，可点击下方按钮生成。'; panel.append(empty); }
      let titles = [], body, tags;
      if (data) {
        const label = document.createElement('strong'); label.textContent = '标题备选 · 每条最多20字'; panel.append(label);
        data.titles.forEach((title, index) => {
          const row = document.createElement('div'); row.className = 'remix-copy-row';
          const input = document.createElement('input'); input.value = title; input.maxLength = 20; input.setAttribute('aria-label', `标题 ${index + 1}`); titles.push(input);
          const button = document.createElement('button'); button.type = 'button'; button.textContent = '复制'; button.onclick = () => copyText(input.value).then(() => { message.textContent = '标题已复制'; }).catch(e => { message.textContent = e.message; });
          row.append(input, button); panel.append(row);
        });
        const bodyLabel = document.createElement('label'); bodyLabel.textContent = '配文'; body = document.createElement('textarea'); body.value = data.body; body.maxLength = 3000; body.rows = 5; bodyLabel.append(body); panel.append(bodyLabel);
        const tagsLabel = document.createElement('label'); tagsLabel.textContent = '推荐标签（用空格分隔）'; tags = document.createElement('input'); tags.value = data.tags.map(t => '#' + t).join(' '); tagsLabel.append(tags); panel.append(tagsLabel);
      }
      const message = document.createElement('p'); message.setAttribute('role', 'status'); panel.append(message);
      const actions = document.createElement('div'); actions.className = 'remix-copy-actions';
      if (data) {
        const all = document.createElement('button'); all.type = 'button'; all.textContent = '复制第一个标题和文案'; all.onclick = () => copyText(`${titles[0].value}\n\n${body.value}\n\n${tags.value}`).then(() => { message.textContent = '已复制'; }).catch(e => { message.textContent = e.message; }); actions.append(all);
        const save = document.createElement('button'); save.type = 'button'; save.textContent = '保存修改'; save.onclick = async () => {
          save.disabled = true; message.textContent = '正在保存…';
          try { const response = await fetch(endpoint, {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({titles:titles.map(t=>t.value),body:body.value,tags:tags.value.split(/[\s,，]+/).filter(Boolean)})}); const result = await response.json(); if(!response.ok) throw new Error(result.detail || '保存失败'); data = result.publication; job.publication = data; paint(); panel.querySelector('[role=status]').textContent = '修改已保存'; } catch(e) { message.textContent = e.message; } finally { save.disabled = false; }
        }; if (!options.context) actions.append(save);
      }
      const generate = document.createElement('button'); generate.type = 'button'; generate.textContent = data ? '重新生成标题和配文 · 1积分' : '生成标题和配文 · 1积分'; generate.onclick = async () => {
        if (data && !confirm('重新生成会替换已保存的标题和文案，继续吗？')) return;
        generate.disabled = true; message.textContent = '正在生成标题和文案，请稍候…';
        try { const response = await fetch(endpoint, options.context ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({context:options.context})} : {method:'POST'}); const result = await response.json(); if (!response.ok) throw new Error(result.detail || '生成失败'); data = result.publication; job.publication = data; paint(); if (typeof refreshWallet === 'function') refreshWallet(); } catch(e) { message.textContent = e.message; } finally { generate.disabled = false; }
      }; actions.append(generate); panel.append(actions);
    }
    paint(); return panel;
  }
  window.RemixPublication = {render};
})();
