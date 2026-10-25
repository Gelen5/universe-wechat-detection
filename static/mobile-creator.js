/* Keep the phone composer above the software keyboard without moving its DOM. */
(() => {
  const root = document.getElementById('workbench');
  if (!root) return;
  const phone = matchMedia('(max-width:600px)');
  const viewport = window.visualViewport;
  const sync = () => {
    const active = phone.matches && !root.hidden;
    const height = viewport?.height || innerHeight;
    root.style.setProperty('--mobile-viewport-height', `${Math.round(height)}px`);
    const editing = root.contains(document.activeElement) && document.activeElement.matches('input,textarea,[contenteditable="true"]');
    document.body.classList.toggle('mobile-writing-keyboard', active && editing && innerHeight - height > 120);
  };
  viewport?.addEventListener('resize', sync);
  window.addEventListener('resize', sync);
  document.addEventListener('focusin', sync);
  document.addEventListener('focusout', () => requestAnimationFrame(sync));
  new MutationObserver(sync).observe(root, {attributes:true,attributeFilter:['hidden']});
  sync();
})();
