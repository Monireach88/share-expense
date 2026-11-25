// Fast repeat visits: registers the service worker (templates/sw.js) and applies its updates.
// The app works without this file; every page is still rendered by the server.
(function () {
  if (!("serviceWorker" in navigator) || window.__seReady) return;
  window.__seReady = true;
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});

  const busy = () => {
    const el = document.activeElement;
    return el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName);
  };

  // The worker showed a stored copy and then found a newer one: put the new content in place.
  navigator.serviceWorker.addEventListener("message", (event) => {
    const msg = event.data || {};
    if (msg.type === "reload") return location.reload();
    if (msg.type !== "update" || msg.url.split("#")[0] !== location.href.split("#")[0] || busy()) return;
    const doc = new DOMParser().parseFromString(msg.html, "text/html");
    const y = window.scrollY;
    document.title = doc.title;
    document.body.innerHTML = doc.body.innerHTML;
    if (window.htmx) htmx.process(document.body);
    window.scrollTo(0, y);
  });

  // Fetch the other tabs of a trip once in the background, so the first tap on them is instant.
  async function warm() {
    if (!navigator.serviceWorker.controller || !window.caches) return;
    for (const link of document.querySelectorAll(".tabbar a:not([aria-current])")) {
      if (await caches.match(link.href, { ignoreVary: true })) continue;
      fetch(link.href, { headers: { Accept: "text/html" }, credentials: "same-origin" }).catch(() => {});
    }
  }
  const later = (fn) => (window.requestIdleCallback ? requestIdleCallback(fn) : setTimeout(fn, 500));
  document.addEventListener("DOMContentLoaded", () => later(warm));
  document.addEventListener("htmx:afterSettle", () => later(warm));
})();
