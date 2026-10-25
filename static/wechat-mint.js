/* Desktop material only: keep every existing composer, route and event handler. */
(() => {
  const workspace = document.getElementById('workbench');
  if (!workspace) return;
  const desktop = matchMedia('(min-width: 1101px)');
  const sync = () => document.body.classList.toggle('mint-wechat', desktop.matches && !workspace.hidden);
  new MutationObserver(sync).observe(workspace, {attributes:true, attributeFilter:['hidden']});
  desktop.addEventListener('change', sync);
  const stages = document.getElementById('workbench-stage-nav');
  if (stages) {
    const syncStages = () => stages.querySelectorAll('button').forEach(button => {
      button.dataset.mintComplete = String(button.querySelector('small')?.textContent.trim() === '已完成');
    });
    new MutationObserver(syncStages).observe(stages, {childList:true, subtree:true, characterData:true});
    syncStages();
  }
  sync();
})();
