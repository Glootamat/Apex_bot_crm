const CACHE = "apex-react-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/assets/icons/icon-192.png"];
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || new URL(event.request.url).pathname.startsWith("/api/")) return;
  event.respondWith(fetch(event.request).then((response) => { if (response.ok && event.request.destination !== "document") { const copy = response.clone(); void caches.open(CACHE).then((cache) => cache.put(event.request, copy)); } return response; }).catch(async () => {
    const cached = await caches.match(event.request);
    if (cached) return cached;
    if (event.request.mode === "navigate") return (await caches.match("/")) ?? Response.error();
    return Response.error();
  }));
});
