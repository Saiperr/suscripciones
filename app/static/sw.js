// Service worker mínimo: guarda solo ficheros estáticos para poder instalar la app y mostrar una pantalla sin conexión.
// Las páginas con datos del usuario NO se guardan en caché.
const V = "susc-v2";
const SHELL = ["/static/style.css", "/static/app.js", "/static/offline.html", "/static/icon-192.png"];
// Sube V cuando cambies estos ficheros para limpiar cachés antiguas.
self.addEventListener("install", e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const r = e.request;
  if (r.method !== "GET") return;
  const url = new URL(r.url);
  if (url.origin !== location.origin) return;
  if (r.mode === "navigate") {
    e.respondWith(fetch(r).catch(() => caches.match("/static/offline.html")));
  } else if (url.pathname.startsWith("/static/")) {
    // Primero la red (así los cambios de diseño llegan enseguida); la caché solo si no hay conexión.
    e.respondWith(fetch(r).then(res => {
      if (res.ok) { const copy = res.clone(); caches.open(V).then(c => c.put(r, copy)); }
      return res;
    }).catch(() => caches.match(r)));
  }
});
