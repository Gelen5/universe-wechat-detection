/*
 * folio.js — 素笺落地 · 空态 landing + 起点回填 + 发送桥接
 * ────────────────────────────────────────────────────────────────
 * 只服务 #workbench（公众号创作页）。原则与 design-parity.js 相同：
 *   · 不删不改任何既有节点，只新增一个 <section class="folio-landing">
 *   · 幂等、失败静默
 *   · 「最近创作」只读首页真实数据，读不到就整块隐藏，绝不编造
 * 空态判定：#workbench-chat-thread 里没有一条 .chat-message。
 * 空态时：body[data-folio-empty] → CSS 隐藏双栏，显示 landing；
 * 有对话后自动切回工作态，两个状态是同一个页面。
 * ──────────────────────────────────────────────────────────────── */
(function () {
  'use strict';

  var wb = null, thread = null, layout = null, landing = null;

  function $(s, r) { return (r || document).querySelector(s); }

  var STARTS = [
    ['中老年情感方向：父亲每次说完「我没事」都会去阳台，想写一篇让人心里发紧的文章',
     '中老年情感：父亲那句「我没事」', '情感 · 长文'],
    ['生成明天早上的早安祝福，要一张图配一段文案',
     '早安祝福：图 + 文案一键生成', '早安祝福'],
    ['帮我复核这篇文章的爆文潜力：https://mp.weixin.qq.com/s/xxxx',
     '发一篇链接，发布前复核爆文潜力', '爆文检测']
  ];

  function build() {
    landing = document.createElement('section');
    landing.className = 'folio-landing';
    landing.id = 'folio-landing';
    landing.style.display = 'none';

    var starts = STARTS.map(function (it, i) {
      return '<a data-fill="' + it[0].replace(/"/g, '&quot;') + '">' +
             '<span class="fl-n">0' + (i + 1) + '</span>' +
             '<span class="fl-t">' + it[1] + '</span>' +
             '<span class="fl-tag">' + it[2] + '</span></a>';
    }).join('');

    landing.innerHTML =
      '<div class="fl-inner">' +
        '<div class="fl-main">' +
          '<h1>公众号创作</h1>' +
          '<p class="fl-sub">从一个主题开始，其余的交给我 —— 选题、大纲、正文、去 AI、排版，一共五步。左边聊，右边出稿。</p>' +
          '<div class="fl-ask">' +
            '<textarea id="folio-ask" placeholder="你想写点什么？比如：写一篇让 50 岁以上读者心里发紧的情感文"></textarea>' +
            '<div class="fl-ask-row">' +
              '<span class="fl-tip">回车发送 · 会调用完整 Skill</span>' +
              '<button class="fl-send" id="folio-send" type="button">发送 →</button>' +
            '</div>' +
          '</div>' +
          '<div class="fl-starts"><p class="fl-lbl">或者从这里开始</p>' + starts + '</div>' +
        '</div>' +
        '<aside class="fl-side">' +
          '<div class="fl-recent" id="folio-recent" hidden><p>最近创作</p></div>' +
          '<div class="fl-flow"><p>五步到可交付</p><ol>' +
            '<li><i>01</i><b>选题</b><em>先确认值得写的角度</em></li>' +
            '<li><i>02</i><b>大纲</b><em>把角度拆成可写的骨架</em></li>' +
            '<li><i>03</i><b>写作</b><em>按大纲写正文</em></li>' +
            '<li><i>04</i><b>去 AI</b><em>去掉机器腔和套话</em></li>' +
            '<li><i>05</i><b>排版</b><em>交一份可粘贴的样式</em></li>' +
          '</ol></div>' +
        '</aside>' +
      '</div>';

    wb.insertBefore(landing, layout);
    bind();
  }

  /* 最近创作：只认首页真实的最近创作列表（#home-recent-list），
     绝不抓营销文案和功能介绍；读不到就整块隐藏。 */
  function fillRecent() {
    var box = $('#folio-recent', landing);
    if (!box || box.dataset.done) return;
    var links = document.querySelectorAll('#home-recent-list a[href]');
    var seen = {}, out = [];
    Array.prototype.forEach.call(links, function (a) {
      var t = (a.textContent || '').replace(/\s+/g, ' ').trim();
      if (t.length < 6 || t.length > 40 || seen[t]) return;
      seen[t] = 1;
      out.push(t);
    });
    if (out.length >= 1) {
      box.hidden = false;
      box.dataset.done = '1';
      out.slice(0, 2).forEach(function (t) {
        var a = document.createElement('a');
        a.textContent = t;
        a.addEventListener('click', function () {
          var box2 = $('#folio-ask', landing);
          if (box2) { box2.value = '接着写：' + t; box2.focus(); }
        });
        box.appendChild(a);
      });
    }
  }

  /* 空态 = 用户还没有说过话，且还没有任何产物。
     欢迎消息（from-ai）不算数 —— 那是系统开场白，不该把新人挡在外面。
     任务执行中的步骤卡（.chat-steps / .tool-progress）也不算空 ——
     此时用户消息往往还没落库渲染，绝不能让 landing 弹回来盖住正在跑的任务。 */
  function isEmpty() {
    if (!thread) return false;
    if (thread.querySelector('.chat-message.from-user, .chat-message.from-me')) return false;
    if (thread.querySelector('.tool-progress, .chat-steps, [data-workbench-pending]')) return false;
    var prog = document.getElementById('workbench-progress');
    if (prog && prog.offsetHeight > 0 && !prog.hidden) return false;
    var out = document.getElementById('studio-stage-output');
    if (out && out.children.length) return false;
    var choices = document.querySelector('#workbench .workbench-stage-choices');
    if (choices && choices.querySelector('button')) return false;
    return true;
  }

  function sync() {
    if (!wb || !landing) return;
    var empty = isEmpty();
    if (empty) {
      wb.setAttribute('data-folio-empty', '1');
      landing.style.display = '';
      fillRecent();
    } else {
      wb.removeAttribute('data-folio-empty');
      landing.style.display = 'none';
    }
  }

  /* 发送：把 landing 输入桥接到真实表单 #workbench-topic + #start-workbench */
  function send() {
    var box = $('#folio-ask', landing);
    if (!box) return;
    var v = (box.value || '').trim();
    var topic = $('#workbench-topic');
    var go = $('#start-workbench');
    if (!v || !topic || !go) return;
    topic.value = v;
    topic.dispatchEvent(new Event('input', { bubbles: true }));
    go.click();
  }

  function bind() {
    var sendBtn = $('#folio-send', landing);
    var box = $('#folio-ask', landing);
    if (sendBtn) sendBtn.addEventListener('click', send);
    if (box) box.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });
    Array.prototype.forEach.call(landing.querySelectorAll('.fl-starts a'), function (a) {
      a.addEventListener('click', function () {
        box.value = a.getAttribute('data-fill') || '';
        box.focus();
      });
    });
  }

  function boot() {
    wb = document.getElementById('workbench');
    thread = document.getElementById('workbench-chat-thread');
    layout = document.querySelector('#workbench .conversation-workbench-layout');
    if (!wb || !thread || !layout) return;          // 页面结构对不上就安静退出

    landing = document.getElementById('folio-landing');
    if (!landing) build();

    sync();
    if (window.MutationObserver) {
      new MutationObserver(sync).observe(thread, { childList: true, subtree: false });
      var out = document.getElementById('studio-stage-output');
      if (out) new MutationObserver(sync).observe(out, { childList: true });
    }
    setInterval(sync, 1200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
