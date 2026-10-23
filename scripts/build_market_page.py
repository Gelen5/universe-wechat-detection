from pathlib import Path

ROOT = Path(r"C:\Users\16972\Documents\deepseek-harness\default-workspace\market-work")
STATIC = ROOT / "static"

HEADER = '''
<header class="market-topbar">
  <div class="market-wrap">
    <a class="market-brand" href="/" aria-label="宇宙第一工作台 首页">
      <span class="market-mark" aria-hidden="true"></span>
      <span class="market-brand-name">宇宙第一工作台</span>
    </a>
    <nav class="market-tabs" aria-label="产品模块">
      <a href="/">首页</a>
      <a href="/diagnose">诊断</a>
      <a href="/workbench">公众号创作</a>
      <a href="/qihaoshou">起号兽</a>
      <a href="/xiaohongshu">小红书</a>
      <a href="/tie-tu">贴图号</a>
      <a href="/hit-detector">爆文检测</a>
      <a href="/morning-generator">早安祝福</a>
      <a href="/bookshelf">AI 书架</a>
      <a href="/market" class="active" aria-current="page">AI 超市</a>
    </nav>
  </div>
</header>
'''

BODY = '''
<main class="market-page" id="market-main">
  <section class="market-hero">
    <div class="market-wrap">
      <div class="market-kicker"><i></i>SKILL INDEX · 001</div>
      <h1>AI 超市</h1>
      <p>收录 GitHub 上值得一用的 AI Agent Skills。按用途分类，标星排序，点开即到源码目录——不安装、不执行、不托管。</p>
      <div class="market-meta">
        <span><b id="meta-count">—</b> 个 skill</span>
        <span><b id="meta-repos">—</b> 个来源仓库</span>
        <span><b id="meta-official">—</b> 个官方出品</span>
        <span id="meta-updated">正在读取索引…</span>
      </div>
    </div>
  </section>

  <div class="market-wrap">
    <div class="market-searchwrap">
      <label class="market-search">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="market-search-input" placeholder="搜索 skill、仓库或用途…" aria-label="搜索 skill" autocomplete="off" />
        <kbd>⌘K</kbd>
      </label>
    </div>

    <div class="market-layout">
      <aside class="market-rail">
        <h2>分类</h2>
        <ul id="market-categories"></ul>
      </aside>

      <div>
        <section id="market-featured-section">
          <div class="market-section-head"><h2>编辑精选</h2><span>EDITOR'S PICK</span></div>
          <div class="market-featured" id="market-featured"></div>
        </section>

        <div class="market-toolbar">
          <span class="market-count"><b id="market-count">0</b> 个结果</span>
          <div class="market-seg" id="market-sort" role="group" aria-label="排序方式">
            <button type="button" data-sort="stars" aria-pressed="true">Star 最多</button>
            <button type="button" data-sort="added" aria-pressed="false">最近收录</button>
            <button type="button" data-sort="manual" aria-pressed="false">手动排序</button>
          </div>
        </div>

        <div class="market-list" id="market-list"></div>
        <div class="market-more" id="market-more" hidden><button type="button">加载更多</button></div>
      </div>
    </div>
  </div>

  <footer class="market-foot">
    <div class="market-wrap">
      <p>索引数据来自 <a href="https://github.com/truefoundry/awesome-skills-registry" target="_blank" rel="noopener noreferrer">truefoundry/awesome-skills-registry</a>（Apache-2.0），各 skill 的授权与安全性请见其源仓库。</p>
      <p>本页只做介绍与跳转，不安装、不执行、不托管任何 skill 内容。</p>
    </div>
  </footer>
</main>

<button type="button" class="market-admin-toggle" id="market-admin-toggle" hidden>管理</button>
<aside class="market-admin" id="market-admin" aria-label="AI 超市管理">
  <button type="button" class="close" data-close aria-label="关闭">×</button>
  <h3>管理</h3>
  <p class="hint">手动添加的条目会与自动同步的索引并列展示，同步不会覆盖它。</p>
  <form id="market-add-form">
    <label>名称<input name="name" required maxlength="120" placeholder="例如：我的选题库" /></label>
    <div class="row2">
      <label>仓库<input name="repo" required placeholder="owner/repo" /></label>
      <label>目录<input name="path" placeholder="/skills/xxx" /></label>
    </div>
    <div class="row2">
      <label>分类
        <select name="category">
          <option value="productivity">效率</option>
          <option value="coding">编程</option>
          <option value="marketing">营销</option>
          <option value="design">设计</option>
          <option value="data-ai">数据与 AI</option>
          <option value="creative">创意</option>
          <option value="business">商业</option>
          <option value="science">科研</option>
          <option value="legal">法务</option>
          <option value="health">健康</option>
          <option value="miscellaneous">其他</option>
        </select>
      </label>
      <label>星标<input name="stars" type="number" min="0" value="0" /></label>
    </div>
    <label>说明<textarea name="description" maxlength="400" placeholder="一句话说清它解决什么问题"></textarea></label>
    <button type="submit" class="primary">添加到手写清单</button>
  </form>
  <p class="hint">精选排序：在列表里点「设为精选」，按点击顺序排 1、2、3；再次点击取消。</p>
</aside>
'''

HTML = f'''<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 超市 · 宇宙第一工作台</title>
<meta name="description" content="收录 GitHub 上高质量的 AI Agent Skills，按用途分类、标星排序，点开直达源码目录。">
<meta name="theme-color" content="#fbfbfd">
<link rel="stylesheet" href="/static/tokens.css">
<link rel="stylesheet" href="/static/market.css?v=20261024">
</head><body class="market-body">
{HEADER}{BODY}
<script src="/static/market.js?v=20261024" defer></script>
</body></html>
'''

(STATIC / "market.html").write_text(HTML, encoding="utf-8")
print("written", len(HTML))
