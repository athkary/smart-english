// Service worker: caches the app shell for fast/offline start. API calls are never cached.
const VERSION = "se-shell-v2";
const SHELL = ["./", "./index.html", "./css/app.css", "./js/app.js", "./js/api.js", "./js/config.js",
  "./js/i18n.js", "./js/ui.js", "./js/speech.js", "./manifest.webmanifest", "./icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return; // API & other origins: network only
  // Network first (so updates arrive), cache as fallback when offline.
  e.respondWith(fetch(e.request).then((res) => {
    const copy = res.clone();
    caches.open(VERSION).then((c) => c.put(e.request, copy));
    return res;
  }).catch(() => caches.match(e.request).then((r) => r || caches.match("./index.html"))));
});
