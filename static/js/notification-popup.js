(() => {
    "use strict";

    /* =========================================================
       UNICAMPLINK NOTIFICATION SYSTEM
       Razor / Facebook-style notification behavior
       ========================================================= */

    const API_URL =
        "/api/notifications/unread";

    const STORAGE_KEY =
        "unicamplink-last-notification-id";

    const POLL_INTERVAL = 5000;

    let lastNotificationId = Number(
        localStorage.getItem(STORAGE_KEY) || 0
    );

    let polling = false;


    /* =========================================================
       SECURITY
       ========================================================= */

    function escapeHtml(value) {

        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }


    /* =========================================================
       NOTIFICATION ICONS
       ========================================================= */

    function getIcon(type) {

        const icons = {

            post: "📝",

            like: "❤️",

            comment: "💬",

            reply: "↩️",

            message: "💬",

            friend_request: "👥",

            friend_accepted: "✅",

            announcement: "📢"
        };

        return icons[type] || "🔔";
    }


    /* =========================================================
       NOTIFICATION CONTAINER
       ========================================================= */

    function ensureContainer() {

        let container =
            document.getElementById(
                "unicamplink-notification-container"
            );

        if (!container) {

            container =
                document.createElement("div");

            container.id =
                "unicamplink-notification-container";

            container.className =
                "unicamplink-notification-container";

            container.setAttribute(
                "aria-live",
                "polite"
            );

            container.setAttribute(
                "aria-atomic",
                "false"
            );

            document.body.appendChild(
                container
            );
        }

        return container;
    }


    /* =========================================================
   MARK NOTIFICATION AS READ
   ========================================================= */

async function markNotificationAsRead(
    notificationId
) {

    if (!notificationId) {
        return false;
    }

    try {

        /*
         * Get the Flask-WTF CSRF token
         * from the page.
         */

        const csrfToken =
            document
                .querySelector(
                    'meta[name="csrf-token"]'
                )
                ?.getAttribute("content");


        if (!csrfToken) {

            console.error(
                "UniCamplink: CSRF token not found."
            );

            return false;
        }


        const response =
            await fetch(
                `/api/notifications/${notificationId}/read`,
                {
                    method: "POST",

                    credentials:
                        "same-origin",

                    headers: {

                        "Accept":
                            "application/json",

                        "Content-Type":
                            "application/json",

                        "X-CSRFToken":
                            csrfToken
                    },

                    body:
                        JSON.stringify({})
                }
            );


        if (!response.ok) {

            console.error(
                "Unable to mark notification as read:",
                response.status
            );

            return false;
        }


        const data =
            await response.json();


        return (
            data.success === true
        );


    } catch (error) {

        console.error(
            "Unable to mark notification as read:",
            error
        );

        return false;
    }
}


    /* =========================================================
       SHOW NOTIFICATION
       ========================================================= */

    function showNotification(
        notification
    ) {

        const container =
            ensureContainer();

        const toast =
            document.createElement("div");

        toast.className =
            "unicamplink-notification-popup";

        const senderName =
            escapeHtml(
                notification.sender_name ||
                "UniCamplink"
            );

        const message =
            escapeHtml(
                notification.message ||
                "You have a new notification."
            );

        const link =
            notification.link ||
            "/notifications";

        const icon =
            getIcon(
                notification.type
            );

        const title =
            notification.type ===
            "announcement"

                ? "UniCamplink Announcement"

                : "New notification";


        /* =====================================================
           POPUP HTML
           ===================================================== */

        toast.innerHTML = `

            <div
                class="unicamplink-notification-icon"
                aria-hidden="true"
            >
                ${icon}
            </div>


            <div
                class="unicamplink-notification-content"
            >

                <div
                    class="unicamplink-notification-title"
                >
                    ${title}
                </div>


                <div
                    class="unicamplink-notification-sender"
                >
                    ${senderName}
                </div>


                <div
                    class="unicamplink-notification-message"
                >
                    ${message}
                </div>

            </div>


            <button
                type="button"
                class="unicamplink-notification-close"
                aria-label="Close notification"
            >
                ×
            </button>

        `;


        /* =====================================================
           CLOSE BUTTON
           ===================================================== */

        const closeButton =
            toast.querySelector(
                ".unicamplink-notification-close"
            );


        if (closeButton) {

            closeButton.addEventListener(
                "click",
                (event) => {

                    event.preventDefault();

                    event.stopPropagation();

                    removeToast(toast);
                }
            );
        }


        /* =====================================================
           NOTIFICATION CLICK
           ===================================================== */

        toast.addEventListener(
    "click",
    () => {

        const notificationId =
            Number(
                notification.id || 0
            );

        console.log(
            "UniCamplink notification clicked:",
            {
                id: notificationId,
                type: notification.type,
                link: link,
                message: notification.message
            }
        );

        /*
         * Mark as read in the background.
         *
         * Do NOT wait for this request before
         * opening the destination.
         */
        if (notificationId) {

            markNotificationAsRead(
                notificationId
            ).catch((error) => {

                console.error(
                    "Notification read update failed:",
                    error
                );

            });

        }

        /*
         * Remove popup immediately.
         */
        removeToast(toast);

        /*
         * Open the actual notification destination
         * immediately.
         */
        if (link) {

            window.location.assign(
                link
            );

        } else {

            window.location.assign(
                "/dashboard"
            );

        }

    }
);


        /* =====================================================
           ADD POPUP
           ===================================================== */

        container.appendChild(
            toast
        );


        /* =====================================================
           ANIMATION
           ===================================================== */

        requestAnimationFrame(() => {

            toast.classList.add(
                "show"
            );

        });


        /* =====================================================
           AUTO DISMISS
           ===================================================== */

        const timeout =
            setTimeout(
                () => {

                    removeToast(
                        toast
                    );

                },
                6500
            );


        toast.dataset.timeout =
            String(timeout);
    }


    /* =========================================================
       REMOVE POPUP
       ========================================================= */

    function removeToast(
        toast
    ) {

        if (
            !toast ||
            !toast.isConnected
        ) {
            return;
        }


        const timeout =
            Number(
                toast.dataset.timeout
            );


        if (timeout) {

            clearTimeout(
                timeout
            );
        }


        toast.classList.remove(
            "show"
        );


        toast.classList.add(
            "hide"
        );


        setTimeout(
            () => {

                if (
                    toast.isConnected
                ) {

                    toast.remove();
                }

            },
            300
        );
    }


    /* =========================================================
       UNREAD NOTIFICATION BADGE
       ========================================================= */

    function updateNotificationBadge(
        count
    ) {

        const notificationLinks =
            document.querySelectorAll(
                ".notification-nav-link"
            );


        notificationLinks.forEach(
            (link) => {

                let badge =
                    link.querySelector(
                        ".unicamplink-notification-badge"
                    );


                if (count > 0) {

                    if (!badge) {

                        badge =
                            document.createElement(
                                "span"
                            );

                        badge.className =
                            "unicamplink-notification-badge";

                        link.appendChild(
                            badge
                        );
                    }


                    badge.textContent =
                        count > 99
                            ? "99+"
                            : String(count);


                    badge.setAttribute(
                        "aria-label",
                        `${count} unread notifications`
                    );


                } else if (badge) {

                    badge.remove();
                }

            }
        );
    }


    /* =========================================================
       CHECK NOTIFICATIONS
       ========================================================= */

    async function checkNotifications() {

        if (
            polling ||
            document.visibilityState ===
            "hidden"
        ) {
            return;
        }


        polling = true;


        try {

            const response =
                await fetch(
                    `${API_URL}?after_id=${encodeURIComponent(
                        lastNotificationId
                    )}`,
                    {
                        method: "GET",

                        credentials:
                            "same-origin",

                        headers: {
                            "Accept":
                                "application/json"
                        },

                        cache:
                            "no-store"
                    }
                );


            if (!response.ok) {

                return;
            }


            const data =
                await response.json();


            /* =================================================
               UPDATE UNREAD BADGE
               ================================================= */

            updateNotificationBadge(
                Number(
                    data.unread_count || 0
                )
            );


            /* =================================================
               GET NOTIFICATIONS
               ================================================= */

            const notifications =
                Array.isArray(
                    data.notifications
                )
                    ? data.notifications
                    : [];


            /* =================================================
               SHOW NEW NOTIFICATIONS
               ================================================= */

            notifications.forEach(
                (notification) => {

                    const id =
                        Number(
                            notification.id ||
                            0
                        );


                    if (
                        id >
                        lastNotificationId
                    ) {

                        showNotification(
                            notification
                        );


                        lastNotificationId =
                            id;
                    }

                }
            );


            /* =================================================
               SAVE LAST NOTIFICATION ID
               ================================================= */

            if (
                lastNotificationId >
                0
            ) {

                localStorage.setItem(
                    STORAGE_KEY,
                    String(
                        lastNotificationId
                    )
                );
            }


        } catch (error) {

            /*
             * Keep the notification system
             * running even if the network
             * temporarily fails.
             */

            console.error(
                "UniCamplink notification error:",
                error
            );


        } finally {

            polling = false;
        }
    }


    /* =========================================================
       START NOTIFICATION POLLING
       ========================================================= */

    function startNotificationPolling() {

        if (!document.body) {

            return;
        }


        ensureContainer();


        /*
         * Check immediately.
         */

        checkNotifications();


        /*
         * Continue checking every 5 seconds.
         */

        setInterval(
            checkNotifications,
            POLL_INTERVAL
        );
    }


    /* =========================================================
       START SYSTEM
       ========================================================= */

    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            startNotificationPolling
        );

    } else {

        startNotificationPolling();
    }

})();