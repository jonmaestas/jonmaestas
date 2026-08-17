// pwa-test service worker — scoped to /pwa-test/ only (shared-origin GH Pages)
const CACHE_VER = "v1-20260817002828"; // rewritten by scripts/bump-pwa-test-build.sh
const CACHE = "pwa-test-" + CACHE_VER;
// NOTE: self.registration is NOT reliable here (threw during eval AND in the
// fetch handler — verified by bisect + console capture). Use self.location
// (the SW script URL) instead: strip the filename -> app directory.
const APP_DIR = self.location.pathname.replace(/[^\/]*$/, "");

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll([
      "./",
      "./index.html",
      "./manifest.webmanifest",
      "./build.json",
      "./icons/icon-192.png",
      "./icons/icon-512.png"
    ]).catch(() => {});
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  const d = event.data;
  if (d === "SKIP_WAITING" || (d && d.type === "SKIP_WAITING")) self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  let url;
  try { url = new URL(req.url); } catch (_) { return; }
  if (url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith(APP_DIR)) return; // never touch other jonmaestas.com apps
  if (url.pathname.endsWith("sw.js") || url.pathname.endsWith("build.json")) return; // always network
  if (req.mode === "navigate") { event.respondWith(networkFirst(req)); return; }
  event.respondWith(staleWhileRevalidate(req));
});

async function networkFirst(req) {
  const cache = await caches.open(CACHE);
  try {
    const fresh = await fetch(req);
    if (fresh && fresh.ok) cache.put(req, fresh.clone());
    return fresh;
  } catch (_) {
    const cached = await cache.match(req, { ignoreSearch: true });
    if (cached) return cached;
    const shell = await cache.match("./index.html", { ignoreSearch: true });
    if (shell) return shell;
    return new Response("offline and not cached", { status: 503, statusText: "offline" });
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(req, { ignoreSearch: true });
  const refresh = fetch(req)
    .then((res) => { if (res && res.ok) cache.put(req, res.clone()); return res; })
    .catch(() => null);
  return cached || (await refresh) || new Response("offline", { status: 503 });
}
