/* Admin controls for V3; every switch defaults to stopped. */
window.ContentFactoryAutomation = (() => {
  const node = (tag, text, className) => { const value = document.createElement(tag); if (text !== undefined) value.textContent = text; if (className) value.className = className; return value; };
  const reasonText = {
    missing_title:'缺少标题', missing_content:'缺少内容', missing_source:'来源不完整',
    article_length:'文章字数不符', detector_not_passed:'朱雀检测未通过',
    'check_not_passed:facts':'事实与来源待核验',
    'check_not_passed:copyright':'版权风险未通过',
    'check_not_passed:safety':'内容安全未通过',
    'check_not_passed:title_consistency':'标题正文不一致',
    'check_not_passed:editorial_quality':'编辑质量未达标',
    'check_not_passed:storage':'交付存储待核验',
    'check_not_passed:image_decode':'图片无法解码',
    'check_not_passed:image_dimensions':'图片尺寸不符',
    'check_not_passed:image_text':'图片文字未通过',
    'check_not_passed:visual_quality':'图片视觉复核未通过',
    duplicate_content:'相同内容已存在', claim_requires_source:'存在缺少来源的事实声明',
    source_or_freshness_issue:'来源或时效性不足', numeric_claim_requires_source:'数字缺少来源',
    first_person_experience_unconfirmed:'第一人称经历无法确认',
    title_too_similar_to_source:'标题与来源过于相似',
    source_title_copied_verbatim:'正文复制来源标题',
    long_quotation_needs_rights_review:'长引用需要权利复核',
    compliance_review_required:'合规项需要处理', substantive_content_risk:'存在实质内容风险',
    content_risk_needs_confirmation:'内容风险需要确认',
    editorial_blockers:'存在编辑阻断项', editorial_revisions_required:'编辑质量需要修改',
    editorial_confirmation_required:'编辑确认项未解决',
    editorial_score_below_threshold:'编辑评分低于门槛',
    title_promise_not_fulfilled:'标题承诺未兑现', title_body_overlap_too_low:'标题正文关联过弱',
    visual_review_unavailable:'视觉复核不可用', visual_quality_failed:'视觉质量不合格',
    image_text_failed:'图片文字质检失败', visual_safety_failed:'画面安全未通过',
    visual_rights_failed:'画面版权风险未通过', visual_title_inconsistent:'画面与标题不一致',
    editorial_evidence_unavailable:'编辑检测不可用', editorial_evidence_incomplete:'编辑检测不完整',
    safety_evidence_incomplete:'安全检测不完整', title_evidence_unavailable:'标题检测不可用',
    quality_held:'质量门禁未通过', automatic_publish_disabled:'自动上架未开启',
    production_failed:'生产失败', automation_stopped:'自动化已停止',
    execution_state_unknown:'执行状态未知，需人工核实',
    budget_or_track_changed:'预算或赛道已变化', budget_not_available:'预算不足',
    source_stale:'来源已过期', invalid_evidence:'选题证据无效', invalid_run_data:'任务数据无效',
    title_generation_failed:'标题生成失败', publish_failed:'自动上架失败',
    pending:'处理中'
  };
  const json = (method, value) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(value)});
  const reasonLabel = reason => reasonText[reason] || reason;
  const toggle = (text, on, handler) => {
    const button = node('button', text);
    button.type = 'button';
    button.className = on ? 'secondary' : '';
    button.onclick = handler;
    return button;
  };

  async function render(parent, api) {
    const box = node('section'); box.className = 'card'; parent.append(box);
    box.append(node('h2', '自动化控制'));
    let state;
    try { state = await api('/admin/automation'); }
    catch { box.append(node('p', '自动化尚未安装或数据库迁移未完成；手动商品功能不受影响。')); return; }
    const status = node('div'); status.className = `automation-status ${state.emergency_stop ? 'stopped' : 'running'}`;
    status.append(node('strong', state.emergency_stop ? '自动生成已停止' : '自动生成正在运行'));
    status.append(node('p', state.emergency_stop
      ? '现在不会自动选题、生成或上架。设置好以后点下面的绿色按钮启动。'
      : '系统会按你的设置自动选题；满足质量要求的内容会自动上架。'));
    box.append(status);

    const form = node('form'); box.append(form);
    const check = (label, checked) => {
      const field = node('label'); field.className = 'automation-check';
      const input = node('input'); input.type = 'checkbox'; input.checked = checked;
      input.style.width = 'auto'; field.append(input, document.createTextNode(' ' + label));
      return {field, input};
    };
    const number = (name, label, value, min = 0) => {
      const field = node('label', label);
      const input = node('input'); input.type = 'number'; input.min = String(min); input.name = name;
      input.value = String(value ?? 0); field.append(input); return input;
    };

    const basic = node('fieldset'); basic.append(node('legend', '1. 生成什么'));
    const articleChoice = check('自动生成文章', !!state.automatic_articles);
    const imageChoice = check('自动生成图片', !!state.automatic_images);
    basic.append(articleChoice.field, imageChoice.field);
    const peopleLabel = node('label', '图片里要不要人物');
    const people = node('select'); people.name = 'image_people_mode';
    for (const [value, text] of [['auto','自动判断'],['required','一定要有人物'],['off','不要人物']]) {
      const option = node('option', text); option.value = value;
      option.selected = (state.image_people_mode || 'auto') === value;
      people.append(option);
    }
    peopleLabel.append(people); basic.append(peopleLabel);
    const counts = node('div'); counts.className = 'automation-grid';
    const articleLimit = number('article_limit', '每天几篇文章', state.article_limit);
    const imageLimit = number('image_limit', '每天几张图片', state.image_limit);
    counts.append(articleLimit.parentElement, imageLimit.parentElement); basic.append(counts);
    form.append(basic);

    const publish = node('fieldset'); publish.append(node('legend', '2. 生成后怎么办'));
    const autoPublish = check('质量通过后自动放进成品库', !!state.automatic_article_publish || !!state.automatic_image_publish);
    const schedule = check('每天早晚自动运行（北京时间 08:00 和 15:00）', !!state.scheduled_selection);
    publish.append(autoPublish.field, schedule.field); form.append(publish);

    const advanced = node('details'); advanced.append(node('summary', '高级设置：预算、赛道和最低分'));
    const costFields = [
      ['daily_budget_micros','每天最多花多少（微单位）'],['title_call_bound_micros','单次标题最高费用'],
      ['article_call_bound_micros','单次文章最高费用'],['image_call_bound_micros','单次图片最高费用'],
      ['detector_call_bound_micros','单次朱雀检测最高费用'],['vision_call_bound_micros','单次视觉复核最高费用']
    ];
    const costs = node('div'); costs.className = 'automation-grid';
    for (const [name, label] of costFields) costs.append(number(name, label, state[name]).parentElement);
    advanced.append(costs);
    const minimumScore = number('minimum_score', '选题最低分（越高越少）', state.minimum_score);
    advanced.append(minimumScore.parentElement);
    const tracksLabel = node('label', '启用赛道（逗号分隔）');
    const tracks = node('input'); tracks.name = 'tracks'; tracks.value = (state.tracks || []).join(',');
    tracksLabel.append(tracks); advanced.append(tracksLabel);
    const confirmLabel = node('label');
    const verified = node('input'); verified.type = 'checkbox'; verified.name = 'verified';
    verified.style.width = 'auto'; verified.checked = !!state.cost_bound_verified;
    confirmLabel.append(verified, document.createTextNode(' 我已核实供应商计价与各项调用费用上限'));
    advanced.append(confirmLabel); form.append(advanced);
    advanced.open = !state.cost_bound_verified;

    const message = node('p'); message.setAttribute('role', 'status'); box.append(message);
    const actions = node('div'); actions.className = 'stack'; box.append(actions);
    const refresh = async () => { box.remove(); await render(parent, api); };
    const action = (text, handler, on = false) => toggle(text, on, async () => {
      message.textContent = '';
      try { await handler(); await refresh(); }
      catch (error) { message.textContent = error.message; }
    });
    const saveSettings = async () => {
      const names = [...costFields.map(([name]) => name), 'article_limit', 'image_limit', 'minimum_score'];
      const values = Object.fromEntries(names.map(name => [name, Number(form.elements[name].value)]));
      values.tracks = tracks.value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
      values.image_people_mode = people.value;
      values.cost_bound_verified = verified.checked;
      await api('/admin/automation/limits', json('PUT', values));
    };
    actions.append(action('只保存设置', saveSettings));
    actions.append(action('保存并启动全自动', async () => {
      if (!articleChoice.input.checked && !imageChoice.input.checked) {
        throw Error('请先选择要自动生成文章还是图片');
      }
      await saveSettings();
      await api('/admin/automation/enable-title-planning', {method:'POST'});
      await api('/admin/automation/enable-production', json('POST', {
        articles: articleChoice.input.checked, images: imageChoice.input.checked
      }));
      await api(
      '/admin/automation/enable-publishing',
        json('POST', {
          articles: articleChoice.input.checked && autoPublish.input.checked,
          images: imageChoice.input.checked && autoPublish.input.checked
        })
      );
      await api('/admin/automation/schedule', json('PUT', {enabled: schedule.input.checked}));
    }));
    actions.append(action('立即全部停止', () => api('/admin/automation/emergency-stop', {method:'POST'})));

    try {
      const metrics = await api('/admin/automation/metrics');
      box.append(node('h3', '今日运行指标'));
      box.append(node('p', `候选 ${metrics.candidates} · 文章 ${metrics.articles_generated} · 图片 ${metrics.images_generated} · 质检通过 ${metrics.quality_passed} · 朱雀通过 ${metrics.detector_passed} · 自动上架 ${metrics.auto_published} · 暂缓 ${metrics.held} · 失败 ${metrics.failed} · 成本 ${(metrics.cost_micros / 1000000).toFixed(4)} · 售出 ${metrics.sold_products} 件 / ${metrics.points_revenue} 积分`));
    } catch { box.append(node('p', '运行指标暂不可用')); }

    const list = node('div'); box.append(node('h3', '异常池'), list);
    try {
      const rows = await api('/admin/automation/exceptions');
      if (!rows.length) list.append(node('p', '暂无暂缓或失败任务'));
      for (const row of rows.slice(0, 30)) {
        let quality = {};
        try { quality = JSON.parse(row.quality_json || '{}') || {}; } catch {}
        const reasons = quality.reasons || [];
        const item = node('div'); item.className = 'card stack';
        item.append(node('p', `${row.track || '未分类'} · ${row.product_type === 'article' ? '文章' : '图片'} · ${row.status} · ${row.error || '无错误码'}`));
        if (reasons.length) item.append(node('p', '原因：' + reasons.map(reasonLabel).join('、'), 'muted'));
        const length = quality.details && quality.details.article && quality.details.article.non_whitespace_chars;
        if (Number.isFinite(length) && reasons.includes('article_length')) {
          item.append(node('p', `正文 ${length} 字（要求 1000–1200，不含空白）`, 'muted'));
        }
        if (['held', 'failed'].includes(row.status)) {
          item.append(action('手动重试（最多 2 次）', async () => {
            await api(`/admin/automation/runs/${row.id}/retry`, {method:'POST'});
            message.textContent = '已重新入队，预算按新尝试单独预留';
          }));
        }
        list.append(item);
      }
    } catch { list.append(node('p', '异常池暂不可用')); }

    const recent = node('div'); box.append(node('h3', '最近任务'), recent);
    const ageSeconds = row => {
      const updated = Date.parse(row.updated_at || '');
      return Number.isFinite(updated) ? Math.max(0, (Date.now() - updated) / 1000) : 0;
    };
    try {
      const rows = await api('/admin/automation/runs');
      if (!rows.length) recent.append(node('p', '暂无任务'));
      for (const row of rows.slice(0, 30)) {
        let quality = {};
        try { quality = JSON.parse(row.quality_json || '{}') || {}; } catch {}
        const reasons = quality.reasons || [];
        const item = node('div'); item.className = 'stack';
        item.append(node('p', `${row.track || '未分类'} · ${row.product_type === 'article' ? '文章' : '图片'} · 尝试 ${row.attempt || 0} · ${row.status}${row.error ? ' · ' + reasonLabel(row.error) : ''}${reasons.length ? ' · ' + reasons.map(reasonLabel).join('、') : ''}`));
        if (['title_queued', 'production_queued'].includes(row.status)) {
          item.append(action('重新派发', () => api(`/admin/automation/runs/${row.id}/dispatch`, {method:'POST'})));
        }
        const staleThreshold = row.status === 'title_running' ? 900
          : row.status === 'production_running' ? 1800 : null;
        if (staleThreshold && ageSeconds(row) >= staleThreshold) {
          item.append(action('标记异常', () => api(`/admin/automation/runs/${row.id}/mark-stale`, {method:'POST'})));
        }
        recent.append(item);
      }
    } catch { recent.append(node('p', '任务记录暂不可用')); }
  }
  return {render};
})();
