const CACHE_NAME = "unicamplink-pwa-v2";

const APP_SHELL = [
    "/dashboard",
    "/static/style.css",
    "/static/js/theme.js",
    "/static/images/unicamplink-logo.png"
];

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(APP_SHELL))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys
                    .filter(key => key !== CACHE_NAME)
                    .map(key => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", event => {

    const request = event.request;

    // Only handle normal GET requests.
    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);

    // Only handle requests belonging to UniCamplink.
    if (url.origin !== self.location.origin) {
        return;
    }

    // Never cache API requests or private/auth-sensitive pages.
    if (
        url.pathname.startsWith("/api/") ||
        url.pathname === "/login" ||
        url.pathname === "/logout" ||
        url.pathname === "/register" ||
        url.pathname === "/messages" ||
        url.pathname === "/notifications"
    ) {
        return;
    }

    // Network first for normal pages.
    if (request.mode === "navigate") {

        event.respondWith(
            fetch(request)
                .then(response => response)
                .catch(() => caches.match("/dashboard"))
        );

        return;
    }

    // Cache-first only for static assets.
    if (
        url.pathname.startsWith("/static/")
    ) {

        event.respondWith(
            caches.match(request)
                .then(cachedResponse => {

                    if (cachedResponse) {
                        return cachedResponse;
                    }

                    return fetch(request).then(response => {

                        if (response && response.ok) {

                            const responseClone = response.clone();

                            caches.open(CACHE_NAME)
                                .then(cache => {
                                    cache.put(request, responseClone);
                                });
                        }

                        return response;
                    });

                })
        );

    }

});