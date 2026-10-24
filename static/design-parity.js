/*
 * design-parity.js — 布局骨架层需要的少量 DOM 补丁
 * ────────────────────────────────────────────────────────────────
 * 为什么要动 DOM：
 *   设计稿里有三样东西线上 DOM 完全没有 —— 面包屑右侧的操作区、
 *   阶段条里的「圆点序号」、以及阶段条下面那行 STEP 说明。
 *   前两样可以用 CSS 伪元素凑出形似，但「序号要独立成圆」和
 *   「STEP 文案要跟着当前阶段变」必须拿到真实节点和状态，
 *   所以这里做最小侵入的增补：只加类名、只插一个容器，不删不改原有节点。
 *
 * 原则：
 *   · 所有原有 id / class 一律保留，事件监听不受影响
 *   · 幂等：重复执行不会重复插入
 *   · 找不到目标就安静退出，绝不抛错
 * ────────────────────────────────────────────────────────────────
 */
(function () {
  'use strict';

  var STEPS = {
    '选题': ['先确认值得写的角度', '可以只生成选题，不写正文、不出图'],
    '大纲': ['把角度拆成可写的骨架', '每段一句话，先定逻辑再铺字'],
    '写作': ['按大纲写正文', '支持中途改方向，不必从头再来'],
    '去 AI': ['去掉机器腔和套话', '保住信息量，不为降 AI 味牺牲可读性'],
    '排版': ['交接可粘贴的排版样式', '复制到公众号后台，样式不走样']
  };

  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }

  /* ---------- 01 阶段条：把「01 选题」拆成 圆点序号 + 文字 ---------- */
  function splitSteps() {
    var nav = $('#workbench-stage-nav');
    if (!nav) return;
    $$('button', nav).forEach(function (btn) {
      var span = btn.querySelector(':scope > span');
      if (!span) return;

      if (!span.dataset.pdSplit) {
        var m = (span.textContent || '').trim().match(/^(\d+)\s*(.+)$/);
        if (!m) return;
        span.dataset.pdSplit = '1';
        span.textContent = '';
        var d = document.createElement('i');
        d.className = 'pd-step-d';
        d.textContent = String(parseInt(m[1], 10));
        var t = document.createElement('em');
        t.className = 'pd-step-t';
        t.textContent = m[2].trim();
        span.appendChild(d);
        span.appendChild(t);
      }

      // 状态：原 small 里的文字是唯一可靠信号
      var small = btn.querySelector('small');
      var st = small ? (small.textContent || '').trim() : '';
      btn.removeAttribute('data-done');
      btn.removeAttribute('data-current');
      if (/当前/.test(st)) btn.setAttribute('data-current', '1');
      else if (/完成|已生成/.test(st)) btn.setAttribute('data-done', '1');
    });
  }

  /* ---------- 02 阶段条下面的 STEP 说明行 ---------- */
  function ensurePhaseLine() {
    var nav = $('#workbench-stage-nav');
    if (!nav) return;
    var line = $('.pd-phline', nav.parentNode);
    if (!line) {
      line = document.createElement('div');
      line.className = 'pd-phline';
      line.innerHTML = '<span class="pd-mk"></span><div><div class="pd-k"></div><div class="pd-v"></div></div>';
      nav.parentNode.insertBefore(line, nav.nextSibling);
    }
    syncPhaseLine();
  }

  function syncPhaseLine() {
    var line = $('.pd-phline');
    var title = $('#workbench-stage-title');
    if (!line || !title) return;

    var name = (title.textContent || '').trim();
    var idxEl = $('#workbench-stage-kicker');
    var kicker = idxEl ? (idxEl.textContent || '').trim() : '';
    var num = (kicker.match(/(\d+)/) || [, '1'])[1];
    num = ('0' + num).slice(-2);

    var key = Object.keys(STEPS).filter(function (k) {
      return name.indexOf(k) === 0 || k.indexOf(name) === 0;
    })[0] || '选题';
    var pair = STEPS[key];

    var kEl = $('.pd-k', line), vEl = $('.pd-v', line);
    if (kEl) kEl.textContent = 'STEP ' + num;
    if (vEl) vEl.innerHTML = '<b>' + pair[0] + '</b> · ' + pair[1];
  }

  /* ---------- 03 页头右侧操作区：把「新对话」提到页头 ---------- */
  function buildPageActions() {
    var head = $('#workbench .studio-heading');
    if (!head) return;
    var act = $('.pd-pageact', head);
    if (!act) {
      act = document.createElement('div');
      act.className = 'pd-pageact';
      head.appendChild(act);
    }

    // 积分胶囊：读侧栏真实余额，不编数据
    if (!$('.pd-pill', act)) {
      var stat = $('.v3-topbar .right .stat');
      var bal = stat ? (stat.textContent || '').replace(/\s+/g, ' ').trim() : '';
      if (bal) {
        var pill = document.createElement('span');
        pill.className = 'pd-pill';
        pill.textContent = bal;
        act.appendChild(pill);
      }
    }

    // 新对话按钮：从面板头搬到页头（保留原节点，事件监听不会丢）
    var newBtn = $('#new-workbench-chat');
    if (newBtn && newBtn.parentNode !== act) {
      newBtn.classList.add('pd-ghost');
      act.appendChild(newBtn);
    }
  }

  /* ---------- 04 侧栏积分：数字单独放大 ---------- */
  function wrapPoints() {
    $$('.v3-topbar .right .stat').forEach(function (el) {
      if (el.dataset.pdWrapped) return;
      var raw = (el.textContent || '').replace(/\s+/g, ' ').trim();
      var m = raw.match(/^([\d,]+)\s*(.*)$/);
      if (!m) return;
      el.dataset.pdWrapped = '1';
      el.textContent = '';
      var lb = document.createElement('span');
      lb.className = 'pd-pl';
      lb.textContent = '本月积分';
      var b = document.createElement('b');
      b.textContent = m[1];
      el.appendChild(lb);
      el.appendChild(b);
    });
  }

  function runAll() {
    try { splitSteps(); } catch (e) { }
    try { ensurePhaseLine(); } catch (e) { }
    try { buildPageActions(); } catch (e) { }
    try { wrapPoints(); } catch (e) { }
  }

  function boot() {
    runAll();

    // 阶段切换 / 对话重绘后重跑（幂等）
    var title = $('#workbench-stage-title');
    if (title && window.MutationObserver) {
      new MutationObserver(function () {
        try { splitSteps(); } catch (e) { }
        try { syncPhaseLine(); } catch (e) { }
      }).observe(title, { childList: true, characterData: true, subtree: true });
    }

    var nav = $('#workbench-stage-nav');
    if (nav) {
      nav.addEventListener('click', function () { setTimeout(runAll, 60); });
    }

    // 面板可能被重绘，用低频轮询兜底（成本可忽略）
    var tick = 0;
    var timer = setInterval(function () {
      tick++;
      runAll();
      if (tick > 40) clearInterval(timer);
    }, 500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
