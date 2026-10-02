// SSC Saathi offline cache. Bump VERSION on every deploy.
const VERSION = "ssc-v1";
const SHELL = ["./", "index.html", "config.js", "manifest.webmanifest", "icons/icon-192.png", "icons/icon-512.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== VERSION && k !== "ssc-audio").map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api/")) return;
  if (u.origin === location.origin && u.pathname.includes("/audio/")) {
    // lesson audio: cache after first play so it works offline later
    e.respondWith(caches.open("ssc-audio").then(async c => (await c.match(e.request)) || fetch(e.request).then(r => { if (r.ok) c.put(e.request, r.clone()); return r; })));
    return;
  }
  if (u.origin === location.origin) {
    // app shell: network first (fresh deploys), cache fallback offline
    e.respondWith(fetch(e.request).then(r => { if (r.ok) caches.open(VERSION).then(c => c.put(e.request, r.clone())); return r; }).catch(() => caches.match(e.request).then(m => m || caches.match("index.html"))));
    return;
  }
  if (/fonts\.(googleapis|gstatic)\.com/.test(u.host)) {
    e.respondWith(caches.open(VERSION).then(async c => (await c.match(e.request)) || fetch(e.request).then(r => { c.put(e.request, r.clone()); return r; })));
  }
});
