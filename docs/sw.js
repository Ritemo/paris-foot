const V = "pf-1540962f";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(V).then((c) => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== V && k !== "pf-logos").map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  // logos des clubs : cache d'abord (ils ne changent pas), pour un affichage instantane et hors ligne
  if (u.hostname === "a.espncdn.com") {
    e.respondWith(caches.open("pf-logos").then((c) => c.match(e.request).then((hit) => hit || fetch(e.request).then((r) => { if (r.ok || r.type === "opaque") c.put(e.request, r.clone()); return r; }))));
    return;
  }
  if (u.origin !== location.origin || e.request.method !== "GET") return;
  // reseau d'abord (donnees et appli toujours a jour), cache si hors ligne
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then((r) => { if (!u.pathname.includes("/data/")) caches.open(V).then((c) => c.put(e.request, r.clone())); return r; })
    .catch(() => caches.match(e.request, { ignoreSearch: true })));
});
