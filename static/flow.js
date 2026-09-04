/* ============================================================
   flow.js — 对话式创作引擎 / Conversational Flow Engine
   ------------------------------------------------------------
   设计意图：
     把「填表单」改成「和 AI 对话」。核心是双区——对话（过程）在左，
     产物（结果）在右，避免产物被埋进长长的消息流。

   零破坏桥接策略（关键）：
     不重写 HTML、不改 app.js、不动后端。
     原表单保留在 DOM 里作为「数据管道 + 提交通道」，对话层收集完信息后
     回填字段 → 触发原 submit → app.js 照常调用接口并渲染 #xxx-result
     → 本引擎用 MutationObserver 接管结果容器，搬进产物面板展示。

   架构（严格遵守单向调用，杜绝渲染函数互调）：
     配置层 FLOWS → 数据层 state → 渲染层 render* → 统一入口 refreshAll
     事件处理 → 改数据 → refreshAll()
     渲染函数之间严禁互相调用。

   加新页面只需在 FLOWS 里加一段配置，无需改逻辑。
   ============================================================ */

(function () {
  'use strict';

  /* ============================================================
     配置层 — 改文案 / 加页面，只动这里
     ============================================================ */
  var FLOWS = {
    /* ── 小红书 ─────────────────────────────── */
    xiaohongshu: {
      title: '小红书创作',
      resultId: 'xhs-result',
      formId: 'xhs-form',
      greet: '想写篇小红书？我带你 30 秒理清楚，右边就是这次要产出的东西。',
      steps: [
        {
          key: 'topic',
          ask: '这篇笔记想写什么主题？',
          field: '#xhs-topic',
          placeholder: '例如：我把小红书运营做成了一个 Skill',
          required: true
        },
        {
          key: 'audience',
          ask: '主要写给谁看？',
          field: '#xhs-audience',
          chips: [
            { label: '刚开始做内容的新手', value: '刚开始做内容的创作者' },
            { label: '想涨粉的运营', value: '想涨粉的账号运营' },
            { label: '想接单的自由职业者', value: '想接单的自由职业者' },
            { label: '同行交流', value: '同行从业者' }
          ]
        },
        {
          key: 'goal',
          ask: '最想让人看完做什么？',
          field: '#xhs-goal',
          isSelect: true,
          chips: [
            { label: '收藏起来', value: '获得收藏' },
            { label: '来评论区聊', value: '引导互动' },
            { label: '信任我这个人', value: '教育与建立信任' },
            { label: '买我的东西', value: '产品承接' }
          ]
        },
        {
          key: 'evidence',
          ask: '有你自己的真实经历或数据要放进去吗？没有就跳过，有的话内容会实很多。',
          field: '#xhs-evidence',
          placeholder: '真实经历、后台数据、案例素材…',
          skippable: true
        }
      ],
      products: [
        { key: 'titles', n: '01', t: '三个标题', tag: '3 candidates', note: '三种不同钩子的写法，挑一个顺手的。', lines: [88, 72, 80] },
        { key: 'cover', n: '02', t: '封面', tag: '3:4 · 1 shot', note: '大字压在八个字以内，左下角留副标。', lines: [90, 58] },
        { key: 'body', n: '03', t: '正文', tag: '5–7 段', note: '每段只讲一件事，开头两句负责抓人。', lines: [92, 78, 86, 64, 82] },
        { key: 'pin', n: '04', t: '置顶评论', tag: 'boost', note: '留个钩子，把人引到评论区。', lines: [70, 50] }
      ]
    },

    /* ── 微信贴图号 ─────────────────────────── */
    'tie-tu': {
      title: '贴图号创作',
      resultId: 'tie-result',
      formId: 'tie-form',
      greet: '做一组贴图？右边就是这次的卡片墙，先跟我聊两句。',
      steps: [
        {
          key: 'topic',
          ask: '这组贴图想讲什么？',
          field: '#tie-topic',
          placeholder: '例如：40岁以后，旅行要换一种玩法',
          required: true
        },
        {
          key: 'audience',
          ask: '给谁看的？',
          field: '#tie-audience',
          chips: [
            { label: '40-50 岁', value: '40-50 岁用户' },
            { label: '25-35 岁', value: '25-35 岁用户' },
            { label: '年轻学生', value: '学生群体' },
            { label: '泛人群', value: '泛人群' }
          ]
        },
        {
          key: 'count',
          ask: '大概要几张？',
          field: '#tie-count',
          chips: [
            { label: '4 张', value: '4' },
            { label: '5 张', value: '5' },
            { label: '6 张', value: '6' },
            { label: '8 张', value: '8' }
          ]
        },
        {
          key: 'portrait',
          ask: '画面里要出现同一个人吗？',
          field: '#tie-portrait',
          isSelect: true,
          chips: [
            { label: '保持同一个人', value: 'required' },
            { label: '不要人物', value: 'off' },
            { label: '你来定', value: 'auto' }
          ]
        },
        {
          key: 'style',
          ask: '视觉风格想要什么感觉？',
          field: '#tie-style',
          placeholder: '成熟、温暖、清晰',
          chips: [
            { label: '治愈系', value: '治愈系 · 莫兰迪 + 柔光' },
            { label: '复古港风', value: '复古港风 · 暖金 + 颗粒' },
            { label: '极简白', value: '极简白 · 黑白 + 衬线' },
            { label: '胶片摄影', value: '胶片摄影 · 高反差 + 暖色' },
            { label: '国风手绘', value: '国风手绘 · 水墨 + 留白' },
            { label: '赛博朋克', value: '赛博朋克 · 霓虹紫 + 故障感' }
          ],
          skippable: true
        }
      ],
      products: [
        { key: 'plan', n: '01', t: '分镜计划', tag: 'storyboard', note: '每张讲什么先定下来，再批量出图。', lines: [86, 74, 90, 66] },
        { key: 'cards', n: '02', t: '卡片成图', tag: '3:4 cards', note: '保持同一个人物和视觉系统。', grid: true }
      ]
    },

    /* ── 爆文检测（单次粘贴，不追问）───────────── */
    'hit-detector': {
      title: '爆文检测',
      resultId: 'hit-result',
      formId: 'hit-form',
      greet: '稿子写完了？我按发布前的标准过一遍，右边是检测结果的三样东西。',
      steps: [
        {
          key: 'title',
          ask: '先给我准备发布的标题。',
          field: '#hit-title',
          placeholder: '输入准备发布的标题',
          required: true
        },
        {
          key: 'body',
          ask: '把正文整段粘贴进来。我只标硬伤：能不能发、事实有没有来源、标题兑不兑现。',
          field: '#hit-body',
          placeholder: '粘贴完整正文…',
          required: true,
          textarea: true
        }
      ],
      products: [
        { key: 'blocker', n: '01', t: '发布阻断项', tag: '先看这个', note: '有阻断就别发，改完再说分数。', blocker: true, lines: [90, 66] },
        { key: 'score', n: '02', t: '六维结构参考', tag: 'reference only', note: '结构分用于定位机械短板，不是爆款概率。', lines: [80, 72, 88, 60, 76, 68] },
        { key: 'suggest', n: '03', t: '优先修改建议', tag: 'P0 first', note: '最值得先改的三个点。', blocker: true, lines: [92, 80, 72] }
      ]
    }
  };

  /* ============================================================
     图标（内联 SVG，不用 emoji）
     ============================================================ */
  var ICON = {
    send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6z"/></svg>'
  };

  /* ============================================================
     数据层
     ============================================================ */
  var state = {};   // { pageId: { step:int, answers:{}, phase:'idle|running|done', busy:bool } }

  function getState(pageId) {
    if (!state[pageId]) {
      state[pageId] = { step: 0, answers: {}, phase: 'idle', busy: false, msgs: [] };
    }
    return state[pageId];
  }

  function getFlow(pageId) { return FLOWS[pageId] || null; }

  function resetState(pageId) {
    state[pageId] = { step: 0, answers: {}, phase: 'idle', busy: false, msgs: [] };
  }

  function currentStep(pageId) {
    var f = getFlow(pageId), s = getState(pageId);
    if (!f) return null;
    return f.steps[s.step] || null;
  }

  /* ============================================================
     工具层
     ============================================================ */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function $(sel, root) { return (root || document).querySelector(sel); }

  /** 给表单控件赋值，兼容 input / textarea / select */
  function setFieldValue(sel, value) {
    var el = $(sel);
    if (!el || value == null || value === '') return false;
    if (el.tagName === 'SELECT') {
      var opts = el.options;
      for (var i = 0; i < opts.length; i++) {
        if (opts[i].value === value || opts[i].text === value) {
          el.selectedIndex = i;
          el.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        }
      }
      return false;
    }
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }

  /* ============================================================
     渲染层 — 各函数独立，严禁互调，由 refreshAll 统一调度
     ============================================================ */

  function renderThread(pageId) {
    var s = getState(pageId), f = getFlow(pageId);
    var host = $('#uw-thread-' + pageId);
    if (!host || !f) return;

    var html = '';
    // 开场白
    html += '<div class="uw-msg uw-msg--ai is-first">' +
              '<span class="uw-msg__who">AI</span>' +
              '<div class="uw-msg__bubble">' + esc(f.greet) + '</div>' +
            '</div>';

    for (var i = 0; i < s.msgs.length; i++) {
      var m = s.msgs[i];
      if (m.role === 'me') {
        html += '<div class="uw-msg uw-msg--me">' +
                  '<span class="uw-msg__who">你</span>' +
                  '<div class="uw-msg__bubble">' + esc(m.text) + '</div>' +
                '</div>';
      } else if (m.role === 'ask') {
        html += '<div class="uw-msg uw-msg--ai">' +
                  '<span class="uw-msg__who">AI</span>' +
                  '<div class="uw-msg__bubble">' + esc(m.text) + '</div>' +
                '</div>';
      } else if (m.role === 'mem' && m.step) {
        html += '<div class="uw-remembered" role="button" tabindex="0" data-goto="' + esc(m.step.key) + '" data-page="' + esc(pageId) + '">' +
                  ICON.check + '<span>已记住 · <b>' + esc(m.step.label) + '</b> <em>' + esc(m.text) + '</em></span>' +
                '</div>';
      }
    }

    if (s.busy) {
      html += '<div class="uw-chat__typing"><i></i><i></i><i></i></div>';
    }
    host.innerHTML = html;
    host.scrollTop = host.scrollHeight;
  }

  function renderChips(pageId) {
    var s = getState(pageId);
    var host = $('#uw-chips-' + pageId);
    if (!host) return;

    var step = currentStep(pageId);
    if (!step || s.busy || s.phase === 'running' || s.phase === 'done') {
      host.innerHTML = '';
      return;
    }

    var html = '';
    if (step.chips) {
      for (var i = 0; i < step.chips.length; i++) {
        html += '<button type="button" class="uw-chip" data-val="' + esc(step.chips[i].value) + '">' +
                  esc(step.chips[i].label) +
                '</button>';
      }
    }
    if (step.skippable) {
      html += '<button type="button" class="uw-chip uw-chip--skip" data-skip="1">跳过这步</button>';
    }
    host.innerHTML = html;
  }

  function renderComposer(pageId) {
    var s = getState(pageId);
    var input = $('#uw-input-' + pageId);
    var send = $('#uw-send-' + pageId);
    var wrap = $('#uw-chat-' + pageId);
    var step = currentStep(pageId);
    if (!input) return;

    if (s.busy || s.phase === 'running') {
      input.disabled = true;
      if (send) send.disabled = true;
      if (wrap) wrap.classList.add('is-busy');
      input.placeholder = '正在生成，稍等一下…';
      return;
    }
    input.disabled = false;
    if (wrap) wrap.classList.remove('is-busy');

    if (s.phase === 'done') {
      input.placeholder = '想改哪里直接说，例如：第三个标题再狠一点';
    } else if (step) {
      input.placeholder = step.placeholder || '或直接打字告诉我…';
    } else {
      input.placeholder = '继续说你的要求…';
    }
    updateSendState(pageId);
  }

  function updateSendState(pageId) {
    var input = $('#uw-input-' + pageId);
    var send = $('#uw-send-' + pageId);
    if (!input || !send) return;
    send.disabled = input.value.trim() === '';
  }

  /** 产物面板：独立渲染（不进 refreshAll，避免输入时骨架闪烁） */
  function renderProducts(pageId) {
    var f = getFlow(pageId), s = getState(pageId);
    var host = $('#uw-blocks-' + pageId);
    var outState = $('#uw-state-' + pageId);
    if (!host || !f) return;

    if (s.phase === 'done') {
      host.hidden = true;
      if (outState) { outState.textContent = '已生成'; outState.className = 'uw-out__state is-done'; }
      return;
    }

    var running = (s.phase === 'running');
    host.hidden = false;

    var html = '';
    for (var i = 0; i < f.products.length; i++) {
      var p = f.products[i];
      var cls = 'uw-block' + (running ? ' is-running' : '') + (p.blocker ? ' uw-block--blocker' : '');
      var tag = running ? '生成中' : (p.blocker ? p.tag : '等待开始');
      html += '<div class="' + cls + '" data-block="' + esc(p.key) + '">' +
                '<div class="uw-block__head">' +
                  '<span class="uw-block__n">' + esc(p.n) + '</span>' +
                  '<span class="uw-block__t">' + esc(p.t) + '</span>' +
                  '<span class="uw-block__spacer"></span>' +
                  '<span class="uw-block__tag">' + esc(tag) + '</span>' +
                '</div>' +
                '<div class="uw-block__body">' +
                  (p.grid
                    ? '<div class="uw-skel-grid"><div class="uw-skel-card"></div><div class="uw-skel-card"></div><div class="uw-skel-card"></div><div class="uw-skel-card"></div><div class="uw-skel-card"></div><div class="uw-skel-card"></div></div>'
                    : '<div class="uw-skel">' + buildLines(p.lines) + '</div>') +
                  '<p class="uw-skel-note">' + esc(p.note) + '</p>' +
                '</div>' +
              '</div>';
    }
    host.innerHTML = html;

    if (outState) {
      outState.textContent = running ? '生成中' : '等待开始';
      outState.className = 'uw-out__state' + (running ? ' is-running' : '');
    }
  }

  function buildLines(lines) {
    if (!lines) return '<i style="width:88%"></i><i style="width:70%"></i><i style="width:80%"></i>';
    var h = '';
    for (var i = 0; i < lines.length; i++) {
      h += '<i style="width:' + Number(lines[i]) + '%"></i>';
    }
    return h;
  }

  /* ============================================================
     统一刷新入口（铁律 9：渲染函数之间不互调）
     ============================================================ */
  function refreshAll(pageId) {
    renderThread(pageId);
    renderChips(pageId);
    renderComposer(pageId);
  }

  /* ============================================================
     桥接层 — 对话 → 原表单 → 原提交按钮
     ============================================================ */

  function fillLegacyForm(pageId) {
    var f = getFlow(pageId), s = getState(pageId);
    if (!f) return;
    for (var i = 0; i < f.steps.length; i++) {
      var st = f.steps[i];
      var v = s.answers[st.key];
      if (v) setFieldValue(st.field, v);
    }
    // 主题同时喂给公众号工作台的兼容字段（若存在）
    if (s.answers.topic) {
      var wt = $('#workbench-topic');
      if (wt && !wt.value) wt.value = s.answers.topic;
    }
  }

  function triggerLegacySubmit(pageId) {
    var f = getFlow(pageId);
    if (!f) return false;
    var form = document.getElementById(f.formId);
    if (!form) return false;
    try {
      if (typeof form.requestSubmit === 'function') {
        form.requestSubmit();
      } else {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      }
      return true;
    } catch (e) {
      return false;
    }
  }

  /** 结果容器搬进产物面板 + 监听其变化 */
  function adoptResult(pageId) {
    var f = getFlow(pageId);
    if (!f) return;
    var body = $('#uw-outbody-' + pageId);
    var resultEl = document.getElementById(f.resultId);
    if (!body || !resultEl || resultEl.dataset.uwAdopted === '1') return;

    resultEl.dataset.uwAdopted = '1';
    body.appendChild(resultEl);           // DOM 移动，app.js 的引用不受影响
    resultEl.hidden = true;

    var timer = null;
    var mo = new MutationObserver(function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        if (!resultEl.hidden && resultEl.innerHTML.trim().length > 0) {
          var s = getState(pageId);
          if (s.phase !== 'done') {
            s.phase = 'done';
            s.busy = false;
            s.msgs.push({ role: 'ask', text: '好了，右边是你这次的产物。想改哪里直接说，比如「第三个标题再狠一点」。' });
            renderProducts(pageId);
            refreshAll(pageId);
          }
        }
      }, 120);
    });
    mo.observe(resultEl, { attributes: true, childList: true, subtree: true });
  }

  function submitToBackend(pageId) {
    var s = getState(pageId);
    s.phase = 'running';
    s.busy = true;
    renderProducts(pageId);
    refreshAll(pageId);

    fillLegacyForm(pageId);

    // 让骨架先渲染出来，再触发提交（避免同步阻塞看不到 loading）
    setTimeout(function () {
      var ok = triggerLegacySubmit(pageId);
      if (!ok) {
        s.phase = 'idle';
        s.busy = false;
        s.msgs.push({ role: 'ask', text: '提交没成功，可能是表单还有必填项没填。你手动点一下右边原来的按钮试试。' });
        renderProducts(pageId);
        refreshAll(pageId);
      }
    }, 260);
  }

  /* ============================================================
     事件层 — 改数据 → 调 refreshAll
     ============================================================ */

  function answerStep(pageId, value, label) {
    var s = getState(pageId), f = getFlow(pageId);
    var step = currentStep(pageId);
    if (!step) return;

    s.answers[step.key] = value;
    // 即时回填：任何时候原表单都保持最新，不依赖最后一步统一同步
    setFieldValue(step.field, value);
    s.msgs.push({ role: 'me', text: label || value });
    s.msgs.push({
      role: 'mem',
      text: label || value,
      step: { key: step.key, label: shortLabel(step) }
    });
    s.step += 1;

    if (s.step >= f.steps.length) {
      submitToBackend(pageId);
      return;
    }
    var next = currentStep(pageId);
    if (next) s.msgs.push({ role: 'ask', text: next.ask });
    refreshAll(pageId);
  }

  function shortLabel(step) {
    if (step.key === 'topic') return '主题';
    if (step.key === 'audience') return '读者';
    if (step.key === 'goal') return '目标';
    if (step.key === 'evidence') return '证据';
    if (step.key === 'count') return '张数';
    if (step.key === 'portrait') return '人物';
    if (step.key === 'style') return '风格';
    if (step.key === 'title') return '标题';
    if (step.key === 'body') return '正文';
    return step.key;
  }

  function skipStep(pageId) {
    var s = getState(pageId), f = getFlow(pageId);
    var step = currentStep(pageId);
    if (!step) return;
    s.msgs.push({ role: 'me', text: '（跳过）' });
    s.step += 1;
    if (s.step >= f.steps.length) {
      submitToBackend(pageId);
      return;
    }
    var next = currentStep(pageId);
    if (next) s.msgs.push({ role: 'ask', text: next.ask });
    refreshAll(pageId);
  }

  /** 点「已记住」回到那一步修改 */
  function gotoStep(pageId, key) {
    var s = getState(pageId), f = getFlow(pageId);
    var idx = -1;
    for (var i = 0; i < f.steps.length; i++) {
      if (f.steps[i].key === key) { idx = i; break; }
    }
    if (idx < 0) return;
    s.step = idx;
    s.phase = 'idle';
    s.busy = false;
    // 清掉该步之后的对话记录，避免状态错位
    s.msgs = s.msgs.slice(0, idx * 2);
    s.msgs.push({ role: 'ask', text: f.steps[idx].ask });
    renderProducts(pageId);
    refreshAll(pageId);
  }

  /* ============================================================
     构建 DOM
     ============================================================ */

  function buildFlow(pageId) {
    var f = getFlow(pageId);
    var section = document.getElementById(pageId);
    if (!f || !section || section.dataset.uwBuilt === '1') return;
    section.dataset.uwBuilt = '1';

    var wrap = document.createElement('div');
    wrap.className = 'uw-flow';
    wrap.setAttribute('data-flow', pageId);
    wrap.setAttribute('data-tab', 'out');   // 窄屏默认看产物
    wrap.innerHTML =
      '<div class="uw-flow__tabs">' +
        '<button type="button" class="uw-flow__tab" data-tab="chat">对话</button>' +
        '<button type="button" class="uw-flow__tab is-active" data-tab="out">产物</button>' +
      '</div>' +
      '<section class="uw-chat" id="uw-chat-' + pageId + '">' +
        '<header class="uw-chat__head">' +
          '<span class="uw-chat__badge"><i></i>' + esc(f.title) + '</span>' +
          '<span class="uw-chat__spacer"></span>' +
          '<button type="button" class="uw-chat__reset" data-reset="' + esc(pageId) + '">重新开始</button>' +
        '</header>' +
        '<div class="uw-chat__thread" id="uw-thread-' + pageId + '" aria-live="polite"></div>' +
        '<div class="uw-chat__chips" id="uw-chips-' + pageId + '"></div>' +
        '<div class="uw-chat__composer">' +
          '<textarea class="uw-chat__input" id="uw-input-' + pageId + '" rows="1" aria-label="对 AI 说"></textarea>' +
          '<button type="button" class="uw-chat__send" id="uw-send-' + pageId + '" aria-label="发送" disabled>' + ICON.send + '</button>' +
        '</div>' +
      '</section>' +
      '<section class="uw-out" id="uw-out-' + pageId + '">' +
        '<header class="uw-out__head">' +
          '<span class="uw-out__title">产物</span>' +
          '<span class="uw-out__spacer"></span>' +
          '<span class="uw-out__state" id="uw-state-' + pageId + '">等待开始</span>' +
        '</header>' +
        '<div class="uw-out__body" id="uw-outbody-' + pageId + '">' +
          '<div class="uw-blocks" id="uw-blocks-' + pageId + '"></div>' +
        '</div>' +
      '</section>';

    section.appendChild(wrap);
    section.classList.add('uw-flow-on');

    adoptResult(pageId);
    bindFlowEvents(pageId, wrap);

    // 首条提问
    var s = getState(pageId);
    var first = currentStep(pageId);
    if (first) s.msgs.push({ role: 'ask', text: first.ask });
    renderProducts(pageId);
    refreshAll(pageId);
  }

  function bindFlowEvents(pageId, wrap) {
    var input = $('#uw-input-' + pageId, wrap);
    var send = $('#uw-send-' + pageId, wrap);
    var chips = $('#uw-chips-' + pageId, wrap);
    var thread = $('#uw-thread-' + pageId, wrap);

    // 发送
    function doSend() {
      var v = (input.value || '').trim();
      if (!v) return;
      input.value = '';
      answerStep(pageId, v, v);
    }
    if (send) send.addEventListener('click', doSend);
    if (input) {
      input.addEventListener('input', function () {
        autoGrow(input);
        updateSendState(pageId);
      });
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          doSend();
        }
      });
    }

    // chips 选项
    if (chips) {
      chips.addEventListener('click', function (e) {
        var b = e.target.closest('.uw-chip');
        if (!b) return;
        if (b.dataset.skip === '1') { skipStep(pageId); return; }
        answerStep(pageId, b.dataset.val, b.textContent.trim());
      });
    }

    // 点「已记住」回去改
    if (thread) {
      thread.addEventListener('click', function (e) {
        var m = e.target.closest('.uw-remembered');
        if (!m) return;
        gotoStep(pageId, m.dataset.goto);
      });
      thread.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        var m = e.target.closest('.uw-remembered');
        if (!m) return;
        e.preventDefault();
        gotoStep(pageId, m.dataset.goto);
      });
    }

    // 重新开始
    var reset = $('[data-reset]', wrap);
    if (reset) {
      reset.addEventListener('click', function () {
        resetState(pageId);
        var s = getState(pageId);
        var first = currentStep(pageId);
        if (first) s.msgs.push({ role: 'ask', text: first.ask });
        // 把结果容器还回原处再隐藏，避免残留
        var f = getFlow(pageId);
        var rl = document.getElementById(f.resultId);
        if (rl) { rl.hidden = true; rl.innerHTML = ''; }
        renderProducts(pageId);
        refreshAll(pageId);
      });
    }

    // 窄屏 tab 切换
    var tabs = wrap.querySelectorAll('.uw-flow__tab');
    for (var i = 0; i < tabs.length; i++) {
      (function (btn) {
        btn.addEventListener('click', function () {
          var name = btn.dataset.tab;
          wrap.setAttribute('data-tab', name);
          var all = wrap.querySelectorAll('.uw-flow__tab');
          for (var j = 0; j < all.length; j++) {
            all[j].classList.toggle('is-active', all[j] === btn);
          }
        });
      })(tabs[i]);
    }
  }

  function autoGrow(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 132) + 'px';
  }

  /* ============================================================
     首页「快速开始」注入
     ============================================================ */
  var QUICK = [
    { href: '/diagnose', label: '诊断账号', desc: '看清内容力短板', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></svg>' },
    { href: '/workbench', label: '写公众号', desc: '8 步从选题到发布', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>' },
    { href: '/xiaohongshu', label: '出小红书', desc: '标题 + 封面 + 正文', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="4"/><path d="M8 12h8M12 8v8"/></svg>' },
    { href: '/hit-detector', label: '发前检测', desc: '先看有没有阻断项', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>' }
  ];

  function buildQuickStart() {
    var home = document.getElementById('home');
    if (!home || home.dataset.uwQuick === '1') return;
    var anchor = home.querySelector('.v3-hero');
    if (!anchor) return;
    home.dataset.uwQuick = '1';

    var box = document.createElement('section');
    box.className = 'uw-quickstart';
    var h = '<div class="uw-quickstart__title">快速开始</div><div class="uw-quickstart__grid">';
    for (var i = 0; i < QUICK.length; i++) {
      var q = QUICK[i];
      h += '<a class="uw-quickstart__card" href="' + esc(q.href) + '">' +
             '<span class="uw-quickstart__icon">' + q.icon + '</span>' +
             '<span class="uw-quickstart__body"><strong>' + esc(q.label) + '</strong><span>' + esc(q.desc) + '</span></span>' +
           '</a>';
    }
    h += '</div>';
    box.innerHTML = h;
    if (anchor.parentNode) {
      anchor.parentNode.insertBefore(box, anchor.nextSibling);
    }
  }

  /* ============================================================
     报告页「下一步」CTA 注入（闭环动线）
     ============================================================ */
  function buildReportNext() {
    var report = document.getElementById('report');
    if (!report || report.dataset.uwNext === '1') return;
    var left = report.querySelector('.v3-diag-l');
    if (!left) return;
    report.dataset.uwNext = '1';

    var card = document.createElement('div');
    card.className = 'uw-nextcard';
    card.innerHTML =
      '<div class="uw-nextcard__body">' +
        '<strong>下一步 · 按这份诊断去创作</strong>' +
        '<span>把报告里的短板带进创作台，AI 会照着改稿方向写。</span>' +
      '</div>' +
      '<a class="uw-nextcard__btn" href="/workbench">去创作 →</a>';
    left.appendChild(card);
  }

  /* ============================================================
     初始化（防御性：严格单向，只调一次）
     ============================================================ */
  function init() {
    // Home already contains all six tool links; avoid a duplicate launcher.
    try { buildReportNext(); } catch (e) { /* 报告页动态渲染，观察即可 */ }

    // These tools collect a finite brief. Keep the native forms visible so users
    // can review and edit every field before an explicit submission.
    var ids = [];
    for (var i = 0; i < ids.length; i++) {
      try { buildFlow(ids[i]); } catch (e) { /* 单页失败不拖垮全局 */ }
    }

    // 报告页是 app.js 动态渲染的，DOM 后到，用观察器补挂 CTA
    if (window.MutationObserver) {
      var reportHost = document.getElementById('report');
      if (reportHost) {
        var mo = new MutationObserver(function () {
          if (reportHost.dataset.uwNext !== '1' && reportHost.querySelector('.v3-diag-l')) {
            try { buildReportNext(); } catch (e) {}
          }
        });
        mo.observe(reportHost, { childList: true, subtree: true });
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
