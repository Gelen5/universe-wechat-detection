/* Cache-independent routing for the two views added after the main app bundle.
 * Older cached app.js builds do not know these view names and hide every panel.
 */
(() => {
  const views = {
    "remove-ai-flavor": document.getElementById("remove-ai-flavor"),
    skills: document.getElementById("skills"),
  };

  function show(view) {
    const target = views[view];
    if (!target) return;
    document.querySelectorAll(".app-shell > section, .app-shell > main").forEach((node) => {
      node.hidden = node !== target;
    });
    document.querySelectorAll(".app-tabs [data-view]").forEach((node) => {
      node.classList.toggle("active", node.dataset.view === view);
    });
    document.querySelector(".app-shell")?.classList.add("workbench-active");
    if (location.pathname.replace(/\/+$/, "") !== "/" + view) {
      history.replaceState(null, "", "/" + view);
    }
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  document.addEventListener("click", (event) => {
    const tab = event.target.closest('.app-tabs [data-view="remove-ai-flavor"], .app-tabs [data-view="skills"]');
    if (!tab) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    show(tab.dataset.view);
  }, true);

  window.addEventListener("popstate", () => {
    const view = location.pathname.replace(/^\/+|\/+$/g, "");
    if (views[view]) show(view);
  });

  const initial = location.pathname.replace(/^\/+|\/+$/g, "");
  if (views[initial]) show(initial);
})();
