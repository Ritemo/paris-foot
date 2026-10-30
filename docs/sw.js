const V = "pf-v13";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin || e.request.method !== "GET") return;
  // reseau d'abord (donnees et appli toujours a jour), cache si hors ligne
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then((r) => { if (!u.pathname.includes("/data/")) caches.open(V).then((c) => c.put(e.request, r.clone())); return r; })
    .catch(() => caches.match(e.request, { ignoreSearch: true })));
});
