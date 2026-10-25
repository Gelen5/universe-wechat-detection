"""把热点广场接成工作台里的原生视图，并登记到「内容创作」分组。"""
from pathlib import Path

ROOT = Path(r"C:\Users\16972\Documents\deepseek-harness\default-workspace\market-work")
STATIC = ROOT / "static"

SECTION = '''
      <section id="hotspots" class="hs-page" hidden aria-label="热点广场">
        <header class="hs-head">
          <div>
            <h1>热点广场</h1>
            <p>微博、知乎、抖音、头条、百度、B站 的实时热榜，选一条直接开写。</p>
          </div>
          <div class="hs-updated" id="hs-updated"><i></i><span>正在读取…</span></div>
        </header>
        <div class="hs-bar">
          <label class="hs-search">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
            <input id="hs-search" placeholder="搜热点关键词…" aria-label="搜索热点" autocomplete="off" />
          </label>
          <div class="hs-platforms" id="hs-platforms"></div>
        </div>
        <p class="hs-banner" id="hs-banner" hidden></p>
        <div class="hs-list" id="hs-list"></div>
      </section>

'''

NAV = ('<a data-view="hotspots" href="/hotspots"><svg class="tab-icon" viewBox="0 0 24 24" fill="none" '
       'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
       'aria-hidden="true"><path d="M3 17l5-5 4 3 5-7 4 5"/><path d="M3 21h18"/></svg><span>热点广场</span></a>')

index = (STATIC / "index.html").read_text(encoding="utf-8")

if 'id="hotspots"' not in index:
    anchor = index.index('<section id="workbench"')
    index = index[:anchor] + SECTION.lstrip("\n") + index[anchor:]

if "static/hotspots.css" not in index:
    index = index.replace('<link rel="stylesheet" href="/static/market.css',
                          '<link rel="stylesheet" href="/static/hotspots.css?v=20261025-1" />\n'
                          '<link rel="stylesheet" href="/static/market.css', 1)

if "static/hotspots.js" not in index:
    index = index.replace('<script src="/static/market.js',
                          '<script src="/static/hotspots.js?v=20261025-1" defer></script>\n'
                          '<script src="/static/market.js', 1)

if 'data-view="hotspots"' not in index:
    anchor = index.index('>公众号创作<')
    start = index.rindex('<a ', 0, anchor)
    index = index[:start] + NAV + index[start:]

(STATIC / "index.html").write_text(index, encoding="utf-8")

app = (STATIC / "app.js").read_text(encoding="utf-8")
if "hotspots: document.querySelector" not in app:
    app = app.replace("  market: document.querySelector('#market'),\n};",
                      "  market: document.querySelector('#market'),\n"
                      "  hotspots: document.querySelector('#hotspots'),\n};", 1)
if "hotspots: '热点广场'" not in app:
    app = app.replace("  market: 'AI 超市',\n};", "  market: 'AI 超市',\n  hotspots: '热点广场',\n};", 1)
app = app.replace("view !== 'report' && view !== 'market');",
                  "view !== 'report' && view !== 'market' && view !== 'hotspots');", 1)
app = app.replace("  if (view === 'market') window.MarketView?.ensureLoaded?.();",
                  "  if (view === 'market') window.MarketView?.ensureLoaded?.();\n"
                  "  if (view === 'hotspots') window.HotspotsView?.ensureLoaded?.();", 1)
if "window.AppNav" not in app:
    app = app.replace("function setActiveView(view, updateHash = false) {",
                      "window.AppNav = { setActiveView };\n\nfunction setActiveView(view, updateHash = false) {", 1)
(STATIC / "app.js").write_text(app, encoding="utf-8")

nav_js = (STATIC / "notion-workspace.js").read_text(encoding="utf-8")
if "'hotspots'" not in nav_js:
    nav_js = nav_js.replace("['内容创作', ['workbench',",
                            "['内容创作', ['hotspots', 'workbench',", 1)
(STATIC / "notion-workspace.js").write_text(nav_js, encoding="utf-8")
print("ok:", 'id="hotspots"' in index, 'data-view="hotspots"' in index,
      "hotspots: document.querySelector" in app, "'hotspots'" in nav_js)
