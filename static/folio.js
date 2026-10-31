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
          '<p class="fl-sub"><span class="fl-desktop-copy">从一个主题开始，其余的交给我 —— 选题、大纲、正文、去 AI、排版，一共五步。左边聊，右边出稿。</span><span class="fl-mobile-copy">写下一个想法，一起把它变成文章。<br>从选题到排版，一步一步来。</span></p>' +
          '<div class="fl-stagebar" aria-label="创作进度"><span class="fl-stage is-on"><i>1</i>选题</span><span class="fl-stage"><i>2</i>大纲</span><span class="fl-stage"><i>3</i>写作</span><span class="fl-stage"><i>4</i>去 AI</span><span class="fl-stage"><i>5</i>排版</span></div>' +
          '<div class="fl-ask">' +
            '<textarea id="folio-ask" aria-label="创作要求：主题、读者和已有素材" placeholder="想写什么、写给谁？也可以粘贴已有素材"></textarea>' +
            '<div class="fl-ask-row">' +
              '<span class="fl-tip"><span class="fl-desktop-copy">回车发送 · 会调用完整 Skill</span><span class="fl-mobile-copy">先说说你想写什么</span></span>' +
              '<button class="fl-send" id="folio-send" type="button">发送 →</button>' +
            '</div>' +
          '</div>' +
          '<div class="fl-starts"><p class="fl-lbl">或者从这里开始</p>' + starts + '</div>' +
          '<button class="fl-canvas-link" id="folio-canvas" type="button">先看看文章画布 <span aria-hidden="true">↗</span></button>' +
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

  /* 选题阶段收起空态占位：
     atelier.css 用 `#workbench-result:not(:has(#studio-stage-output > *))`
     强行把「作品会在这里出现」显示出来（3 个 ID 权重），CSS 层压不过，
     这里用内联 !important 处理（内联 !important 优先级最高）。 */
  var PICK_HIDE = ['.article-canvas-head', '.version-strip', '.editor-wrap', '#workbench-decision'];
  var pickState = null;

  function setPick(on) {
    if (pickState === on) return;
    pickState = on;
    PICK_HIDE.forEach(function (sel) {
      Array.prototype.forEach.call(document.querySelectorAll('#workbench ' + sel), function (el) {
        if (on) el.style.setProperty('display', 'none', 'important');
        else el.style.removeProperty('display');
      });
    });
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
    // 选题已出、还没有作品：收起右栏的空态标题与空编辑器，让选题板直接顶上
    var hasTopics = !!document.querySelector('#workbench .topic-row');
    var t = document.getElementById('result-title');
    var noArtifact = !t || /作品会在这里出现/.test(t.textContent || '');
    var pick = hasTopics && noArtifact;
    if (pick) wb.setAttribute('data-folio-pick', '1');
    else wb.removeAttribute('data-folio-pick');
    setPick(pick);

    // 文档阅读层：textarea 有值就渲染成排版好的只读文档（编辑态时不动）
    ensureDoc();
    var wrap = document.querySelector('#workbench .editor-wrap');
    if (!wrap || !wrap.classList.contains('is-editing')) renderDoc();
    // 有正文时收起提示卡，头部也不再留空态占位
    var ta = document.getElementById('article-editor');
    var hasDoc = !!(ta && (ta.value || '').trim().length > 20);
    if (hasDoc) wb.setAttribute('data-folio-doc', '1');
    else wb.removeAttribute('data-folio-doc');
    /* 兜底：workbench-studio.js 用 `session.article` 判断编辑器显隐，
       而大纲阶段正文还没生成、内容却已经在 textarea 里 ——
       它会把装着大纲的编辑器一起 hidden 掉。这里只要编辑器有字就强制显示。 */
    if (wrap) {
      if (hasDoc) wrap.style.setProperty('display', 'block', 'important');
      else wrap.style.removeProperty('display');
    }
  }

  /* ── 文档阅读层 ──────────────────────────────────────────────
     大纲/正文/去 AI 的内容都塞在 #article-editor 这个 textarea 里，
     纯文本没有任何层级，字号再大也是一团。这里做一个只读渲染层：
     段落、编号小标题、引用各自成块；要改的时候点「编辑」切回 textarea。
     只改视觉，textarea 的值和保存流程完全不动。 */
  var docLayer = null, docBtn = null, docText = null;

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  /* 大纲里真实出现的字段名（从线上产物统计）：
     情境 / 冲突 / 问题 / 回答 / 标题草案 / 写作目的 / 关键论点 / 案例或证据位置 /
     衔接 / 待核验素材 / 假设场景 / 分析要点 / 反事实对照 / 交付提示 / 限制 … */
  var FIELDS = /(?=(?:情境|冲突|问题|回答|标题草案|写作目的|关键论点|核心论点|小标题|案例或证据位置|素材位置|待核验素材|假设场景|分析要点|反事实对照|交付提示|衔接|结构安排|限制|风险|观点|事实边界|要点|正文|开篇)[:：])/;

  /* 一段没有中括号的文本 → 按「字段：值」拆成若干带小标签的段落 */
  function fieldParas(s) {
    var txt = String(s).trim();
    if (!txt) return '';
    var parts = txt.split(FIELDS).filter(function (x) { return x.trim(); });
    if (parts.length > 1) {
      return parts.map(function (seg) {
        var mm = seg.match(/^([^:：]{2,8})[:：]\s*([\s\S]*)$/);
        if (mm) {
          var val = mm[2].trim();
          if (!val) return '';
          return '<p><span class="fdoc-k">' + esc(mm[1]) + '</span>' + esc(val) + '</p>';
        }
        return '<p>' + esc(seg.trim()) + '</p>';
      }).join('');
    }
    return '<p>' + esc(txt) + '</p>';
  }

  /* 「…[观点] xxx；[事实边界] yyy」——中括号前的那截文字也要留住，
     老版本直接从第一个 [ 开始匹配，把前半句整段吃掉了。 */
  function tagify(s) {
    var str = String(s), out = [], re = /\[([^\]]{2,10})\]\s*([^；;]*[；;]?)/g, m, last = 0;
    while ((m = re.exec(str))) {
      var pre = str.slice(last, m.index).trim();
      if (pre) out.push(fieldParas(pre));
      last = re.lastIndex;
      var val = m[2].trim();
      if (val) out.push('<p><span class="fdoc-k">' + esc(m[1]) + '</span>' + esc(val) + '</p>');
    }
    if (!out.length) return fieldParas(str);
    var tail = str.slice(last).trim();
    if (tail) out.push(fieldParas(tail));
    return out.join('');
  }

  /* 一条大纲项，线上真实存在四种写法：
       ① `S｜情境：…`                        （结构标签 + 字段）
       ② `开篇切入｜从读者看到…`              （小标题｜正文）
       ③ `【引言｜标题草案：…】【S】写作目的：…`（中括号标题 + 标签 + 字段）
       ④ `1. 开篇｜先给主张：…；[观点] …`      （重复编号 + 小标题｜带标签正文）
     统一成：编号 + 结构标签 + 小标题 + 字段段落。 */
  function fmtItem(raw) {
    var t = String(raw).trim().replace(/^\d{1,2}[.、)）]\s*/, '');
    var head = '', tag = '', note = '', body = t;

    // ① 开头的连续【…】：1~3 个字母是 S/C/Q/A 结构标签，长的才是小标题
    var re = /^【([^】]{1,80})】\s*/, m;
    while ((m = re.exec(body))) {
      var c = m[1].trim();
      body = body.slice(m[0].length);
      if (/^[A-Za-z]{1,3}$/.test(c)) { if (!tag) tag = c.toUpperCase(); continue; }
      if (!head) {
        var sp = c.split(/[｜|]/);
        head = sp[0].trim();
        if (sp.length > 1) note = sp.slice(1).join('｜').trim();
        continue;
      }
      break;
    }

    // ② 「小标题｜正文」
    if (!head) {
      var parts = body.split(/[｜|]/);
      if (parts.length > 1 && parts[0].trim().length <= 28) {
        var cand = parts.shift().trim();
        if (/^[A-Za-z]{1,3}$/.test(cand)) { if (!tag) tag = cand.toUpperCase(); }
        else head = cand;
        body = parts.join('｜').trim();
      }
    }

    // ③ 「小标题：X 核心论点：Y」
    if (!head) {
      var km = body.match(/^小标题[:：]\s*([\s\S]*?)核心论点[:：]\s*([\s\S]*)$/);
      if (km) { head = km[1].trim(); body = '核心论点：' + km[2].trim(); }
      else if (/^小标题[:：]/.test(body)) { head = body.replace(/^小标题[:：]\s*/, '').trim(); body = ''; }
    }

    // ④ 还没有小标题：把第一个「字段：」的字段名提上来当小标题
    if (!head) {
      var fm = body.match(/^([\u4e00-\u9fa5]{2,8})[:：]\s*/);
      if (fm) { head = fm[1]; body = body.slice(fm[0].length); }
    }

    // ⑤ 整条就是一短语，直接当标题
    if (!head && t.length <= 24 && !/[。；;]/.test(t)) { head = t; body = ''; }

    // 清掉模型输出里残留的「】 【S】」碎片
    body = body.replace(/】\s*【[^】]{0,6}】\s*/g, ' ').replace(/\s{2,}/g, ' ').trim();

    var html = '';
    if (tag) html += '<span class="fdoc-tag">' + esc(tag) + '</span>';
    if (head) html += '<strong class="fdoc-h">' + esc(head) + '</strong>';
    if (note) {
      var nm = note.match(/^([^:：]{1,8})[:：]\s*([\s\S]*)$/);
      html += nm
        ? '<p class="fdoc-note"><span class="fdoc-k">' + esc(nm[1]) + '</span>' + esc(nm[2].trim()) + '</p>'
        : '<p class="fdoc-note">' + esc(note) + '</p>';
    }
    if (body) html += tagify(body);
    return html || '<p>' + esc(t) + '</p>';
  }

  function pad2(n) { return ('0' + n).slice(-2); }

  /* 行内格式：**加粗** / `代码` / [文字](链接) */
  function inline(s) {
    return esc(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  }

  /* 正文是 Markdown（# 标题 / ## 小标题 / > 引用 / - 列表），
     大纲是「1. 小标题｜字段」纯文本 —— 两种形态分开渲染，
     否则大纲的编号会被当成列表、正文的 # 会被当成普通行。 */
  function isMarkdown(text) {
    return /^#{1,4}\s+\S/m.test(text) ||
           /^\s*[-*+]\s+\S/m.test(text) ||
           /^\s*>\s?\S/m.test(text);
  }

  function toMd(text) {
    var lines = String(text).split(/\r?\n/);
    var out = [], buf = [], list = null, quote = [], firstH1 = -1;

    function flushP() { if (buf.length) { out.push('<p>' + inline(buf.join(' ')) + '</p>'); buf = []; } }
    function flushList() {
      if (!list) return;
      out.push('<' + list.tag + '>' + list.items.map(function (x) {
        return '<li>' + inline(x) + '</li>';
      }).join('') + '</' + list.tag + '>');
      list = null;
    }
    function flushQuote() {
      if (!quote.length) return;
      out.push('<blockquote>' + quote.map(function (x) { return '<p>' + inline(x) + '</p>'; }).join('') + '</blockquote>');
      quote = [];
    }
    function flushAll() { flushP(); flushList(); flushQuote(); }

    for (var i = 0; i < lines.length; i++) {
      var l = lines[i].trim();
      if (!l) { flushAll(); continue; }
      var h = l.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        flushAll();
        var lv = h[1].length;
        if (lv === 1 && i <= 2 && firstH1 < 0) {
          // 一级标题就是文章标题，画布头部已经显示了，正文里不再重复
          firstH1 = i; continue;
        }
        var tag = lv <= 2 ? 'h2' : 'h3';
        out.push('<' + tag + '>' + inline(h[2]) + '</' + tag + '>');
        continue;
      }
      if (/^>\s?/.test(l)) { flushP(); flushList(); quote.push(l.replace(/^>\s?/, '')); continue; }
      var ul = l.match(/^[-*+]\s+(.*)$/);
      if (ul) {
        flushP(); flushQuote();
        if (!list || list.tag !== 'ul') { flushList(); list = { tag: 'ul', items: [] }; }
        list.items.push(ul[1]); continue;
      }
      var ol = l.match(/^\d{1,2}[.、)）]\s+(.*)$/);
      if (ol) {
        flushP(); flushQuote();
        if (!list || list.tag !== 'ol') { flushList(); list = { tag: 'ol', items: [] }; }
        list.items.push(ol[1]); continue;
      }
      if (/^([-*_])\1{2,}$/.test(l)) { flushAll(); out.push('<hr>'); continue; }
      flushList(); flushQuote(); buf.push(l);
    }
    flushAll();
    return out.join('');
  }

  /* 大纲多为「单换行」分段，编号还有重复（1. 1. 开篇｜…），这里统一处理 */
  function toOutline(text) {
    var lines = String(text).split(/\r?\n/);
    var out = [], buf = [];
    function flush() {
      if (!buf.length) return;
      out.push('<p>' + esc(buf.join(' ')).replace(/&lt;br&gt;/g, '<br>') + '</p>');
      buf = [];
    }
    for (var i = 0; i < lines.length; i++) {
      var l = lines[i].trim();
      if (!l) { flush(); continue; }
      var num = l.match(/^(\d{1,2})[.、)）]\s*(.*)$/);
      if (num) {
        flush();
        var rest = num[2].replace(/^\d{1,2}[.、)）]\s*/, '');   // 去掉重复编号
        out.push('<div class="fdoc-item"><span class="fdoc-n">' + pad2(num[1]) +
                 '</span><div class="fdoc-body">' + fmtItem(rest) + '</div></div>');
        continue;
      }
      if (/^《[^》]{2,60}》$/.test(l)) { flush(); out.push('<h2 class="fdoc-title">' + esc(l) + '</h2>'); continue; }
      if (/^[「“"]/.test(l) && l.length < 220) { flush(); out.push('<blockquote>' + esc(l) + '</blockquote>'); continue; }
      buf.push(l);
    }
    flush();
    return out.join('');
  }

  function toDoc(text) {
    return isMarkdown(text) ? toMd(text) : toOutline(text);
  }

  function ensureDoc() {
    var ta = document.getElementById('article-editor');
    if (!ta || !ta.parentNode) return;
    var wrap = ta.closest('.editor-wrap');
    if (!wrap) return;
    /* 正文一落库就立刻重排（否则要等 1.2s 轮询，长文看着像卡住） */
    if (!ta.dataset.folioBound) {
      ta.dataset.folioBound = '1';
      ta.addEventListener('input', function () {
        docText = null;
        if (!wrap.classList.contains('is-editing')) renderDoc();
        sync();
      });
    }
    if (!docLayer) {
      docLayer = document.createElement('div');
      docLayer.className = 'folio-doc';
      ta.parentNode.insertBefore(docLayer, ta.nextSibling);
      docBtn = document.createElement('button');
      docBtn.type = 'button';
      docBtn.className = 'folio-doc-edit';
      docBtn.textContent = '编辑';
      wrap.appendChild(docBtn);
      docBtn.addEventListener('click', function () {
        var on = wrap.classList.toggle('is-editing');
        docBtn.textContent = on ? '完成' : '编辑';
        if (on) ta.focus(); else renderDoc();
      });
    }
  }

  /* 页脚信息：字数 + 约读时长。中文按 400 字/分钟估。 */
  var metaEl = null;
  function paintMeta(text) {
    var foot = document.querySelector('#workbench-result .article-canvas-foot');
    if (!foot) return;
    if (!metaEl || !foot.contains(metaEl)) {
      metaEl = document.createElement('span');
      metaEl.className = 'folio-meta';
      foot.insertBefore(metaEl, foot.lastElementChild);
    }
    var n = String(text || '').replace(/\s/g, '').length;
    if (n < 60) { metaEl.textContent = ''; metaEl.style.display = 'none'; return; }
    metaEl.style.display = '';
    metaEl.textContent = n.toLocaleString('zh-CN') + ' 字 · 约 ' +
      Math.max(1, Math.round(n / 400)) + ' 分钟';
  }

  function renderDoc() {
    var ta = document.getElementById('article-editor');
    if (!ta || !docLayer) return;
    var text = (ta.value || '').trim();
    if (text === docText) return;
    docText = text;
    docLayer.innerHTML = text
      ? toDoc(text)
      : '<p class="fdoc-empty">这一步还没有正文。在左边说一句想怎么写，我来出稿。</p>';
    if (docBtn) docBtn.style.display = text ? '' : 'none';
    paintMeta(text);
  }


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
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
    Array.prototype.forEach.call(landing.querySelectorAll('.fl-starts a'), function (a) {
      a.addEventListener('click', function () {
        box.value = a.getAttribute('data-fill') || '';
        box.focus();
      });
    });
    var canvasBtn = $('#folio-canvas', landing);
    if (canvasBtn) canvasBtn.addEventListener('click', function () {
      var sw = document.querySelector('#workbench .studio-switch [data-studio-view="article"]');
      if (sw) sw.click();
      var result = document.getElementById('workbench-result');
      if (result && result.scrollIntoView) result.scrollIntoView({ block: 'start', behavior: 'smooth' });
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
