/* Single source of truth for application navigation.
 *
 * Every renderer (notion-workspace.js, shell.js, app-navigation.js) derives its
 * list from here, so adding a module means editing this file only. Values are
 * kept identical to the previously hard-coded arrays: same order, same labels,
 * same short labels, same icons, so the rendered DOM does not change.
 */
window.APP_NAV = (() => {
  const svg = (inner) =>
    '<svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    inner + '</svg>';

  const home = {
    href: '/', view: 'home', label: '首页', short: '首页',
    icon: svg('<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>'),
  };

  // order matters: it is the order every renderer emits.
  //
  // ⚠️ 应用内视图（带 view、非 page）必须在 index.html 的 .app-tabs 里有一份
  // 静态 <a data-view=...> 节点。app.js 的 tab 监听器是在初始化时对现有节点
  // 直接绑定的，只靠 fallback 动态创建会拿不到监听器；而 app-navigation.js 在
  // 捕获阶段已经 preventDefault，看到 data-view 又交还给应用 —— 结果是点击
  // 完全无响应。低粉爆文第一次上线就踩了这个坑。
  const items = [
    {group: '内容创作', href: '/hotspots', view: 'hotspots', label: '热点广场',
     fallback: true,
     icon: svg('<path d="M3 17l5-5 4 3 5-7 4 5"/><path d="M3 21h18"/>')},
    // 低粉爆文：小体量账号的高爆发文章榜，是选题的上游入口。
    {group: '内容创作', href: '/lowfans', view: 'lowfans', label: '低粉爆文',
     fallback: true,
     icon: svg('<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 ' +
               '.5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>')},
    {group: '内容创作', href: '/workbench', view: 'workbench', label: '公众号创作', short: '创作',
     icon: svg('<path d="M4 13.5V4a2 2 0 0 1 2-2h8.5L20 7.5V20a2 2 0 0 1-2 2h-9.5"/>' +
               '<polyline points="14 2 14 8 20 8"/><line x1="10" y1="11" x2="10" y2="17"/>' +
               '<line x1="13" y1="14" x2="7" y2="14"/>')},
    {group: '内容创作', href: '/wechat-plus', view: 'wechat-plus', label: '公众号创作 Plus',
     fallback: true,
     icon: svg('<path d="M4 4h16v12H9l-5 4z"/><path d="M9 10h6M12 7v6"/>')},
    {group: '内容创作', href: '/one-click-writing', view: 'one-click-writing',
     label: '公众号一键成文', short: '一键成文',
     icon: svg('<path d="M4 20h16M5 15l10-10 4 4-10 10H5z"/>')},
    {group: '内容创作', href: '/xiaohongshu', view: 'xiaohongshu', label: '小红书',
     icon: svg('<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/>' +
               '<polyline points="2 12 12 17 22 12"/>')},
    {group: '内容创作', href: '/tie-tu', view: 'tie-tu', label: '贴图号',
     icon: svg('<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/>' +
               '<rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>')},
    {group: '内容创作', href: '/viral-remix', view: 'viral-remix', label: '爆款贴图复刻',
     icon: svg('<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 15 3-3 2 2 3-4 2 3"/>' +
               '<circle cx="8.5" cy="8.5" r="1.2"/><path d="M16 3v4M14 5h4"/>')},
    // 小红书内容提取：应用内视图，静态页面里没有节点，标记 fallback 让渲染器建出来。
    {group: '内容创作', href: '/xhs-extract', view: 'xhs-extract', label: '小红书内容提取',
     fallback: true,
     icon: svg('<rect x="2.5" y="3.5" width="12" height="17" rx="2.5"/><path d="M19 8.5v9a2.5 2.5 0 0 1-2.5 2.5H8"/>' +
               '<path d="M7 8h4.5M7 12h3"/>')},
    // 抖音内容提取：同上，应用内视图，靠 fallback 让渲染器建出节点。
    {group: '内容创作', href: '/douyin-extract', view: 'douyin-extract', label: '抖音内容提取',
     fallback: true,
     icon: svg('<path d="M15.5 3v9.2a3.6 3.6 0 1 1-3.1-3.57"/><path d="M15.5 5.4a5 5 0 0 0 4.3 4.2"/>' +
               '<rect x="2.5" y="2.5" width="19" height="19" rx="5.5" opacity=".35"/>')},
    // 早安祝福入口在页面上暂时隐藏，但清单保留（渲染器找不到节点会跳过）。
    {group: '内容创作', href: '/morning-generator', view: 'morning', label: '早安祝福',
     hidden: true,
     icon: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/>' +
               '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>' +
               '<path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/>' +
               '<path d="m19.07 4.93-1.41 1.41"/>')},
    // 账号诊断入口暂时隐藏：上游数据源（Redfox）额度用尽，任何查询都会失败，
    // 先不让人点进去。路由与 #diagnose 章节都保留，恢复时删掉 hidden: true，
    // 再把 index.html / bookshelf.html / market.html / qihaoshou.html 里注释掉
    // 的导航节点放开即可。
    {group: '分析', href: '/diagnose', view: 'diagnose', label: '账号诊断',
     hidden: true,
     icon: svg('<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>')},
    {group: '分析', href: '/hit-detector', view: 'hit-detector', label: '发布前复核',
     icon: svg('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 ' +
               '1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>' +
               '<polyline points="9 12 11 14 15 10"/>')},
    {group: '资源', href: '/market', view: 'market', label: 'AI 超市', short: '超市',
     icon: svg('<path d="M3 7h18l-1.4 12.1a2 2 0 0 1-2 1.9H6.4a2 2 0 0 1-2-1.9z"/>' +
               '<path d="M8 7V5.5a4 4 0 0 1 8 0V7"/>')},
    // 独立页面（服务端渲染），不是应用内视图：不能带 view，
    // 否则 app-navigation.js 会拦下点击、SPA 把内容区清空 → 白屏。
    {group: '资源', href: '/bookshelf', view: 'bookshelf', label: 'AI 书架',
     icon: svg('<path d="M4 4h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v15h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4z"/>' +
               '<path d="M12 5v15"/>')},
    {group: '账户', href: '/pricing', label: '积分套餐', page: true,
     fallback: true,
     icon: svg('<rect x="2" y="6" width="20" height="13" rx="2.5"/><path d="M2 10h20"/><path d="M6 15h4"/>')},
  ];

  const groups = ['内容创作', '分析', '资源', '账户'];
  const all = [home, ...items];
  const normalize = (path) => (path || '/').replace(/\/+$/, '') || '/';
  /* 隐藏项不进任何渲染器的菜单，但路由照样能解析（可直接访问 URL、可被
     程序跳转）。早安祝福是历史遗留例外：它只在侧栏里保留条目。 */
  const inMenu = (item) => !item.hidden || item.href === '/morning-generator';

  return {
    home,
    items,
    groups,
    /* shell.js: [href, label, short?] in sidebar order (hidden entries dropped). */
    shellRoutes: all
      .filter(inMenu)
      .map((item) => (item.short ? [item.href, item.label, item.short] : [item.href, item.label])),
    /* notion-workspace.js: [[groupLabel, [href...]], ...] */
    notionPlan: groups.map((group) => [group, items
      .filter((i) => i.group === group && inMenu(i)).map((i) => i.href)]),
    /* notion-workspace.js: nodes to create when the page lacks them. */
    extras: items.filter((item) => item.fallback && inMenu(item)),
    /* 只有应用内视图才返回；独立页面返回 undefined，交给浏览器正常跳转。 */
    viewFor: (path) => {
      const match = all.find((item) => item.href === normalize(path));
      return (match && !match.page && match.view) || undefined;
    },
    itemFor: (href) => all.find((item) => item.href === href),
  };
})();
