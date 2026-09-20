const CACHE_NAME = "unicamplink-pwa-v4";

const APP_SHELL = [
    "/dashboard",
    "/static/style.css",
    "/static/js/theme.js",
    "/static/images/unicamplink-logo.png"
];


/* =========================================================
   INSTALL
   ========================================================= */

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => cache.addAll(APP_SHELL))
            .then(() => self.skipWaiting())
    );
});


/* =========================================================
   ACTIVATE
   ========================================================= */

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


/* =========================================================
   PUSH NOTIFICATION
   ========================================================= */

self.addEventListener("push", event => {

    let data = {
        title: "UniCamplink",
        message: "You have a new notification.",
        link: "/notifications"
    };

    if (event.data) {
        try {
            data = {
                ...data,
                ...event.data.json()
            };
        } catch (error) {
            console.error(
                "UniCamplink push data error:",
                error
            );
        }
    }

    const title = data.title || "UniCamplink";

    const options = {
        body: data.message || "You have a new notification.",

        icon: "/static/icons/icon-192.png",

        badge: "/static/icons/icon-192.png",

        tag: data.tag || "unicamplink-notification",

        data: {
            link: data.link || "/notifications"
        },

        requireInteraction: false
    };

    event.waitUntil(
        self.registration.showNotification(
            title,
            options
        )
    );
});


/* =========================================================
   NOTIFICATION CLICK
   ========================================================= */

self.addEventListener("notificationclick", event => {

    event.notification.close();

    const link =
        event.notification.data?.link ||
        "/notifications";

    event.waitUntil(

        clients.matchAll({
            type: "window",
            includeUncontrolled: true
        })

        .then(clientList => {

            for (const client of clientList) {

                if (
                    client.url.startsWith(
                        self.location.origin
                    ) &&
                    "focus" in client
                ) {

                    return client.focus().then(() => {

                        if ("navigate" in client) {
                            return client.navigate(link);
                        }

                    });

                }
            }

            if (clients.openWindow) {
                return clients.openWindow(link);
            }

        })

    );
});


/* =========================================================
   FETCH / CACHE
   ========================================================= */

self.addEventListener("fetch", event => {

    const request = event.request;

    // Only handle GET requests.
    if (request.method !== "GET") {
        return;
    }

    const url = new URL(request.url);

    // Only handle UniCamplink requests.
    if (url.origin !== self.location.origin) {
        return;
    }

    // Never cache API or authentication-sensitive routes.
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

    // Network-first for pages.
    if (request.mode === "navigate") {

        event.respondWith(
            fetch(request)
                .then(response => response)
                .catch(() => caches.match("/dashboard"))
        );

        return;
    }

    // Cache-first for static assets.
    if (url.pathname.startsWith("/static/")) {

        event.respondWith(

            caches.match(request)
                .then(cachedResponse => {

                    if (cachedResponse) {
                        return cachedResponse;
                    }

                    return fetch(request)
                        .then(response => {

                            if (
                                response &&
                                response.ok
                            ) {

                                const responseClone =
                                    response.clone();

                                caches.open(CACHE_NAME)
                                    .then(cache => {
                                        cache.put(
                                            request,
                                            responseClone
                                        );
                                    });
                            }

                            return response;
                        });

                })

        );
    }

});