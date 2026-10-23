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
  // Open AI 超市 / AI 书架 in an in-app overlay: the sidebar stays put.
  const overlay = document.querySelector("#library-overlay");
  const overlayFrame = document.querySelector("#library-overlay-frame");
  const overlayTitle = document.querySelector("#library-overlay-title");
  const overlayClose = document.querySelector("#library-overlay-close");
  if (overlay && overlayFrame && overlayTitle && overlayClose) {
    const closeLibrary = () => {
      overlay.hidden = true;
      overlayFrame.src = "about:blank";
      document.body.classList.remove("library-open");
    };
    const openLibrary = (href, title) => {
      const separator = href.includes("?") ? "&" : "?";
      overlayTitle.textContent = title || "资料库";
      overlayFrame.src = `${href}${separator}embed=1`;
      overlay.hidden = false;
      document.body.classList.add("library-open");
      overlayClose.focus();
    };
    document.addEventListener(
      "click",
      (event) => {
        const link = event.target.closest("a[data-library-link]");
        if (!link) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        openLibrary(link.getAttribute("href"), link.textContent.trim());
      },
      true
    );
    overlayClose.addEventListener("click", closeLibrary);
    document.addEventListener("click", (event) => {
      if (overlay.hidden) return;
      if (overlay.contains(event.target)) return;
      if (event.target.closest("a[data-library-link]")) return;
      closeLibrary();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !overlay.hidden) closeLibrary();
    });
  }
})();
