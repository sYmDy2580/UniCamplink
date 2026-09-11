(() => {
    "use strict";

    const API_URL = "/api/notifications/unread";
    const STORAGE_KEY = "unicamplink-last-notification-id";
    const POLL_INTERVAL = 5000;

    let lastNotificationId = Number(
        localStorage.getItem(STORAGE_KEY) || 0
    );

    let polling = false;

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function getIcon(type) {
        const icons = {
            post: "📝",
            like: "❤️",
            comment: "💬",
            message: "💬",
            friend_request: "👥",
            friend_accepted: "✅"
        };

        return icons[type] || "🔔";
    }

    function ensureContainer() {
        let container = document.getElementById(
            "unicamplink-notification-container"
        );

        if (!container) {
            container = document.createElement("div");
            container.id = "unicamplink-notification-container";
            container.className =
                "unicamplink-notification-container";

            container.setAttribute("aria-live", "polite");
            container.setAttribute("aria-atomic", "false");

            document.body.appendChild(container);
        }

        return container;
    }

    function showNotification(notification) {
        const container = ensureContainer();

        const toast = document.createElement("div");

        toast.className = "unicamplink-notification-popup";

        const senderName = escapeHtml(
            notification.sender_name || "UniCamplink"
        );

        const message = escapeHtml(
            notification.message ||
            "You have a new notification."
        );

        const link = notification.link || "/notifications";

        toast.innerHTML = `
            <div class="unicamplink-notification-icon">
                ${getIcon(notification.type)}
            </div>

            <div class="unicamplink-notification-content">
                <div class="unicamplink-notification-title">
                    New notification
                </div>

                <div class="unicamplink-notification-sender">
                    ${senderName}
                </div>

                <div class="unicamplink-notification-message">
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

        const closeButton = toast.querySelector(
            ".unicamplink-notification-close"
        );

        closeButton.addEventListener("click", (event) => {
            event.stopPropagation();
            removeToast(toast);
        });

        toast.addEventListener("click", () => {
            window.location.href = link;
        });

        container.appendChild(toast);

        requestAnimationFrame(() => {
            toast.classList.add("show");
        });

        const timeout = setTimeout(() => {
            removeToast(toast);
        }, 6500);

        toast.dataset.timeout = String(timeout);
    }

    function removeToast(toast) {
        if (!toast || !toast.isConnected) {
            return;
        }

        const timeout = Number(toast.dataset.timeout);

        if (timeout) {
            clearTimeout(timeout);
        }

        toast.classList.remove("show");
        toast.classList.add("hide");

        setTimeout(() => {
            toast.remove();
        }, 300);
    }

    /* =========================================================
       UNREAD NOTIFICATION BADGE
    ========================================================= */

    function updateNotificationBadge(count) {
        const notificationLinks =
            document.querySelectorAll(
                ".notification-nav-link"
            );

        notificationLinks.forEach((link) => {
            let badge = link.querySelector(
                ".unicamplink-notification-badge"
            );

            if (count > 0) {
                if (!badge) {
                    badge = document.createElement("span");

                    badge.className =
                        "unicamplink-notification-badge";

                    link.appendChild(badge);
                }

                badge.textContent =
                    count > 99
                        ? "99+"
                        : String(count);

                badge.setAttribute(
                    "aria-label",
                    count +
                    " unread notifications"
                );

            } else if (badge) {
                badge.remove();
            }
        });
    }

    async function checkNotifications() {
        if (
            polling ||
            document.visibilityState === "hidden"
        ) {
            return;
        }

        polling = true;

        try {
            const response = await fetch(
                `${API_URL}?after_id=${encodeURIComponent(
                    lastNotificationId
                )}`,
                {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json"
                    },
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                return;
            }

            const data = await response.json();

            /* Update unread badge */
            updateNotificationBadge(
                Number(data.unread_count || 0)
            );

            const notifications =
                Array.isArray(data.notifications)
                    ? data.notifications
                    : [];

            notifications.forEach(
                (notification) => {
                    const id = Number(
                        notification.id || 0
                    );

                    if (
                        id > lastNotificationId
                    ) {
                        showNotification(
                            notification
                        );

                        lastNotificationId = id;
                    }
                }
            );

            if (lastNotificationId > 0) {
                localStorage.setItem(
                    STORAGE_KEY,
                    String(lastNotificationId)
                );
            }

        } catch (error) {
            // Keep the notification system silent
            // when the network is unavailable.
        } finally {
            polling = false;
        }
    }

    function startNotificationPolling() {
        if (!document.body) {
            return;
        }

        ensureContainer();

        checkNotifications();

        setInterval(
            checkNotifications,
            POLL_INTERVAL
        );
    }

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