const CACHE = "stock-lens-shell-v3";
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(["/", "/icon.svg", "/manifest.webmanifest"])),
  );
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k.startsWith("stock-lens-shell-") && k !== CACHE)
            .map((k) => caches.delete(k)),
        ),
      ),
  );
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (
    u.origin !== location.origin ||
    u.pathname.startsWith("/api/") ||
    e.request.method !== "GET"
  )
    return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok) {
          const clone = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, clone));
        }
        return r;
      })
      .catch(async () => {
        return (
          (await caches.match(e.request)) ||
          (e.request.mode === "navigate" ? await caches.match("/") : null) ||
          new Response("离线资源未缓存", { status: 503 })
        );
      }),
  );
});
