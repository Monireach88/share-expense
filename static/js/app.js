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
    // Sections the reader opened (filters, days) stay open in the new copy.
    const open = [...document.querySelectorAll("details[data-keep-open][open]")].map((d) => d.dataset.keepOpen);
    document.title = doc.title;
    document.body.innerHTML = doc.body.innerHTML;
    for (const key of open) {
      const el = document.querySelector(`details[data-keep-open="${CSS.escape(key)}"]`);
      if (el) el.open = true;
    }
    if (window.htmx) htmx.process(document.body);
    if (window.__seInitReorder) window.__seInitReorder();
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

// Small page behaviours that must survive the body swap above, so they listen on the document.
(function () {
  if (window.__seUi) return;
  window.__seUi = true;
  // The "+" menu: a long press opens it like a tap; a tap anywhere else closes it.
  document.addEventListener("contextmenu", (event) => {
    const summary = event.target.closest(".fab-menu > summary");
    if (!summary) return;
    event.preventDefault();
    summary.parentElement.open = true;
  });
  // A tap outside an open menu (account menu, "+" menu), or the Escape key, closes it.
  document.addEventListener("click", (event) => {
    for (const menu of document.querySelectorAll(".fab-menu[open], details.menu[open]")) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".fab-menu[open], details.menu[open]").forEach((m) => (m.open = false));
  });

  // Drag to reorder the cards of one day (Expenses page). A long press (350 ms) starts the drag,
  // so a normal tap still opens the expense and a swipe still scrolls.
  let droppedAt = 0;
  function save(list) {
    const body = new URLSearchParams({ day: list.dataset.day });
    for (const li of list.children) body.append("ids", li.dataset.id);
    const headers = JSON.parse(document.body.getAttribute("hx-headers") || "{}");
    const saving = fetch(list.dataset.reorder, { method: "POST", headers, body, credentials: "same-origin" })
      .then((response) => { if (!response.ok) location.reload(); })
      .catch(() => location.reload());
    if (window.seBusy) window.seBusy(saving);
  }
  function initReorder() {
    if (!window.Sortable) return;
    for (const list of document.querySelectorAll("ul[data-reorder]:not([data-ready])")) {
      list.dataset.ready = "1";
      Sortable.create(list, {
        delay: 350, animation: 150, chosenClass: "chosen", ghostClass: "ghost",
        onEnd(event) {
          droppedAt = Date.now();
          if (event.oldIndex !== event.newIndex) save(list);
        },
      });
    }
  }
  // The tap that ends a drag must not also open the expense, and a long press shows no link menu.
  document.addEventListener("click", (event) => {
    if (Date.now() - droppedAt < 400 && event.target.closest("ul[data-reorder]")) event.preventDefault();
  }, true);
  document.addEventListener("contextmenu", (event) => {
    if (event.target.closest("ul[data-reorder]")) event.preventDefault();
  });
  // "Everyone" chip in a list of checkboxes (who covers a traveler): ticks or clears them all,
  // and is ticked itself exactly when every other box is.
  function syncAll(chips) {
    const all = chips.querySelector("[data-all] input");
    const boxes = [...chips.querySelectorAll("label:not([data-all]) input[type=checkbox]")];
    if (all) all.checked = boxes.length > 0 && boxes.every((box) => box.checked);
  }
  function initAll() {
    for (const label of document.querySelectorAll("[data-all][hidden]")) {
      if (label.parentElement.querySelectorAll("input[type=checkbox]").length < 3) continue;
      label.hidden = false;
      syncAll(label.parentElement);
    }
  }
  document.addEventListener("input", (event) => {
    const chips = event.target.closest(".chips");
    if (!chips || !chips.querySelector("[data-all]")) return;
    if (event.target.closest("[data-all]")) {
      for (const box of chips.querySelectorAll("label:not([data-all]) input[type=checkbox]")) {
        box.checked = event.target.checked;
      }
    } else {
      syncAll(chips);
    }
  });
  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSettle", initAll);

  window.__seInitReorder = initReorder;
  document.addEventListener("DOMContentLoaded", initReorder);
  document.addEventListener("htmx:afterSettle", initReorder);
})();

// Loading indicators: a thin bar at the top while the app waits for the server (after 150 ms, so
// instant answers do not flash), and a spinner in the pressed button, which also stops a second
// press. window.seBusy(promise) shows the bar for work done with fetch().
(function () {
  if (window.seBusy) return;
  let active = 0;
  let timer = null;
  function bar() {
    let el = document.querySelector("body > .progress");
    if (!el) {
      el = document.createElement("div");
      el.className = "progress";
      el.setAttribute("aria-hidden", "true");
      document.body.prepend(el);
    }
    return el;
  }
  function start() {
    active += 1;
    if (active === 1) timer = setTimeout(() => bar().classList.add("on"), 150);
  }
  function stop() {
    active = Math.max(0, active - 1);
    if (active) return;
    clearTimeout(timer);
    bar().classList.remove("on");
  }
  window.seBusy = (promise) => {
    start();
    return Promise.resolve(promise).finally(stop);
  };

  const PRESSABLE = "button, .btn, .fab, .chip-add";
  function loading(el, on) {
    if (!el) return;
    el.classList.toggle("is-loading", on);
    if (on) el.setAttribute("aria-busy", "true");
    else el.removeAttribute("aria-busy");
  }
  // What the user pressed for this htmx request: the form's submit button, or the link itself.
  function pressed(detail) {
    const submitter = detail.requestConfig && detail.requestConfig.triggeringEvent
      && detail.requestConfig.triggeringEvent.submitter;
    const el = submitter || detail.elt;
    return el && el.matches && el.matches(PRESSABLE) ? el : null;
  }

  document.addEventListener("htmx:beforeRequest", (event) => {
    start();
    loading(pressed(event.detail), true);
    const search = event.detail.elt.closest && event.detail.elt.closest(".search");
    if (search) search.classList.add("is-busy");
  });
  document.addEventListener("htmx:afterRequest", (event) => {
    stop();
    loading(pressed(event.detail), false);
    const search = event.detail.elt.closest && event.detail.elt.closest(".search");
    if (search) search.classList.remove("is-busy");
  });

  // Forms htmx does not send (hx-boost="false", e.g. Google sign-in) load a whole new page.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || form.method === "dialog" || !form.closest('[hx-boost="false"]')) return;
    start();
    loading(event.submitter, true);
  });
  // Coming back with the browser's Back button shows the old page from memory: clear its spinners.
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    document.querySelectorAll(".is-loading").forEach((el) => loading(el, false));
    active = 0;
    stop();
  });
})();

// "Copy" button next to a read-only field: <button data-copy="field-id" data-done="Copied">.
(function () {
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    const field = document.getElementById(button.dataset.copy);
    if (!field) return;
    field.select();
    try {
      await navigator.clipboard.writeText(field.value);
    } catch {
      return; // The text stays selected, so the person can copy it by hand.
    }
    const label = button.textContent;
    button.textContent = button.dataset.done || label;
    setTimeout(() => (button.textContent = label), 2000);
  });
})();
