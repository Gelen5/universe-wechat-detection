(() => {
  const $ = s => document.querySelector(s);
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const json = (method, body) => ({ method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  const steps = ['research', 'image', 'quality', 'store'];
  const labels = {research:'检索资料', image:'生成画面与配音', quality:'质检', store:'保存成果'};
  let config = {enabled:false, points:0, voices:[]};
  let timer = null;

  async function api(path, options = {}) {
    const response = await fetch('/api/video-factory' + path, options);
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求失败');
    return data;
  }

  function renderSteps(step) {
    const current = steps.indexOf(step);
    $('#steps').replaceChildren(...steps.map((name, index) => el('span', labels[name], index <= current && current >= 0 ? 'done' : '')));
  }

  function parseSources(value) {
    return value.split('\n').map(line => line.trim()).filter(Boolean).map(line => {
      const index = line.indexOf('|');
      if (index < 0) throw Error('每行资料请按“https://地址 | 摘要”填写');
      const url = line.slice(0, index).trim();
      const summary = line.slice(index + 1).trim();
      if (!url.startsWith('https://') || summary.length < 20) throw Error('资料来源必须使用 HTTPS，摘要至少 20 字');
      return {url, summary};
    });
  }

  function showResult(job) {
    const result = job.result || {};
    const root = $('#result');
    root.replaceChildren();
    if (job.status === 'failed') {
      root.append(el('p', job.error || '生成失败，积分已按现有规则退还', 'notice'));
      return;
    }
    if (job.status !== 'succeeded') return;
    const video = el('video');
    video.controls = true;
    video.playsInline = true;
    video.src = `/api/video-factory/jobs/${job.id}/assets/video`;
    video.preload = 'metadata';
    root.append(video);
    video.addEventListener('error', () => {
      $('#notice').textContent = '视频暂时无法播放，请稍后重新打开或下载 MP4';
    }, {once: true});
    const actions = el('div', undefined, 'actions');
    const download = el('a', '下载 MP4');
    download.href = `${video.src}?download=1`;
    download.download = `video-${job.id.slice(0, 8)}.mp4`;
    actions.append(download);
    actions.append(el('button', '复制文案', 'secondary')).onclick = async () => {
      const script = (result.scripts && result.scripts.narration || []).join('\n');
      await navigator.clipboard.writeText(script);
      $('#notice').textContent = '文案已复制';
    };
    const cover = el('a', '查看封面');
    cover.href = `/api/video-factory/jobs/${job.id}/assets/cover`;
    cover.target = '_blank';
    actions.append(cover);
    root.append(actions);
    if (result.storyboard) {
      root.append(el('h3', '分镜'));
      result.storyboard.forEach(scene => root.append(el('pre', `${scene.sequence}. ${scene.narration}\n${scene.visual_prompt}`)));
    }
    const assetLinks = el('div', undefined, 'actions');
    [['captions', '下载字幕'], ['script', '下载文案'], ['storyboard', '下载分镜'],
     ['sources', '下载来源'], ['quality', '下载质检'], ['cost', '下载成本记录']].forEach(([name, label]) => {
      const link = el('a', label);
      link.href = `/api/video-factory/jobs/${job.id}/assets/${name}?download=1`;
      link.download = `${name}-${job.id.slice(0, 8)}`;
      assetLinks.append(link);
    });
    root.append(assetLinks);
    if (result.quality_report) root.append(el('pre', JSON.stringify(result.quality_report, null, 2)));
  }

  async function refresh(jobId) {
    const data = await api(`/jobs/${jobId}`);
    const job = data.job;
    const progressMap = {research:25, image:60, quality:90, store:96};
    const progress = job.status === 'succeeded' ? 100 :
      progressMap[job.result && job.result.progress && job.result.progress.step] || (job.status === 'running' ? 12 : 5);
    $('#progress-bar').style.width = progress + '%';
    $('#job-meta').textContent = `任务 ${job.id.slice(0, 10)} · ${job.status}`;
    renderSteps(job.result && job.result.step || '');
    showResult(job);
    if (job.status === 'succeeded' || job.status === 'failed' || job.status === 'canceled') {
      clearTimeout(timer);
      $('#submit').disabled = !config.enabled;
    } else {
      timer = setTimeout(() => refresh(jobId), 3000);
    }
  }

  $('#form').addEventListener('submit', async event => {
    event.preventDefault();
    $('#notice').textContent = '';
    $('#submit').disabled = true;
    try {
      const form = new FormData(event.currentTarget);
      const topic = String(form.get('topic') || '').trim();
      const idempotency_key = `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const payload = {
        category: form.get('category'), topic, duration: Number(form.get('duration')),
        visual_style: form.get('visual_style'), voice_id: form.get('voice_id'),
        sources: parseSources(String(form.get('sources') || '')), idempotency_key,
      };
      const created = await api('/jobs', json('POST', payload));
      $('#job-meta').textContent = `任务 ${created.job.id.slice(0, 10)} · queued`;
      renderSteps('');
      await refresh(created.job.id);
    } catch (error) {
      $('#notice').textContent = error.message;
      $('#submit').disabled = !config.enabled;
    }
  });

  (async () => {
    try {
      config = await api('/config');
    } catch {
      $('#price-note').textContent = '配置读取失败';
      return;
    }
    const select = $('#voice_id');
    config.voices.forEach(voice => { const option = el('option', voice.label); option.value = voice.id; select.append(option); });
    $('#price-note').textContent = config.enabled ? `预计 ${config.points} 积分 · 实际成本未回传前不虚报人民币金额` : '功能尚未开放';
    $('#submit').disabled = !config.enabled;
    if (!config.enabled) $('#notice').textContent = 'AI 视频工厂尚未开放';
  })();
})();
