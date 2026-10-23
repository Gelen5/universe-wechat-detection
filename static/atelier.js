// Legibility floor for the Atelier skin.
// The legacy screens carry 9-10px metadata in hidden panels; the design
// system keeps every readable text node at 11px or above.
(() => {
  const MIN = 11;
  const fix = () => {
    document.querySelectorAll("body *").forEach((el) => {
      const directText = [...el.childNodes].some(
        (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()
      );
      if (!directText) return;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size > 0 && size < MIN) el.style.setProperty("font-size", `${MIN}px`, "important");
    });
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", fix, { once: true });
  } else {
    fix();
  }
  new MutationObserver(() => requestAnimationFrame(fix)).observe(document.body, {
    childList: true,
    subtree: true,
  });
  window.setTimeout(fix, 1200);

  // Carry a draft from the home desk into the workbench composer.
  const draft = document.querySelector("#atelier-draft");
  const start = document.querySelector("#atelier-start-go");
  if (draft && start) {
    const forward = (event) => {
      if (event) event.preventDefault();
      const value = draft.value.trim();
      if (value) sessionStorage.setItem("universe.homeDraft", value);
      window.location.href = "/workbench";
    };
    start.addEventListener("click", forward);
    draft.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        forward();
      }
    });
  }
})();
