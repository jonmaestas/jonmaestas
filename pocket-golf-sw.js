/* Pocket Golf service worker — installable PWA + local notification relay */
const CACHE = "pocket-golf-v1";
const PRECACHE = [
  "./pocket-golf.html",
  "./pocket-golf-build.json",
  "./pocket-golf.webmanifest",
  "./icons/pocket-golf-192.png",
  "./icons/pocket-golf-512.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Network-first for HTML/JSON so deploys win; cache fallback offline
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  const isDoc =
    req.mode === "navigate" ||
    url.pathname.endsWith("pocket-golf.html") ||
    url.pathname.endsWith("pocket-golf-build.json");

  if (isDoc) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((m) => m || caches.match("./pocket-golf.html")))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => {
      const net = fetch(req).then((res) => {
        if (res && res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => cached);
      return cached || net;
    })
  );
});

// Page posts {type:'notify', title, body, tag, url}
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "notify") return;
  const title = data.title || "Pocket Golf";
  const opts = {
    body: data.body || "",
    icon: "./icons/pocket-golf-192.png",
    badge: "./icons/pocket-golf-192.png",
    tag: data.tag || "pocket-golf",
    renotify: !!data.renotify,
    data: { url: data.url || "./pocket-golf.html" }
  };
  event.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "./pocket-golf.html";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.url.includes("pocket-golf") && "focus" in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});

// Ready for real Web Push later (VAPID server). Payload JSON: {title, body, tag, url}
self.addEventListener("push", (event) => {
  let payload = { title: "Pocket Golf", body: "Something happened on the course" };
  try {
    if (event.data) payload = Object.assign(payload, event.data.json());
  } catch (_) {
    try { payload.body = event.data.text(); } catch (__) {}
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || "Pocket Golf", {
      body: payload.body || "",
      icon: "./icons/pocket-golf-192.png",
      badge: "./icons/pocket-golf-192.png",
      tag: payload.tag || "pocket-golf-push",
      data: { url: payload.url || "./pocket-golf.html" }
    })
  );
});
