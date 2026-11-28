// Share Expense service worker. Served from /sw.js by apps/trips/offline.py; read that file first.
// Pages: show the stored copy at once, fetch the fresh copy, and send it to the page if it changed.
// Static files: their names change with their content, so a stored copy is always right.
// Any change (a POST: save, delete, log in, log out) deletes every stored page.
const VERSION = "{{ version }}";
const PAGES = "pages-" + VERSION;
const STATIC = "static-" + VERSION;
const STATIC_FILES = [{% for f in static_files %}"{{ f }}"{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(STATIC).then((c) => c.addAll(STATIC_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== PAGES && k !== STATIC).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isLogin(response) {
  return new URL(response.url).pathname.startsWith("/accounts/login/");
}

// A trip page that now answers 403 or 404: the person was removed from the trip, or it was
// deleted. Its stored copy must not be shown again.
function isGoneTripPage(request, response) {
  return (response.status === 403 || response.status === 404) &&
    new URL(request.url).pathname.startsWith("/trips/");
}

async function fetchAndStore(request) {
  const response = await fetch(request);
  const cache = await caches.open(PAGES);
  if (response.redirected && isLogin(response)) {
    // The session ended: nothing stored may be shown any more.
    await caches.delete(PAGES);
  } else if (isGoneTripPage(request, response)) {
    await cache.delete(request.url, { ignoreVary: true });
  } else if (response.ok && response.headers.get("X-SW-Cache") === "page") {
    await cache.put(request.url, response.clone());
  } else {
    await cache.delete(request.url);
  }
  return response;
}

async function notify(clientId, message) {
  const client = clientId && (await self.clients.get(clientId));
  if (client) client.postMessage(message);
}

async function page(event) {
  const { request } = event;
  const stored = await caches.match(request.url, { cacheName: PAGES, ignoreVary: true });
  const fresh = fetchAndStore(request);
  if (!stored) return fresh;
  const clientId = event.resultingClientId || event.clientId;
  event.waitUntil(
    fresh.then(async (response) => {
      if (response.redirected && isLogin(response)) return notify(clientId, { type: "reload" });
      // The stored copy is on screen but the trip is no longer open to this person: reload,
      // which now shows the server's answer (the stored copy was deleted above).
      if (isGoneTripPage(request, response)) return notify(clientId, { type: "reload" });
      if (!response.ok || response.headers.get("X-Page-Hash") === stored.headers.get("X-Page-Hash")) return;
      notify(clientId, { type: "update", url: request.url, html: await response.clone().text() });
    }).catch(() => {})  // Offline: the stored copy stays on screen.
  );
  return stored;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method !== "GET") {
    event.waitUntil(caches.delete(PAGES));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request, { cacheName: STATIC }).then((hit) => hit || fetch(request).then((response) => {
        if (response.ok) caches.open(STATIC).then((c) => c.put(request, response.clone()));
        return response;
      }))
    );
    return;
  }
  const accept = request.headers.get("Accept") || "";
  if (request.mode === "navigate" || request.headers.get("HX-Request") || accept.includes("text/html")) {
    event.respondWith(page(event));
  }
});
