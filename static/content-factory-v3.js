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
  const statusText = {
    held:'待处理', failed:'失败', production_failed:'生成失败', quality_held:'质量检查未通过',
    title_queued:'等待生成标题', title_running:'正在生成标题', title_ready:'标题已生成',
    production_queued:'等待生成内容', production_running:'正在生成内容', published:'已上架'
  };
  const nextAction = (row, reasons) => {
    if (row.error === 'production_failed') return '建议：先看失败环节；确认配置后再重试，可能再次产生调用费用。';
    if (reasons.includes('article_length')) return '建议：调整文章长度后重新检查，未通过前不要上架。';
    if (reasons.some(x => x.includes('source') || x.includes('copyright') || x.includes('facts'))) return '建议：补充或核对来源证据，再进行复核。';
    if (reasons.some(x => x.includes('visual') || x.includes('image_'))) return '建议：检查图片排版和视觉结果，确认无误后再复核。';
    if (row.error === 'automatic_publish_disabled') return '建议：质量已通过，可人工审核后上架。';
    if (row.error === 'automation_stopped') return '建议：先在自动化设置中完成预算和生产开关配置。';
    return '建议：打开任务详情，确认结果后决定是否重试或上架。';
  };
  const toggle = (text, on, handler) => {
    const button = node('button', text);
    button.type = 'button';
    button.className = on ? 'secondary' : '';
    button.onclick = handler;
    return button;
  };

  async function render(parent, api) {
    const box = node('section'); box.className = 'card'; parent.append(box);
    const heading = node('div', undefined, 'automation-heading');
    heading.append(node('h2', '自动化设置'), node('p', '这里只控制后台自动生产；日常审核请看下面的待处理任务。', 'muted'));
    box.append(heading);
    let state;
    try { state = await api('/admin/automation'); }
    catch { box.append(node('p', '自动化尚未安装或数据库迁移未完成；手动商品功能不受影响。')); return; }
    box.append(node('p', state.emergency_stop ? '状态：已紧急停止'
      : `状态：选题${state.automatic_selection ? '开启' : '关闭'} · 定时${state.scheduled_selection ? '开启' : '关闭'} · 文章自动上架${state.automatic_article_publish ? '开启' : '关闭'} · 图片自动上架${state.automatic_image_publish ? '开启' : '关闭'}`));
    box.append(node('p', '费用使用统一币种的微单位；仅在核实每次调用的最高费用后填写。未知费用的预留不会自动释放。朱雀和视觉复核不可用时，文章或图片都不会自动上架。'));
    const fields = [
      ['daily_budget_micros','每日预算'],['title_call_bound_micros','标题单次费用上限'],
      ['article_call_bound_micros','文章单次费用上限'],['image_call_bound_micros','图片单次费用上限'],
      ['detector_call_bound_micros','朱雀单次费用上限'],['vision_call_bound_micros','视觉复核单次费用上限'],
      ['article_limit','每日文章数量'],['image_limit','每日图片数量'],['minimum_score','最低机会分']
    ];
    const form = node('form'); box.append(form);
    for (const [name, label] of fields) {
      const field = node('label', label);
      const input = node('input'); input.type = 'number'; input.min = '0'; input.name = name;
      input.value = String(state[name] ?? 0); field.append(input); form.append(field);
    }
    const tracksLabel = node('label', '启用赛道（逗号分隔）');
    const tracks = node('input'); tracks.name = 'tracks'; tracks.value = (state.tracks || []).join(',');
    tracksLabel.append(tracks); form.append(tracksLabel);
    const confirmLabel = node('label');
    const verified = node('input'); verified.type = 'checkbox'; verified.name = 'verified';
    verified.style.width = 'auto'; verified.checked = !!state.cost_bound_verified;
    confirmLabel.append(verified, document.createTextNode(' 我已核实供应商计价与各项调用费用上限'));
    form.append(confirmLabel);
    const message = node('p'); message.setAttribute('role', 'status'); box.append(message);
    const actions = node('div'); actions.className = 'stack'; box.append(actions);
    const refresh = async () => { box.remove(); await render(parent, api); };
    const action = (text, handler, on = false) => toggle(text, on, async () => {
      message.textContent = '';
      try { await handler(); await refresh(); }
      catch (error) { message.textContent = error.message; }
    });
    actions.append(action('保存预算与赛道', async () => {
      const values = Object.fromEntries(fields.map(([name]) => [name, Number(form.elements[name].value)]));
      values.tracks = tracks.value.split(/[,，]/).map(value => value.trim()).filter(Boolean);
      values.cost_bound_verified = verified.checked;
      await api('/admin/automation/limits', json('PUT', values));
    }));
    actions.append(action('启用标题规划', () => api('/admin/automation/enable-title-planning', {method:'POST'})));
    actions.append(action(state.automatic_articles ? '关闭文章生产' : '启用文章生产', () => api(
      '/admin/automation/enable-production',
      json('POST', {articles: !state.automatic_articles, images: !!state.automatic_images})
    ), state.automatic_articles));
    actions.append(action(state.automatic_images ? '关闭图片生产' : '启用图片生产', () => api(
      '/admin/automation/enable-production',
      json('POST', {articles: !!state.automatic_articles, images: !state.automatic_images})
    ), state.automatic_images));
    actions.append(action(state.automatic_article_publish ? '关闭文章自动上架' : '开启文章自动上架', () => api(
      '/admin/automation/enable-publishing',
      json('POST', {articles: !state.automatic_article_publish, images: !!state.automatic_image_publish})
    ), state.automatic_article_publish));
    actions.append(action(state.automatic_image_publish ? '关闭图片自动上架' : '开启图片自动上架', () => api(
      '/admin/automation/enable-publishing',
      json('POST', {articles: !!state.automatic_article_publish, images: !state.automatic_image_publish})
    ), state.automatic_image_publish));
    actions.append(action(state.scheduled_selection ? '关闭定时选题' : '开启定时选题', () => api(
      '/admin/automation/schedule', json('PUT', {enabled: !state.scheduled_selection})
    ), state.scheduled_selection));
    actions.append(action('紧急停止', () => api('/admin/automation/emergency-stop', {method:'POST'})));

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
        item.append(node('p', `${row.track || '未分类'} · ${row.product_type === 'article' ? '文章' : '图片'} · ${statusText[row.status] || row.status} · ${reasonLabel(row.error || '无错误码')}`));
        if (reasons.length) item.append(node('p', '原因：' + reasons.map(reasonLabel).join('、'), 'muted'));
        const length = quality.details && quality.details.article && quality.details.article.non_whitespace_chars;
        if (Number.isFinite(length) && reasons.includes('article_length')) {
          item.append(node('p', `正文 ${length} 字（要求 1000–1200，不含空白）`, 'muted'));
        }
        item.append(node('p', nextAction(row, reasons), 'action-hint'));
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
        item.append(node('p', `${row.track || '未分类'} · ${row.product_type === 'article' ? '文章' : '图片'} · 尝试 ${row.attempt || 0} · ${statusText[row.status] || row.status}${row.error ? ' · ' + reasonLabel(row.error) : ''}${reasons.length ? ' · ' + reasons.map(reasonLabel).join('、') : ''}`));
        if (row.error || reasons.length) item.append(node('p', nextAction(row, reasons), 'action-hint'));
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
