import json
from pywebpush import webpush, WebPushException
import os
import math
import hmac
import sqlite3
from dotenv import load_dotenv
load_dotenv()
import smtplib
from email.message import EmailMessage
from urllib.parse import quote
from uuid import uuid4
from datetime import datetime, timedelta

from flask import (
    Flask,
    redirect,
    send_from_directory,
    render_template,
    request,
    session,
    url_for,
    jsonify
)

from flask_wtf.csrf import (
    CSRFProtect,
    CSRFError,
    generate_csrf
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from PIL import Image, UnidentifiedImageError


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__, static_folder=None)


# ============================================================
# SECRET KEY SECURITY
# ============================================================

SECRET_KEY = os.environ.get("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is not set. "
        "Please set it before starting UniCamplink."
    )

app.secret_key = SECRET_KEY


# ============================================================
# EMAIL / SMTP CONFIGURATION
# ============================================================

MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
MAIL_USE_TLS = (
    os.environ.get("MAIL_USE_TLS", "true").lower()
    in {"1", "true", "yes", "on"}
)
MAIL_RECIPIENT = os.environ.get(
    "MAIL_RECIPIENT",
    "daveinfinitz@gmail.com"
)

WHATSAPP_NUMBER = os.environ.get(
    "WHATSAPP_NUMBER",
    ""
).strip().replace("+", "").replace(" ", "").replace("-", "")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()


# ============================================================
# SESSION SECURITY
# ============================================================

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",

    # Keep False for local HTTP development.
    # Set SESSION_COOKIE_SECURE=true on Railway/HTTPS.
    SESSION_COOKIE_SECURE=(
        os.environ.get(
            "SESSION_COOKIE_SECURE",
            "false"
        ).lower() in {"1", "true", "yes", "on"}
    ),

    # Maximum request size: 5 MB
    MAX_CONTENT_LENGTH=5 * 1024 * 1024
)


# ============================================================
# CSRF PROTECTION
# ============================================================

csrf = CSRFProtect(app)


@app.context_processor
def inject_csrf_token():
    return {
        "csrf_token": generate_csrf
    }


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    return (
        "CSRF validation failed. "
        "Please refresh the page and try again.",
        400
    )
# ============================================================
# SAFE ERROR HANDLING
# ============================================================

@app.errorhandler(400)
def bad_request(error):
    return (
        "Bad request. Please check your input and try again.",
        400
    )


@app.errorhandler(404)
def page_not_found(error):
    return (
        "Page not found.",
        404
    )


@app.errorhandler(405)
def method_not_allowed(error):
    return (
        "Method not allowed.",
        405
    )


@app.errorhandler(413)
def request_too_large(error):
    return (
        "File or request is too large. "
        "Maximum allowed size is 5 MB.",
        413
    )


@app.errorhandler(500)
def internal_server_error(error):
    return (
        "Something went wrong on the server. "
        "Please try again later.",
        500
    )


# ============================================================
# SECURITY HEADERS
# ============================================================

@app.after_request
def add_security_headers(response):

    # Prevent MIME-type sniffing.
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Prevent the app from being embedded in iframes
    # by other origins.
    response.headers["X-Frame-Options"] = "SAMEORIGIN"

    # Limit information sent through the Referer header.
    response.headers["Referrer-Policy"] = (
        "strict-origin-when-cross-origin"
    )

    # Disable browser features that UniCamplink
    # does not currently need.
    response.headers["Permissions-Policy"] = (
        "camera=(), "
        "microphone=(), "
        "geolocation=(), "
        "payment=()"
    )

    # Prevent browsers from caching authenticated
    # pages and sensitive application responses.
    if "user_id" in session:

        response.headers["Cache-Control"] = (
            "no-store, "
            "no-cache, "
            "must-revalidate, "
            "max-age=0"
        )

        response.headers["Pragma"] = "no-cache"

    return response


# ============================================================
# POPUP NOTIFICATION ASSETS
# ============================================================

@app.after_request
def inject_notification_popup_assets(response):

    # Add the popup CSS/JavaScript automatically to every
    # HTML page, so existing templates do not need to be
    # rewritten just to enable popup notifications.
    content_type = response.headers.get("Content-Type", "")

    if (
        "text/html" in content_type
        and not response.direct_passthrough
    ):
        try:
            html = response.get_data(as_text=True)

            css_tag = (
                '<link rel="stylesheet" '
                'href="/static/css/notification-popup.css">'
            )

            js_tag = (
                '<script src="/static/js/notification-popup.js" '
                'defer></script>'
            )

            if css_tag not in html:
                if "</head>" in html.lower():
                    lower_html = html.lower()
                    head_end = lower_html.find("</head>")
                    html = (
                        html[:head_end]
                        + "\n"
                        + css_tag
                        + html[head_end:]
                    )

            if js_tag not in html:
                lower_html = html.lower()
                body_end = lower_html.rfind("</body>")

                if body_end != -1:
                    html = (
                        html[:body_end]
                        + "\n"
                        + js_tag
                        + "\n"
                        + html[body_end:]
                    )
                else:
                    html += "\n" + js_tag

            response.set_data(html)

        except (TypeError, ValueError):
            # Never allow notification UI injection to break
            # an otherwise valid page response.
            pass

    return response


# ============================================================
# INPUT VALIDATION LIMITS
# ============================================================

MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254
MAX_UNIVERSITY_LENGTH = 150
MAX_BIO_LENGTH = 500
MAX_PASSWORD_LENGTH = 128

MAX_POST_LENGTH = 5000
MAX_COMMENT_LENGTH = 2000

MAX_GROUP_NAME_LENGTH = 100
MAX_GROUP_DESCRIPTION_LENGTH = 1000

MAX_PRODUCT_NAME_LENGTH = 150
MAX_PRODUCT_DESCRIPTION_LENGTH = 3000
MAX_LOCATION_LENGTH = 150

MAX_SEARCH_LENGTH = 100

MAX_MESSAGE_LENGTH = 2000

MAX_PRICE = 1_000_000_000


# ============================================================
# MARKETPLACE CATEGORIES
# ============================================================

MARKETPLACE_CATEGORIES = [
    "Electronics",
    "Fashion",
    "Books",
    "Hostel",
    "Food",
    "Services",
    "Other"
]


# ============================================================
# PATH CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

# Railway persistent storage is supplied through
# UNICAMPLINK_DATA_DIR=/app/data.
# Locally, keep the existing database and uploads
# locations so development continues to work normally.
DATA_DIR = os.environ.get(
    "UNICAMPLINK_DATA_DIR"
)

if DATA_DIR:
    DATA_DIR = os.path.abspath(DATA_DIR)
    DATABASE = os.path.join(
        DATA_DIR,
        "database.db"
    )
    UPLOAD_FOLDER = os.path.join(
        DATA_DIR,
        "uploads"
    )
else:
    DATA_DIR = BASE_DIR
    DATABASE = os.path.join(
        BASE_DIR,
        "database.db"
    )
    UPLOAD_FOLDER = os.path.join(
        BASE_DIR,
        "static",
        "uploads"
    )

STATIC_FOLDER = os.path.join(
    BASE_DIR,
    "static"
)

ALLOWED_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif"
}

os.makedirs(
    DATA_DIR,
    exist_ok=True
)

os.makedirs(
    UPLOAD_FOLDER,
    exist_ok=True
)
# ============================================================
# WEB PUSH SUBSCRIPTIONS
# ============================================================

@app.route(
    "/api/push/subscribe",
    methods=["POST"]
)
def push_subscribe():
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "error": "Please log in."
        }), 401

    data = request.get_json(silent=True) or {}

    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}

    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return jsonify({
            "success": False,
            "error": "Invalid push subscription."
        }), 400

    conn = get_db_connection()

    try:
        conn.execute("""
            INSERT INTO push_subscriptions
                (user_id, endpoint, p256dh, auth)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint)
            DO UPDATE SET
                user_id = excluded.user_id,
                p256dh = excluded.p256dh,
                auth = excluded.auth
        """, (
            session["user_id"],
            endpoint,
            p256dh,
            auth
        ))

        conn.commit()

        return jsonify({
            "success": True,
            "message": "Push notifications enabled."
        })

    except sqlite3.Error:
        conn.rollback()

        return jsonify({
            "success": False,
            "error": "Could not save push subscription."
        }), 500

    finally:
        conn.close()


@app.route(
    "/api/push/unsubscribe",
    methods=["POST"]
)
def push_unsubscribe():
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "error": "Please log in."
        }), 401

    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")

    if not endpoint:
        return jsonify({
            "success": False,
            "error": "Missing subscription endpoint."
        }), 400

    conn = get_db_connection()

    try:
        conn.execute("""
            DELETE FROM push_subscriptions
            WHERE user_id = ?
              AND endpoint = ?
        """, (
            session["user_id"],
            endpoint
        ))

        conn.commit()

        return jsonify({
            "success": True,
            "message": "Push notifications disabled."
        })

    except sqlite3.Error:
        conn.rollback()

        return jsonify({
            "success": False,
            "error": "Could not remove push subscription."
        }), 500

    finally:
        conn.close()


@app.route("/api/push/config")
def push_config():
    if "user_id" not in session:
        return jsonify({
            "success": False,
            "error": "Please log in."
        }), 401

    public_key = os.environ.get("VAPID_PUBLIC_KEY")

    if not public_key:
        return jsonify({
            "success": False,
            "error": "Push notifications are not configured."
        }), 500

    return jsonify({
        "success": True,
        "publicKey": public_key
    })
# ============================================================
# WEB PUSH DELIVERY
# ============================================================

def send_push_notification(
    user_id,
    title,
    message,
    link="/notifications",
    tag="unicamplink-notification"
):
    """
    Send a browser push notification to all active
    subscriptions belonging to a UniCamplink user.

    This helper does not create database notifications.
    It only handles browser push delivery.
    """

    private_key = os.environ.get(
        "VAPID_PRIVATE_KEY"
    )

    claim_email = os.environ.get(
        "VAPID_CLAIM_EMAIL"
    )

    if not private_key or not claim_email:
        return 0

    conn = get_db_connection()

    try:
        subscriptions = conn.execute("""
            SELECT
                id,
                endpoint,
                p256dh,
                auth
            FROM push_subscriptions
            WHERE user_id = ?
        """, (user_id,)).fetchall()

        if not subscriptions:
            return 0

        payload = {
            "title": title,
            "message": message,
            "link": link,
            "tag": tag
        }

        sent = 0

        for subscription in subscriptions:

            subscription_info = {
                "endpoint": subscription["endpoint"],
                "keys": {
                    "p256dh": subscription["p256dh"],
                    "auth": subscription["auth"]
                }
            }

            try:
                webpush(
                    subscription_info=subscription_info,
                    data=json.dumps(payload),
                    vapid_private_key=private_key,
                    vapid_claims={
                        "sub": claim_email
                    },
                    ttl=300
                )

                sent += 1

            except WebPushException as error:

                status_code = getattr(
                    error.response,
                    "status_code",
                    None
                ) if getattr(error, "response", None) else None

                print(
                    "UniCamplink push delivery error:",
                    error
                )

                # Remove expired/invalid browser subscriptions.
                if status_code in (404, 410):

                    try:
                        conn.execute("""
                            DELETE FROM push_subscriptions
                            WHERE id = ?
                        """, (subscription["id"],))

                        conn.commit()

                    except sqlite3.Error as cleanup_error:

                        print(
                            "UniCamplink push cleanup error:",
                            cleanup_error
                        )

        return sent

    except sqlite3.Error as error:

        print(
            "UniCamplink push database error:",
            error
        )

        return 0

    finally:
        conn.close()

# ============================================================
# STATIC FILE SERVING
# ============================================================

@app.route(
    "/static/<path:filename>",
    endpoint="static"
)
def serve_static_file(filename):
    # Uploaded profile/product images are stored in the
    # persistent data directory on Railway.
    if filename == "uploads" or filename.startswith("uploads/"):
        upload_filename = filename[len("uploads/"):]

        if not upload_filename:
            return "File not found.", 404

        return send_from_directory(
            UPLOAD_FOLDER,
            upload_filename
        )

    # CSS, JavaScript and the application logo remain in
    # the normal project static directory.
    return send_from_directory(
        STATIC_FOLDER,
        filename
    )


# ============================================================
# SAFE UPLOAD PATH
# ============================================================

def safe_upload_path(filename):
    upload_root = os.path.realpath(UPLOAD_FOLDER)
    target_path = os.path.realpath(
        os.path.join(UPLOAD_FOLDER, filename)
    )

    if (
        target_path != upload_root
        and not target_path.startswith(
            upload_root + os.sep
        )
    ):
        raise ValueError("Unsafe upload path.")

    return target_path


# ============================================================
# PILLOW SECURITY
# ============================================================

# Protect against extremely large/decompression-bomb images.
Image.MAX_IMAGE_PIXELS = 16_777_216


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    conn = sqlite3.connect(
        DATABASE,
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    # Enforce foreign-key relationships.
    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    # Wait briefly instead of immediately failing
    # when another request temporarily locks the database.
    conn.execute(
        "PRAGMA busy_timeout = 5000"
    )

    return conn


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def column_exists(table_name, column_name):

    conn = get_db_connection()

    columns = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()

    conn.close()

    return any(
        column["name"] == column_name
        for column in columns
    )


def allowed_file(filename):

    return (
        "."
        in filename
        and
        filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXTENSIONS
    )


def clean_text(value, max_length):

    value = (value or "").strip()

    if len(value) > max_length:
        return None

    return value


def valid_email(email):

    if not email:
        return False

    if len(email) > MAX_EMAIL_LENGTH:
        return False

    if "@" not in email:
        return False

    if email.startswith("@") or email.endswith("@"):
        return False

    return True


# ============================================================
# SECURE IMAGE VALIDATION
# ============================================================

def validate_image(image):

    """
    Validate that an uploaded file is a genuine
    supported image.

    Security checks:

    - File must exist
    - Extension must be allowed
    - Actual file contents must be a valid image
    - Image dimensions must not exceed 4096x4096
    - File extension must match detected image format
    - Pillow decompression-bomb protection

    Returns:

        True  -> valid image
        False -> invalid or unsafe image
    """

    if not image or not image.filename:
        return False

    if not allowed_file(image.filename):
        return False

    try:

        image.seek(0)

        with Image.open(image) as img:

            detected_format = img.format

            width, height = img.size

            if width <= 0 or height <= 0:
                return False

            if width > 4096 or height > 4096:
                return False

            img.verify()

        image.seek(0)

        extension = image.filename.rsplit(
            ".",
            1
        )[1].lower()

        format_extensions = {
            "PNG": {"png"},
            "JPEG": {"jpg", "jpeg"},
            "GIF": {"gif"}
        }

        allowed_extensions_for_format = (
            format_extensions.get(
                detected_format,
                set()
            )
        )

        if extension not in allowed_extensions_for_format:
            return False

        return True

    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError
    ):

        try:
            image.seek(0)
        except Exception:
            pass

        return False


# ============================================================
# NIGERIAN TIMEZONE
# ============================================================

@app.template_filter("nigeria_time")
def nigeria_time(timestamp):

    if not timestamp:
        return ""

    try:

        utc_time = datetime.strptime(
            str(timestamp),
            "%Y-%m-%d %H:%M:%S"
        )

        nigeria_time_value = (
            utc_time + timedelta(hours=1)
        )

        return nigeria_time_value.strftime(
            "%b %d, %Y %I:%M %p"
        )

    except (ValueError, TypeError):

        return timestamp


# ============================================================
# DATABASE SETUP
# ============================================================

def create_tables():

    conn = get_db_connection()

    # ========================================================
    # USERS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            university TEXT NOT NULL,
            password TEXT NOT NULL,
            bio TEXT DEFAULT '',
            profile_picture TEXT DEFAULT '',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
        # ============================================================
    # SAFE MIGRATION — ADVERTISEMENT REQUESTS
    # ============================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS advertisement_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            business_name TEXT NOT NULL,
            advertising_type TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE SET NULL
        )
    """)

    conn.commit()

    # ========================================================
    # LOGIN ATTEMPTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            email TEXT PRIMARY KEY,
            failed_attempts INTEGER DEFAULT 0,
            locked_until TIMESTAMP
        )
    """)

    # ========================================================
    # POSTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            group_id INTEGER,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # LIKES
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            UNIQUE(post_id, user_id),

            FOREIGN KEY (post_id)
            REFERENCES posts(id)
            ON DELETE CASCADE,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # COMMENTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            parent_comment_id INTEGER,

            FOREIGN KEY (post_id)
            REFERENCES posts(id)
            ON DELETE CASCADE,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # GROUPS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            creator_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (creator_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # GROUP MEMBERS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(group_id, user_id),

            FOREIGN KEY (group_id)
            REFERENCES groups(id)
            ON DELETE CASCADE,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # MARKETPLACE
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            location TEXT NOT NULL,
            image TEXT DEFAULT '',
            status TEXT DEFAULT 'available',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (seller_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # PRIVATE MESSAGES
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read INTEGER DEFAULT 0,

            FOREIGN KEY (sender_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (receiver_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # NOTIFICATIONS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            sender_id INTEGER,
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (sender_id)
            REFERENCES users(id)
            ON DELETE SET NULL
        )
    """)

    # ========================================================
    # FRIEND REQUESTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS friend_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(sender_id, receiver_id),

            FOREIGN KEY (sender_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (receiver_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    # ========================================================
    # ADVERTISEMENT REQUESTS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS advertisement_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            business_name TEXT NOT NULL,
            advertising_type TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE SET NULL
        )
    """)

    # ========================================================
    # FRIENDS
    # ========================================================

    conn.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            friend_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(user_id, friend_id),

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (friend_id)
            REFERENCES users(id)
            ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# DATABASE MIGRATIONS
# ============================================================

def update_users_table():

    conn = get_db_connection()

    if not column_exists("users", "bio"):

        conn.execute("""
            ALTER TABLE users
            ADD COLUMN bio TEXT DEFAULT ''
        """)

    if not column_exists("users", "profile_picture"):

        conn.execute("""
            ALTER TABLE users
            ADD COLUMN profile_picture TEXT DEFAULT ''
        """)

    if not column_exists("users", "joined_at"):

        conn.execute("""
            ALTER TABLE users
            ADD COLUMN joined_at TIMESTAMP
        """)
    if not column_exists("users", "last_seen"):
        conn.execute("""
            ALTER TABLE users
            ADD COLUMN last_seen TIMESTAMP
        """)

    conn.commit()
    conn.close()
    # ============================================================
# GROUP MESSAGES TABLE
# ============================================================

def update_group_messages_table():

    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_id INTEGER NOT NULL,

            sender_id INTEGER NOT NULL,

            message TEXT NOT NULL,

            created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (group_id)
                REFERENCES groups(id)
                ON DELETE CASCADE,

            FOREIGN KEY (sender_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_group_messages_group

        ON group_messages(group_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_group_messages_created

        ON group_messages(created_at)
        """
    )

    conn.commit()
    conn.close()
def update_users_block_status():
    conn = get_db_connection()

    existing_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    }

    if "is_blocked" not in existing_columns:
        conn.execute(
            """
            ALTER TABLE users
            ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0
            """
        )

    conn.commit()
    conn.close()
    # ============================================================
# GROUP MESSAGES TABLE
# ============================================================

def update_group_messages_table():

    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            group_id INTEGER NOT NULL,

            sender_id INTEGER NOT NULL,

            message TEXT NOT NULL,

            created_at TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (group_id)
                REFERENCES groups(id)
                ON DELETE CASCADE,

            FOREIGN KEY (sender_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_group_messages_group

        ON group_messages(group_id)
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_group_messages_created

        ON group_messages(created_at)
        """
    )

    conn.commit()
    conn.close()

def update_posts_table():

    conn = get_db_connection()

    if not column_exists("posts", "group_id"):

        conn.execute("""
            ALTER TABLE posts
            ADD COLUMN group_id INTEGER
        """)

    # Additive migration for Razor image posts.
    # Existing posts are preserved and receive an empty image value.
    if not column_exists("posts", "image"):

        conn.execute("""
            ALTER TABLE posts
            ADD COLUMN image TEXT DEFAULT ''
        """)
    # ------------------------------------------------------------
    # RAZOR SPONSORED EXISTING POSTS
    # ------------------------------------------------------------
    # Allows an admin to mark an ordinary UniCamplink post
    # as Sponsored without creating a separate post.
    #
    # Non-destructive:
    # - Existing posts remain untouched.
    # - Existing posts default to not sponsored.
    # ------------------------------------------------------------

    existing_post_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(posts)"
        ).fetchall()
    }

    if "is_sponsored" not in existing_post_columns:
        conn.execute(
            """
            ALTER TABLE posts
            ADD COLUMN is_sponsored INTEGER NOT NULL DEFAULT 0
            """
        )

    if "sponsored_at" not in existing_post_columns:
        conn.execute(
            """
            ALTER TABLE posts
            ADD COLUMN sponsored_at TIMESTAMP
            """
        )
        # ============================================================
    # RAZOR: NORMAL POST SPONSORED FLAG
    # ============================================================

    existing_post_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(posts)"
        ).fetchall()
    }

    if "is_sponsored" not in existing_post_columns:

        conn.execute(
            """
            ALTER TABLE posts
            ADD COLUMN is_sponsored INTEGER NOT NULL DEFAULT 0
            """
        )

    if "sponsored_at" not in existing_post_columns:

        conn.execute(
            """
            ALTER TABLE posts
            ADD COLUMN sponsored_at TIMESTAMP
            """
        )
    conn.commit()
    conn.close()


def update_comments_table():

    conn = get_db_connection()

    if not column_exists(
        "comments",
        "parent_comment_id"
    ):

        conn.execute("""
            ALTER TABLE comments
            ADD COLUMN parent_comment_id INTEGER
        """)

    conn.commit()
    conn.close()
    # ============================================================
# DATABASE MIGRATION — ADVERTISEMENT REQUESTS
# ============================================================

def update_advertisement_requests_table():
    conn = get_db_connection()

    table_exists = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        AND name = 'advertisement_requests'
    """).fetchone()

    if not table_exists:
        conn.execute("""
            CREATE TABLE advertisement_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT DEFAULT '',
                email TEXT DEFAULT '',
                business_name TEXT DEFAULT '',
                advertising_type TEXT DEFAULT '',
                message TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    else:
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(advertisement_requests)"
            ).fetchall()
        }

        migrations = {
            "user_id": """
                ALTER TABLE advertisement_requests
                ADD COLUMN user_id INTEGER
            """,

            "name": """
                ALTER TABLE advertisement_requests
                ADD COLUMN name TEXT DEFAULT ''
            """,

            "email": """
                ALTER TABLE advertisement_requests
                ADD COLUMN email TEXT DEFAULT ''
            """,

            "business_name": """
                ALTER TABLE advertisement_requests
                ADD COLUMN business_name TEXT DEFAULT ''
            """,

            "advertising_type": """
                ALTER TABLE advertisement_requests
                ADD COLUMN advertising_type TEXT DEFAULT ''
            """,

            "message": """
                ALTER TABLE advertisement_requests
                ADD COLUMN message TEXT DEFAULT ''
            """,

            "status": """
                ALTER TABLE advertisement_requests
                ADD COLUMN status TEXT DEFAULT 'pending'
            """,

            "created_at": """
                ALTER TABLE advertisement_requests
                ADD COLUMN created_at
                TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """
        }

        for column, sql in migrations.items():
            if column not in columns:
                conn.execute(sql)

    conn.commit()
    conn.close()
    # ============================================================
# DATABASE MIGRATION — SPONSORED POSTS
# ============================================================

def update_sponsored_posts_table():

    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sponsored_posts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            advertisement_request_id INTEGER UNIQUE,

            advertiser_user_id INTEGER,

            business_name TEXT NOT NULL DEFAULT '',

            content TEXT NOT NULL DEFAULT '',

            image TEXT DEFAULT '',

            cta_text TEXT DEFAULT '',

            cta_url TEXT DEFAULT '',

            status TEXT NOT NULL DEFAULT 'draft',

            starts_at TIMESTAMP,

            ends_at TIMESTAMP,

            impressions INTEGER NOT NULL DEFAULT 0,

            clicks INTEGER NOT NULL DEFAULT 0,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (advertisement_request_id)
                REFERENCES advertisement_requests(id)
                ON DELETE SET NULL,

            FOREIGN KEY (advertiser_user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_sponsored_posts_status
        ON sponsored_posts(status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_sponsored_posts_dates
        ON sponsored_posts(starts_at, ends_at)
    """)

    conn.commit()
    conn.close()


# ============================================================
# DATABASE MIGRATION — CAMPUS AMBASSADORS
# ============================================================

def update_campus_ambassadors_table():
    """Create the separate Campus Ambassador role table.

    This migration is intentionally non-destructive: it creates a new
    table only when it does not already exist and never replaces the
    existing users table or production database file.
    """
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS campus_ambassadors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            campus TEXT NOT NULL DEFAULT '',
            school TEXT NOT NULL DEFAULT '',
            appointed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            appointed_by INTEGER,
            active INTEGER NOT NULL DEFAULT 1,
            removed_at TIMESTAMP,

            FOREIGN KEY (user_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (appointed_by)
            REFERENCES users(id)
            ON DELETE SET NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_campus_ambassadors_active
        ON campus_ambassadors(active)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_campus_ambassadors_campus
        ON campus_ambassadors(campus)
    """)

    conn.commit()
    conn.close()
def update_announcements_table():
    conn = get_db_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (created_by)
            REFERENCES users(id)
            ON DELETE SET NULL
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_announcements_active
        ON announcements(is_active)
        """
    )

    conn.commit()
    conn.close()
# ============================================================
# DATABASE MIGRATION — REPORTS
# ============================================================

def update_reports_table():

    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            reporter_id INTEGER NOT NULL,

            reported_user_id INTEGER,

            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,

            reason TEXT NOT NULL,
            details TEXT DEFAULT '',

            status TEXT NOT NULL DEFAULT 'pending',

            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,

            resolution_note TEXT DEFAULT '',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (reporter_id)
            REFERENCES users(id)
            ON DELETE CASCADE,

            FOREIGN KEY (reported_user_id)
            REFERENCES users(id)
            ON DELETE SET NULL,

            FOREIGN KEY (reviewed_by)
            REFERENCES users(id)
            ON DELETE SET NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_status
        ON reports(status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_target
        ON reports(target_type, target_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_reporter
        ON reports(reporter_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_created
        ON reports(created_at)
    """)

    conn.commit()
    conn.close()
def update_push_subscriptions_table():
    conn = get_db_connection()

    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        conn.commit()

    finally:
        conn.close()
def update_moderation_logs_table():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS moderation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (admin_id)
                REFERENCES users(id)
                ON DELETE SET NULL,

            FOREIGN KEY (target_user_id)
                REFERENCES users(id)
                ON DELETE SET NULL
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_moderation_logs_target
        ON moderation_logs(target_user_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_moderation_logs_created
        ON moderation_logs(created_at)
    """)

    conn.commit()
    conn.close()
# ============================================================
# INITIALIZE DATABASE
# ============================================================

create_tables()
update_users_table()
update_group_messages_table()
update_users_block_status()
update_group_messages_table()
update_posts_table()
update_comments_table()
update_advertisement_requests_table()
update_sponsored_posts_table()
update_campus_ambassadors_table()
update_announcements_table()
update_reports_table()
update_moderation_logs_table()
update_push_subscriptions_table()
# ============================================================
# USER ONLINE / LAST SEEN TRACKER
# ============================================================

@app.before_request
def update_last_seen():

    if "user_id" not in session:
        return

    if request.path.startswith("/static/"):
        return

    try:

        conn = get_db_connection()

        conn.execute(
            """
            UPDATE users
            SET last_seen = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                session["user_id"],
            )
        )

        conn.commit()
        conn.close()

    except Exception as e:

        print("LAST SEEN ERROR:", e)

# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    if "user_id" in session:

        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "index.html"
    )


# ============================================================
# SIGN UP
# ============================================================

@app.route(
    "/signup",
    methods=["GET", "POST"]
)
def signup():

    if request.method == "POST":

        name = clean_text(
            request.form.get("name"),
            MAX_NAME_LENGTH
        )

        email = (
            request.form.get(
                "email",
                ""
            )
            .strip()
            .lower()
        )

        university = clean_text(
            request.form.get("university"),
            MAX_UNIVERSITY_LENGTH
        )

        password = request.form.get(
            "password",
            ""
        )

        if not name or not university or not email or not password:

            return (
                "Please fill in all fields."
            )

        if not valid_email(email):

            return (
                "Please enter a valid email address."
            )

        if len(password) < 8:

            return (
                "Password must be at least "
                "8 characters long."
            )

        if len(password) > MAX_PASSWORD_LENGTH:

            return (
                "Password is too long. "
                "Maximum length is 128 characters."
            )

        conn = get_db_connection()

        existing_user = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if existing_user:

            conn.close()

            return (
                "An account with this email "
                "already exists."
            )

        password_hash = generate_password_hash(
            password
        )

        conn.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                university,
                password
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                name,
                email,
                university,
                password_hash
            )
        )

        conn.commit()
        conn.close()

        return redirect(
            url_for("login")
        )

    return render_template(
        "signup.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = (
            request.form.get(
                "email",
                ""
            )
            .strip()
            .lower()
        )

        password = request.form.get(
            "password",
            ""
        )

        # ----------------------------------------------------
        # INVALID EMAIL LENGTH
        # ----------------------------------------------------

        if len(email) > MAX_EMAIL_LENGTH:

            return render_template(
                "login.html",
                login_error="Invalid email or password.",
                login_email=email
            )

        conn = get_db_connection()

        # ----------------------------------------------------
        # CHECK LOGIN ATTEMPT RECORD
        # ----------------------------------------------------

        attempt_record = conn.execute(
            """
            SELECT
                failed_attempts,
                locked_until
            FROM login_attempts
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if attempt_record:

            locked_until = attempt_record["locked_until"]

            if locked_until:

                try:

                    lock_time = datetime.strptime(
                        str(locked_until),
                        "%Y-%m-%d %H:%M:%S"
                    )

                    if datetime.utcnow() < lock_time:

                        remaining_seconds = int(
                            (
                                lock_time
                                - datetime.utcnow()
                            ).total_seconds()
                        )

                        remaining_minutes = max(
                            1,
                            (remaining_seconds + 59) // 60
                        )

                        conn.close()

                        return render_template(
                            "login.html",
                            login_error=(
                                "Too many failed login attempts. "
                                f"Please try again in "
                                f"{remaining_minutes} minute(s)."
                            ),
                            login_email=email
                        ), 429

                    conn.execute(
                        """
                        DELETE FROM login_attempts
                        WHERE email = ?
                        """,
                        (email,)
                    )

                    conn.commit()

                except ValueError:

                    conn.execute(
                        """
                        DELETE FROM login_attempts
                        WHERE email = ?
                        """,
                        (email,)
                    )

                    conn.commit()

        # ----------------------------------------------------
        # FIND USER
        # ----------------------------------------------------

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        login_successful = False

        if user:

            stored_password = user["password"]

            # ------------------------------------------------
            # HASHED PASSWORD
            # ------------------------------------------------

            if stored_password.startswith(
                ("scrypt:", "pbkdf2:")
            ):

                if check_password_hash(
                    stored_password,
                    password
                ):

                    login_successful = True

            # ------------------------------------------------
            # LEGACY PLAINTEXT PASSWORD
            # ------------------------------------------------

            else:

                if stored_password == password:

                    new_password_hash = (
                        generate_password_hash(
                            password
                        )
                    )

                    conn.execute(
                        """
                        UPDATE users
                        SET password = ?
                        WHERE id = ?
                        """,
                        (
                            new_password_hash,
                            user["id"]
                        )
                    )

                    conn.commit()

                    login_successful = True

        # ----------------------------------------------------
        # SUCCESSFUL LOGIN
        # ----------------------------------------------------

        if login_successful:

            conn.execute(
                """
                DELETE FROM login_attempts
                WHERE email = ?
                """,
                (email,)
            )

            conn.commit()

            session.clear()

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            conn.close()

            return redirect(
                url_for("dashboard")
            )

        # ----------------------------------------------------
        # FAILED LOGIN
        # ----------------------------------------------------

        existing_attempt = conn.execute(
            """
            SELECT failed_attempts
            FROM login_attempts
            WHERE email = ?
            """,
            (email,)
        ).fetchone()

        if existing_attempt:

            failed_attempts = (
                existing_attempt["failed_attempts"] + 1
            )

        else:

            failed_attempts = 1

        # ----------------------------------------------------
        # LOCK ACCOUNT AFTER 5 FAILED ATTEMPTS
        # ----------------------------------------------------

        if failed_attempts >= 5:

            locked_until = (
                datetime.utcnow()
                + timedelta(minutes=10)
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            conn.execute(
                """
                INSERT INTO login_attempts
                (
                    email,
                    failed_attempts,
                    locked_until
                )
                VALUES (?, ?, ?)

                ON CONFLICT(email)
                DO UPDATE SET
                    failed_attempts = excluded.failed_attempts,
                    locked_until = excluded.locked_until
                """,
                (
                    email,
                    failed_attempts,
                    locked_until
                )
            )

            conn.commit()
            conn.close()

            return render_template(
                "login.html",
                login_error=(
                    "Too many failed login attempts. "
                    "Please try again in 10 minutes."
                ),
                login_email=email
            ), 429

        # ----------------------------------------------------
        # RECORD FAILED ATTEMPT
        # ----------------------------------------------------

        conn.execute(
            """
            INSERT INTO login_attempts
            (
                email,
                failed_attempts,
                locked_until
            )
            VALUES (?, ?, NULL)

            ON CONFLICT(email)
            DO UPDATE SET
                failed_attempts = excluded.failed_attempts,
                locked_until = NULL
            """,
            (
                email,
                failed_attempts
            )
        )

        conn.commit()
        conn.close()

        # ----------------------------------------------------
        # SHOW RAZOR LOGIN PAGE WITH ERROR
        # ----------------------------------------------------

        return render_template(
            "login.html",
            login_error="Invalid email or password.",
            login_email=email
        )

    # --------------------------------------------------------
    # NORMAL LOGIN PAGE
    # --------------------------------------------------------

    return render_template(
        "login.html",
        login_error=None,
        login_email=""
    )
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static", "icons"),
                       "icon-192.png",
        mimetype="image/png"
    )


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "service-worker.js",
        mimetype="application/javascript"
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    current_user_id = session["user_id"]

    # ========================================================
    # ACTIVE ANNOUNCEMENT
    # ========================================================

    active_announcement = conn.execute(
        """
        SELECT
            id,
            title,
            message,
            created_at
        FROM announcements
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()

    # ========================================================
    # PEOPLE YOU MAY KNOW
    # ========================================================
    #
    # Uses the existing users, friends, friend_requests and
    # campus_ambassadors tables. No new table or migration is
    # required for this feature.
    #
    # Candidates are excluded when they are:
    # - the current user
    # - already friends with the current user
    # - already involved in an existing friend request
    #
    # Suggestions are ranked using:
    # - same university
    # - mutual friends
    # - campus ambassador status
    # - friend count
    #
    people_you_may_know = conn.execute(
        """
        SELECT
            candidate.id,
            candidate.name,
            candidate.university,
            candidate.bio,
            candidate.profile_picture,
            COALESCE(candidate.is_verified_student, 0)
                AS is_verified_student,

            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM campus_ambassadors ca
                    WHERE ca.user_id = candidate.id
                    AND ca.active = 1
                )
                THEN 1
                ELSE 0
            END AS is_campus_ambassador,

            (
                SELECT COUNT(*)
                FROM friends fc
                WHERE fc.user_id = candidate.id
            ) AS friend_count,

            (
                SELECT COUNT(*)
                FROM friends myf
                WHERE myf.user_id = ?
                AND EXISTS (
                    SELECT 1
                    FROM friends cf
                    WHERE cf.user_id = candidate.id
                    AND cf.friend_id = myf.friend_id
                )
            ) AS mutual_friend_count,

            CASE
                WHEN LOWER(COALESCE(candidate.university, ''))
                     = LOWER(COALESCE(?, ''))
                THEN 1
                ELSE 0
            END AS same_university

        FROM users candidate

        WHERE candidate.id != ?

        AND NOT EXISTS (
            SELECT 1
            FROM friends existing_friendship
            WHERE
                (
                    existing_friendship.user_id = ?
                    AND existing_friendship.friend_id = candidate.id
                )
                OR
                (
                    existing_friendship.user_id = candidate.id
                    AND existing_friendship.friend_id = ?
                )
        )

        AND NOT EXISTS (
            SELECT 1
            FROM friend_requests existing_request
            WHERE
                existing_request.status = 'pending'
                AND (
                    (
                        existing_request.sender_id = ?
                        AND existing_request.receiver_id = candidate.id
                    )
                    OR
                    (
                        existing_request.sender_id = candidate.id
                        AND existing_request.receiver_id = ?
                    )
                )
        )

        ORDER BY
            same_university DESC,
            mutual_friend_count DESC,
            is_campus_ambassador DESC,
            friend_count DESC,
            candidate.joined_at DESC,
            candidate.id DESC

        LIMIT 6
        """,
        (
            current_user_id,
            user["university"],
            current_user_id,
            current_user_id,
            current_user_id,
            current_user_id,
            current_user_id
        )
    ).fetchall()

    people_you_may_know = [
        {
            "id": person["id"],
            "name": person["name"],
            "university": person["university"],
            "bio": person["bio"] or "",
            "profile_picture": person["profile_picture"] or "",
            "is_verified_student": bool(
                person["is_verified_student"]
            ),
            "is_campus_ambassador": bool(
                person["is_campus_ambassador"]
            ),
            "friend_count": person["friend_count"],
            "mutual_friend_count": person["mutual_friend_count"],
            "same_university": bool(
                person["same_university"]
            ),
            "suggestion_reason": (
                f"{person['mutual_friend_count']} mutual "
                f"friend{'s' if person['mutual_friend_count'] != 1 else ''}"
                if person["mutual_friend_count"]
                else (
                    "Same university as you"
                    if person["same_university"]
                    else "Suggested on UniCamplink"
                )
            )
        }
        for person in people_you_may_know
    ]


    conn.close()

    if not user:
        session.clear()

        return redirect(
            url_for("login")
        )

    # ========================================================
    # ADMIN STATUS
    # ========================================================

    is_admin = (
        bool(ADMIN_EMAIL)
        and user["email"]
        and user["email"].strip().lower()
        == ADMIN_EMAIL.strip().lower()
    )

    # ========================================================
    # DASHBOARD
    # ========================================================

    return render_template(
        "dashboard.html",
        user=user,
        is_admin=is_admin,
        active_announcement=active_announcement,
        people_you_may_know=people_you_may_know
    )
# ============================================================
# CGPA CALCULATOR
# ============================================================

@app.route("/cgpa-calculator")
def cgpa_calculator():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    return render_template(
        "cgpa_calculator.html"
    )
@app.route("/announcements")
def announcements():

    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if not user:
        conn.close()
        session.clear()
        return redirect(url_for("login"))

    announcements_list = conn.execute(
        """
        SELECT
            announcements.id,
            announcements.title,
            announcements.message,
            announcements.created_at,
            announcements.updated_at,
            users.name AS creator_name
        FROM announcements
        LEFT JOIN users
            ON users.id = announcements.created_by
        WHERE announcements.is_active = 1
        ORDER BY
            announcements.created_at DESC,
            announcements.id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "announcements.html",
        user=user,
        announcements=announcements_list
    )
# ============================================================
# FEED
# ============================================================

@app.route("/feed")
def feed():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    posts = conn.execute(
        """
        SELECT
            posts.*,
            users.name AS author_name,
            users.university AS author_university,
            users.profile_picture,
            users.is_verified_student AS author_is_verified,

            (
                SELECT COUNT(*)
                FROM likes
                WHERE likes.post_id = posts.id
            ) AS like_count,

            (
                SELECT COUNT(*)
                FROM comments
                WHERE comments.post_id = posts.id
            ) AS comment_count,

            EXISTS (
                SELECT 1
                FROM likes
                WHERE likes.post_id = posts.id
                AND likes.user_id = ?
            ) AS user_liked

        FROM posts

        JOIN users
        ON posts.user_id = users.id

        ORDER BY posts.created_at DESC
        """,
        (
            session["user_id"],
        )
    ).fetchall()

    conn.close()

    return render_template(
        "feed.html",
        posts=posts
    )


# ============================================================
# CREATE POST
# ============================================================
@app.route(
    "/create-post",
    methods=["POST"]
)
def create_post():

    if "user_id" not in session:

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "error": "Please log in."
            }), 401

        return redirect(url_for("login"))

    content = clean_text(
        request.form.get("content"),
        MAX_POST_LENGTH
    )

    image = request.files.get("image")

    if not content and not (image and image.filename):
        message = "Post cannot be empty. Add text or an image."

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "error": message
            }), 400

        return message, 400

    if content is None:
        message = (
            "Post text is too long. "
            "Maximum length is 5000 characters."
        )

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({
                "success": False,
                "error": message
            }), 400

        return message, 400

    image_filename = ""

    if image and image.filename:

        if not validate_image(image):
            message = (
                "Invalid image. Please upload a genuine PNG, JPG, JPEG "
                "or GIF image under 4096x4096 pixels."
            )

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "success": False,
                    "error": message
                }), 400

            return message, 400

        extension = image.filename.rsplit(".", 1)[1].lower()

        image_filename = (
            "post_"
            + str(uuid4())
            + "."
            + extension
        )

        try:

            image.save(
                safe_upload_path(image_filename)
            )

        except OSError:

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "success": False,
                    "error": (
                        "The image could not be saved. "
                        "Please try again."
                    )
                }), 500

            return (
                "The image could not be saved. "
                "Please try again.",
                500
            )

    conn = get_db_connection()

    current_user_id = session["user_id"]

    cursor = conn.execute(
        """
        INSERT INTO posts
        (
            user_id,
            content,
            image
        )
        VALUES (?, ?, ?)
        """,
        (
            current_user_id,
            content or "",
            image_filename
        )
    )

    post_id = cursor.lastrowid

    author = conn.execute(
        """
        SELECT
            id,
            name,
            university,
            profile_picture,
            is_verified_student
        FROM users
        WHERE id = ?
        """,
        (current_user_id,)
    ).fetchone()

    author_name = (
        author["name"]
        if author
        else "A student"
    )

    friends = conn.execute(
        """
        SELECT friend_id
        FROM friends
        WHERE user_id = ?
        """,
        (current_user_id,)
    ).fetchall()

    for friend in friends:

        conn.execute(
            """
            INSERT INTO notifications
            (
                user_id,
                sender_id,
                type,
                message,
                link
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                friend["friend_id"],
                current_user_id,
                "post",
                f"{author_name} shared a new campus update 📝",
                f"/feed#post-{post_id}"
            )
        )

    conn.commit()
    conn.close()

    post_data = {
        "id": post_id,
        "user_id": current_user_id,
        "author_name": (
            author["name"]
            if author
            else "UniCamplink User"
        ),
        "author_university": (
            author["university"]
            if author
            else ""
        ),
        "profile_picture": (
            author["profile_picture"]
            if author
            else ""
        ),
        "author_is_verified": (
            bool(author["is_verified_student"])
            if author
            else False
        ),
        "content": content or "",
        "image": image_filename,
        "like_count": 0,
        "comment_count": 0,
        "user_liked": False
    }

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":

        return jsonify({
            "success": True,
            "post": post_data
        }), 201

    return redirect(
        url_for("feed")
    )

# ============================================================
# LIKE POST
# ============================================================

@app.route(
    "/like/<int:post_id>",
    methods=["POST"]
)
def like_post(post_id):

    if "user_id" not in session:

        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or \
           "application/json" in request.headers.get("Accept", "").lower():
            return jsonify({
                "success": False,
                "error": "Please log in again."
            }), 401

        return redirect(url_for("login"))

    conn = get_db_connection()

    post_exists = conn.execute(
        """
        SELECT id
        FROM posts
        WHERE id = ?
        """,
        (post_id,)
    ).fetchone()

    if not post_exists:

        conn.close()

        return "Post not found.", 404

    existing_like = conn.execute(
        """
        SELECT id
        FROM likes
        WHERE post_id = ?
        AND user_id = ?
        """,
        (
            post_id,
            session["user_id"]
        )
    ).fetchone()

    if existing_like:

        conn.execute(
            """
            DELETE FROM likes
            WHERE post_id = ?
            AND user_id = ?
            """,
            (
                post_id,
                session["user_id"]
            )
        )

    else:

        conn.execute(
            """
            INSERT INTO likes
            (
                post_id,
                user_id
            )
            VALUES (?, ?)
            """,
            (
                post_id,
                session["user_id"]
            )
        )

        post_owner = conn.execute(
            """
            SELECT user_id
            FROM posts
            WHERE id = ?
            """,
            (
                post_id,
            )
        ).fetchone()

        if (
            post_owner
            and
            post_owner["user_id"]
            != session["user_id"]
        ):

            conn.execute(
                """
                INSERT INTO notifications
                (
                    user_id,
                    sender_id,
                    type,
                    message,
                    link
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    post_owner["user_id"],
                    session["user_id"],
                    "like",
                    "liked your post ❤️",
f"/feed#post-{post_id}"
                )
            )
            send_push_notification(
                post_owner["user_id"],
                "❤️ New Like",
                "Someone liked your post.",
                f"/feed#post-{post_id}",
                "unicamplink-like"
            )

    conn.commit()

    like_count = conn.execute(
        "SELECT COUNT(*) FROM likes WHERE post_id = ?",
        (post_id,)
    ).fetchone()[0]

    user_liked = conn.execute(
        """
        SELECT 1
        FROM likes
        WHERE post_id = ?
        AND user_id = ?
        LIMIT 1
        """,
        (post_id, session["user_id"])
    ).fetchone() is not None

    conn.close()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or \
       request.headers.get("Accept", "").lower().find("application/json") >= 0:
        return jsonify({
            "success": True,
            "post_id": post_id,
            "like_count": like_count,
            "user_liked": user_liked
        })

    return redirect(
        url_for("feed")
    )


# ============================================================
# COMMENT
# ============================================================

@app.route(
    "/comment/<int:post_id>",
    methods=["POST"]
)
def comment(post_id):

    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "").lower()
    )

    if "user_id" not in session:
        if is_ajax:
            return jsonify({
                "success": False,
                "error": "Please log in again."
            }), 401
        return redirect(url_for("login"))

    content = clean_text(
        request.form.get("content"),
        MAX_COMMENT_LENGTH
    )

    if not content:
        message = "Comment cannot be empty and must not exceed 2000 characters."
        if is_ajax:
            return jsonify({"success": False, "error": message}), 400
        return message, 400

    parent_raw = request.form.get("parent_comment_id", "").strip()
    parent_comment_id = None

    if parent_raw:
        try:
            parent_comment_id = int(parent_raw)
        except ValueError:
            if is_ajax:
                return jsonify({"success": False, "error": "Invalid reply target."}), 400
            return "Invalid reply target.", 400

    conn = get_db_connection()

    post_owner = conn.execute(
        "SELECT user_id FROM posts WHERE id = ?",
        (post_id,)
    ).fetchone()

    if not post_owner:
        conn.close()
        if is_ajax:
            return jsonify({"success": False, "error": "Post not found."}), 404
        return "Post not found.", 404

    if parent_comment_id is not None:
        parent = conn.execute(
            """
            SELECT id, post_id, user_id
            FROM comments
            WHERE id = ? AND post_id = ?
            """,
            (parent_comment_id, post_id)
        ).fetchone()

        if not parent:
            conn.close()
            if is_ajax:
                return jsonify({"success": False, "error": "The comment you are replying to was not found."}), 404
            return "The comment you are replying to was not found.", 404

    cursor = conn.execute(
        """
        INSERT INTO comments
        (post_id, user_id, content, parent_comment_id)
        VALUES (?, ?, ?, ?)
        """,
        (post_id, session["user_id"], content, parent_comment_id)
    )

    comment_id = cursor.lastrowid

    # Notify the post owner for top-level comments.
    if post_owner["user_id"] != session["user_id"]:
        conn.execute(
            """
            INSERT INTO notifications
            (user_id, sender_id, type, message, link)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                post_owner["user_id"],
                session["user_id"],
                "comment",
                "commented on your post 💬",
f"/feed#post-{post_id}"
            )
        )
        send_push_notification(
            post_owner["user_id"],
            "💬 New Comment",
            "Someone commented on your post.",
            f"/feed#post-{post_id}",
            "unicamplink-comment"
        )

    # Notify the parent-comment author for replies, when different.
    if parent_comment_id is not None:
        parent_user = conn.execute(
            "SELECT user_id FROM comments WHERE id = ?",
            (parent_comment_id,)
        ).fetchone()

        if parent_user and parent_user["user_id"] != session["user_id"]:
            conn.execute(
                """
                INSERT INTO notifications
                (user_id, sender_id, type, message, link)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    parent_user["user_id"],
                    session["user_id"],
                    "reply",
                    "replied to your comment 💬",
                    f"/feed#post-{post_id}"
                )
            )


            send_push_notification(
                parent_user["user_id"],
                "New Reply",
                "Someone replied to your comment.",
                f"/feed#post-{post_id}",
                "unicamplink-reply"
            )
    conn.commit()

    comment_row = conn.execute(
        """
        SELECT
            c.id,
            c.post_id,
            c.user_id,
            c.content,
            c.created_at,
            c.parent_comment_id,
            u.name AS author_name,
            u.profile_picture
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.id = ?
        """,
        (comment_id,)
    ).fetchone()

    comment_count = conn.execute(
        "SELECT COUNT(*) FROM comments WHERE post_id = ?",
        (post_id,)
    ).fetchone()[0]

    conn.close()

    if is_ajax:
        return jsonify({
            "success": True,
            "comment_count": comment_count,
            "comment": dict(comment_row) if comment_row else None
        })

    return redirect(url_for("feed"))


# ============================================================
# COMMENTS API — LOAD EXISTING COMMENTS
# ============================================================

@app.route("/comments/<int:post_id>", methods=["GET"])
def get_comments(post_id):

    if "user_id" not in session:
        return jsonify({
            "success": False,
            "error": "Please log in again."
        }), 401

    conn = get_db_connection()

    post = conn.execute(
        "SELECT id FROM posts WHERE id = ?",
        (post_id,)
    ).fetchone()

    if not post:
        conn.close()
        return jsonify({
            "success": False,
            "error": "Post not found."
        }), 404

    rows = conn.execute(
        """
        SELECT
            c.id,
            c.post_id,
            c.user_id,
            c.content,
            c.created_at,
            c.parent_comment_id,
            u.name AS author_name,
            u.profile_picture
        FROM comments c
        JOIN users u ON u.id = c.user_id
        WHERE c.post_id = ?
        ORDER BY c.created_at ASC, c.id ASC
        """,
        (post_id,)
    ).fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "comments": [dict(row) for row in rows]
    })
# ============================================================
# REPORT SYSTEM
# ============================================================

@app.route(
    "/api/reports",
    methods=["POST"]
)
def create_report():

    if "user_id" not in session:
        return jsonify({
            "success": False,
            "error": "Please log in again."
        }), 401

    data = request.get_json(silent=True) or {}

    target_type = clean_text(
        data.get("target_type"),
        30
    )

    reason = clean_text(
        data.get("reason"),
        100
    )

    details = clean_text(
        data.get("details"),
        1000
    )

    try:
        target_id = int(
            data.get("target_id")
        )
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Invalid report target."
        }), 400

    allowed_target_types = {
        "user",
        "post",
        "comment"
    }

    if target_type not in allowed_target_types:
        return jsonify({
            "success": False,
            "error": "Invalid report type."
        }), 400

    if not reason:
        return jsonify({
            "success": False,
            "error": "Please select a report reason."
        }), 400

    if target_id <= 0:
        return jsonify({
            "success": False,
            "error": "Invalid report target."
        }), 400

    if details is None:
        return jsonify({
            "success": False,
            "error": "Report details are too long."
        }), 400

    conn = get_db_connection()

    # --------------------------------------------------------
    # Verify that the reported target actually exists
    # --------------------------------------------------------

    reported_user_id = None

    if target_type == "user":

        target = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
            """,
            (target_id,)
        ).fetchone()

        if not target:
            conn.close()

            return jsonify({
                "success": False,
                "error": "User not found."
            }), 404

        reported_user_id = target["id"]

    elif target_type == "post":

        target = conn.execute(
            """
            SELECT id, user_id
            FROM posts
            WHERE id = ?
            """,
            (target_id,)
        ).fetchone()

        if not target:
            conn.close()

            return jsonify({
                "success": False,
                "error": "Post not found."
            }), 404

        reported_user_id = target["user_id"]

    elif target_type == "comment":

        target = conn.execute(
            """
            SELECT id, user_id
            FROM comments
            WHERE id = ?
            """,
            (target_id,)
        ).fetchone()

        if not target:
            conn.close()

            return jsonify({
                "success": False,
                "error": "Comment not found."
            }), 404

        reported_user_id = target["user_id"]

    # --------------------------------------------------------
    # Prevent users from reporting themselves
    # --------------------------------------------------------

    if reported_user_id == session["user_id"]:

        conn.close()

        return jsonify({
            "success": False,
            "error": "You cannot report yourself."
        }), 400

    # --------------------------------------------------------
    # Prevent duplicate pending reports
    # --------------------------------------------------------

    existing_report = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE reporter_id = ?
        AND target_type = ?
        AND target_id = ?
        AND status = 'pending'
        LIMIT 1
        """,
        (
            session["user_id"],
            target_type,
            target_id
        )
    ).fetchone()

    if existing_report:

        conn.close()

        return jsonify({
            "success": False,
            "error": "You have already reported this."
        }), 409

    # --------------------------------------------------------
    # Create report
    # --------------------------------------------------------

    cursor = conn.execute(
        """
        INSERT INTO reports
        (
            reporter_id,
            reported_user_id,
            target_type,
            target_id,
            reason,
            details,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            session["user_id"],
            reported_user_id,
            target_type,
            target_id,
            reason,
            details or ""
        )
    )

    report_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": (
            "Thank you. Your report has been submitted "
            "for review."
        ),
        "report_id": report_id
    }), 201

# ============================================================
# PROFILE
# ============================================================

@app.route("/profile")
def profile():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    if not user:

        conn.close()
        session.clear()

        return redirect(
            url_for("login")
        )

    posts = conn.execute(
        """
        SELECT
            posts.*,

            (
                SELECT COUNT(*)
                FROM likes
                WHERE likes.post_id = posts.id
            ) AS like_count,

            (
                SELECT COUNT(*)
                FROM comments
                WHERE comments.post_id = posts.id
            ) AS comment_count,

            EXISTS (
                SELECT 1
                FROM likes
                WHERE likes.post_id = posts.id
                AND likes.user_id = ?
            ) AS user_liked

        FROM posts
        WHERE posts.user_id = ?
        ORDER BY posts.created_at DESC
        """,
        (
            session["user_id"],
            session["user_id"],
        )
    ).fetchall()

    post_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM posts
        WHERE user_id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()[0]

    total_likes = conn.execute(
        """
        SELECT COUNT(*)
        FROM likes
        JOIN posts
        ON likes.post_id = posts.id
        WHERE posts.user_id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()[0]

    campus_ambassador = conn.execute(
        """
        SELECT campus, school, appointed_at
        FROM campus_ambassadors
        WHERE user_id = ? AND active = 1
        LIMIT 1
        """,
        (session["user_id"],)
    ).fetchone()

    conn.close()

    return render_template(
        "profile.html",
        user=user,
        posts=posts,
        post_count=post_count,
        total_likes=total_likes,
        campus_ambassador=campus_ambassador,
        is_owner=True
    )
# ============================================================
# PUBLIC USER PROFILE
# ============================================================

@app.route("/profile/<int:user_id>")
def view_profile(user_id):

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:

        conn.close()

        return "User not found.", 404

    posts = conn.execute(
        """
        SELECT
            posts.*,

            (
                SELECT COUNT(*)
                FROM likes
                WHERE likes.post_id = posts.id
            ) AS like_count,

            (
                SELECT COUNT(*)
                FROM comments
                WHERE comments.post_id = posts.id
            ) AS comment_count,

            EXISTS (
                SELECT 1
                FROM likes
                WHERE likes.post_id = posts.id
                AND likes.user_id = ?
            ) AS user_liked

        FROM posts
        WHERE posts.user_id = ?
        ORDER BY posts.created_at DESC
        """,
        (
            session["user_id"],
            user_id,
        )
    ).fetchall()

    post_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM posts
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    total_likes = conn.execute(
        """
        SELECT COUNT(*)
        FROM likes
        JOIN posts
            ON likes.post_id = posts.id
        WHERE posts.user_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    campus_ambassador = conn.execute(
        """
        SELECT
            campus,
            school,
            appointed_at
        FROM campus_ambassadors
        WHERE user_id = ?
        AND active = 1
        LIMIT 1
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    is_owner = (
        session["user_id"] == user_id
    )

    return render_template(
        "profile.html",
        user=user,
        posts=posts,
        post_count=post_count,
        total_likes=total_likes,
        campus_ambassador=campus_ambassador,
        is_owner=is_owner
    )


# ============================================================
# EDIT PROFILE
# ============================================================

@app.route(
    "/edit-profile",
    methods=["GET", "POST"]
)
def edit_profile():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            session["user_id"],
        )
    ).fetchone()

    if not user:

        conn.close()
        session.clear()

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        name = clean_text(
            request.form.get("name"),
            MAX_NAME_LENGTH
        )

        university = clean_text(
            request.form.get("university"),
            MAX_UNIVERSITY_LENGTH
        )

        bio = clean_text(
            request.form.get("bio"),
            MAX_BIO_LENGTH
        )

        if not name:

            conn.close()

            return (
                "Name is required and must not exceed "
                "100 characters."
            ), 400

        if not university:

            conn.close()

            return (
                "University is required and must not exceed "
                "150 characters."
            ), 400

        if bio is None:

            conn.close()

            return (
                "Bio must not exceed 500 characters."
            ), 400

        profile_picture = user["profile_picture"]

        image = request.files.get(
            "profile_picture"
        )

        if image and image.filename:

            if not validate_image(image):

                conn.close()

                return (
                    "Invalid image. "
                    "Please upload a genuine "
                    "PNG, JPG, JPEG or GIF image "
                    "under 4096x4096 pixels."
                ), 400

            extension = image.filename.rsplit(
                ".",
                1
            )[1].lower()

            filename = (
                "profile_"
                + str(uuid4())
                + "."
                + extension
            )

            image.save(
                safe_upload_path(filename)
            )

            # Remove old profile picture if it exists.
            if profile_picture:

                old_image_path = safe_upload_path(
                    profile_picture
                )

                if os.path.isfile(old_image_path):

                    try:
                        os.remove(old_image_path)
                    except OSError:
                        pass

            profile_picture = filename

        conn.execute(
            """
            UPDATE users
            SET
                name = ?,
                university = ?,
                bio = ?,
                profile_picture = ?
            WHERE id = ?
            """,
            (
                name,
                university,
                bio,
                profile_picture,
                session["user_id"]
            )
        )

        conn.commit()
        conn.close()

        session["user_name"] = name

        return redirect(
            url_for("profile")
        )

    conn.close()

    return render_template(
        "edit_profile.html",
        user=user
    )


# ============================================================
# VIEW OTHER USER
# ============================================================

@app.route(
    "/user/<int:user_id>"
)
def view_user(user_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            user_id,
        )
    ).fetchone()

    if not user:

        conn.close()

        return "User not found.", 404

    posts = conn.execute(
        """
        SELECT
            posts.*,
            users.name AS author_name

        FROM posts

        JOIN users
        ON posts.user_id = users.id

        WHERE posts.user_id = ?

        ORDER BY posts.created_at DESC
        """,
        (
            user_id,
        )
    ).fetchall()

    is_friend = False
    request_sent = False
    request_received = False

    if user_id != current_user_id:

        friendship = conn.execute(
            """
            SELECT id
            FROM friends
            WHERE user_id = ?
            AND friend_id = ?
            """,
            (
                current_user_id,
                user_id
            )
        ).fetchone()

        if friendship:
            is_friend = True

        sent_request = conn.execute(
            """
            SELECT id
            FROM friend_requests
            WHERE sender_id = ?
            AND receiver_id = ?
            AND status = 'pending'
            """,
            (
                current_user_id,
                user_id
            )
        ).fetchone()

        if sent_request:
            request_sent = True

        received_request = conn.execute(
            """
            SELECT id
            FROM friend_requests
            WHERE sender_id = ?
            AND receiver_id = ?
            AND status = 'pending'
            """,
            (
                user_id,
                current_user_id
            )
        ).fetchone()

        if received_request:
            request_received = True

    campus_ambassador = conn.execute(
        """
        SELECT campus, school, appointed_at
        FROM campus_ambassadors
        WHERE user_id = ? AND active = 1
        LIMIT 1
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    return render_template(
        "user_profile.html",
        user=user,
        posts=posts,
        is_friend=is_friend,
        request_sent=request_sent,
        request_received=request_received,
        current_user_id=current_user_id,
        campus_ambassador=campus_ambassador
    )


# ============================================================
# SEARCH USERS
# ============================================================

@app.route(
    "/search",
    endpoint="search_students"
)
@app.route(
    "/search",
    endpoint="search"
)
def search_students():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    query = clean_text(
        request.args.get("q"),
        MAX_SEARCH_LENGTH
    )

    if query is None:

        return (
            "Search query is too long. "
            "Maximum length is 100 characters."
        ), 400

    conn = get_db_connection()

    users = []

    if query:

        search_pattern = f"%{query}%"

        users = conn.execute(
            """
            SELECT *
            FROM users
            WHERE LOWER(name) LIKE LOWER(?)
               OR LOWER(email) LIKE LOWER(?)
               OR LOWER(university) LIKE LOWER(?)
            ORDER BY name ASC
            """,
            (
                search_pattern,
                search_pattern,
                search_pattern
            )
        ).fetchall()

    conn.close()

    return render_template(
        "search.html",
        users=users,
        query=query
    )


# ============================================================
# GROUPS
# ============================================================

@app.route("/groups")
def groups():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    groups_list = conn.execute(
        """
        SELECT
            groups.*,
            users.name AS creator_name,

            (
                SELECT COUNT(*)
                FROM group_members
                WHERE group_members.group_id = groups.id
            ) AS member_count

        FROM groups

        JOIN users
        ON groups.creator_id = users.id

        ORDER BY groups.created_at DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "groups.html",
        groups=groups_list
    )


# ============================================================
# CREATE GROUP
# ============================================================

@app.route(
    "/create-group",
    methods=["GET", "POST"]
)
def create_group():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        name = clean_text(
            request.form.get("name"),
            MAX_GROUP_NAME_LENGTH
        )

        description = clean_text(
            request.form.get("description"),
            MAX_GROUP_DESCRIPTION_LENGTH
        )

        if not name:

            return (
                "Group name is required and must not exceed "
                "100 characters."
            ), 400

        if description is None:

            return (
                "Group description must not exceed "
                "1000 characters."
            ), 400

        conn = get_db_connection()

        cursor = conn.execute(
            """
            INSERT INTO groups
            (
                name,
                description,
                creator_id
            )
            VALUES (?, ?, ?)
            """,
            (
                name,
                description,
                session["user_id"]
            )
        )

        group_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO group_members
            (
                group_id,
                user_id
            )
            VALUES (?, ?)
            """,
            (
                group_id,
                session["user_id"]
            )
        )

        conn.commit()
        conn.close()

        return redirect(
            url_for("groups")
        )

    return render_template(
        "create_group.html"
    )


# ============================================================
# JOIN GROUP
# ============================================================

@app.route(
    "/join-group/<int:group_id>",
    methods=["POST"]
)
def join_group(group_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    group = conn.execute(
        """
        SELECT id
        FROM groups
        WHERE id = ?
        """,
        (
            group_id,
        )
    ).fetchone()

    if not group:

        conn.close()

        return "Group not found.", 404

    conn.execute(
        """
        INSERT OR IGNORE INTO group_members
        (
            group_id,
            user_id
        )
        VALUES (?, ?)
        """,
        (
            group_id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "group_detail",
            group_id=group_id
        )
    )


# ============================================================
# GROUP DETAIL
# ============================================================

@app.route(
    "/group/<int:group_id>"
)
def group_detail(group_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    group = conn.execute(
        """
        SELECT
            groups.*,
            users.name AS creator_name

        FROM groups

        JOIN users
        ON groups.creator_id = users.id

        WHERE groups.id = ?
        """,
        (
            group_id,
        )
    ).fetchone()

    if not group:

        conn.close()

        return "Group not found.", 404

    members = conn.execute(
        """
        SELECT
            users.id,
            users.name,
            users.university,
            users.profile_picture

        FROM group_members

        JOIN users
        ON group_members.user_id = users.id

        WHERE group_members.group_id = ?

        ORDER BY users.name
        """,
        (
            group_id,
        )
    ).fetchall()

    posts = conn.execute(
        """
        SELECT
            posts.*,
            users.name AS author_name,
            users.profile_picture

        FROM posts

        JOIN users
        ON posts.user_id = users.id

        WHERE posts.group_id = ?

        ORDER BY posts.created_at DESC
        """,
        (
            group_id,
        )
    ).fetchall()

    membership = conn.execute(
        """
        SELECT id
        FROM group_members
        WHERE group_id = ?
        AND user_id = ?
        """,
        (
            group_id,
            session["user_id"]
        )
    ).fetchone()

    conn.close()

    return render_template(
        "group_detail.html",
        group=group,
        members=members,
        posts=posts,
        is_member=bool(membership)
    )
# ============================================================
# GROUP CHAT
# ============================================================

@app.route(
    "/group/<int:group_id>/chat",
    methods=["GET", "POST"]
)
def group_chat(group_id):

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    # --------------------------------------------------------
    # GET GROUP
    # --------------------------------------------------------

    group = conn.execute(
        """
        SELECT
            groups.id,
            groups.name,
            groups.description,
            groups.creator_id,
            users.name AS creator_name
        FROM groups
        JOIN users
        ON users.id = groups.creator_id
        WHERE groups.id = ?
        """,
        (group_id,)
    ).fetchone()

    if not group:
        conn.close()
        return "Group not found.", 404

    # --------------------------------------------------------
    # CHECK MEMBERSHIP
    # --------------------------------------------------------

    membership = conn.execute(
        """
        SELECT id
        FROM group_members
        WHERE group_id = ?
        AND user_id = ?
        """,
        (
            group_id,
            current_user_id
        )
    ).fetchone()

    if not membership:
        conn.close()

        return (
            "You must join this group before "
            "you can use the group chat."
        ), 403

    # --------------------------------------------------------
    # SEND GROUP MESSAGE
    # --------------------------------------------------------

    if request.method == "POST":

        message = clean_text(
            request.form.get("message"),
            MAX_MESSAGE_LENGTH
        )

        if not message:
            conn.close()

            return (
                "Message cannot be empty and must not "
                "exceed 2000 characters."
            ), 400

        cursor = conn.execute(
            """
            INSERT INTO group_messages
            (
                group_id,
                sender_id,
                message
            )
            VALUES (?, ?, ?)
            """,
            (
                group_id,
                current_user_id,
                message
            )
        )

        group_message_id = cursor.lastrowid

        # ----------------------------------------------------
        # NOTIFY OTHER GROUP MEMBERS
        # ----------------------------------------------------

        sender = conn.execute(
            """
            SELECT name
            FROM users
            WHERE id = ?
            """,
            (current_user_id,)
        ).fetchone()

        sender_name = (
            sender["name"]
            if sender
            else "A student"
        )

        group_members = conn.execute(
            """
            SELECT user_id
            FROM group_members
            WHERE group_id = ?
            AND user_id != ?
            """,
            (
                group_id,
                current_user_id
            )
        ).fetchall()

        for member in group_members:

            conn.execute(
                """
                INSERT INTO notifications
                (
                    user_id,
                    sender_id,
                    type,
                    message,
                    link
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    member["user_id"],
                    current_user_id,
                    "group_message",
                    f"{sender_name} sent a message in "
                    f"{group['name']} 💬",
                    f"/group/{group_id}/chat"
                )
            )

        conn.commit()
        conn.close()

        return redirect(
            url_for(
                "group_chat",
                group_id=group_id
            )
        )

    # --------------------------------------------------------
    # LOAD GROUP MESSAGES
    # --------------------------------------------------------

    group_messages = conn.execute(
        """
        SELECT
            group_messages.id,
            group_messages.group_id,
            group_messages.sender_id,
            group_messages.message,
            group_messages.created_at,

            users.name AS sender_name,
            users.profile_picture AS sender_picture

        FROM group_messages

        JOIN users
        ON users.id = group_messages.sender_id

        WHERE group_messages.group_id = ?

        ORDER BY
            group_messages.created_at ASC,
            group_messages.id ASC
        """,
        (group_id,)
    ).fetchall()

    # --------------------------------------------------------
    # LOAD MEMBERS
    # --------------------------------------------------------

    members = conn.execute(
        """
        SELECT
            users.id,
            users.name,
            users.university,
            users.profile_picture

        FROM group_members

        JOIN users
        ON users.id = group_members.user_id

        WHERE group_members.group_id = ?

        ORDER BY users.name
        """,
        (group_id,)
    ).fetchall()

    conn.close()

    return render_template(
        "group_chat.html",
        group=group,
        group_messages=group_messages,
        members=members,
        current_user_id=current_user_id
    )


# ============================================================
# CREATE GROUP POST
# ============================================================

@app.route(
    "/group/<int:group_id>/post",
    methods=["POST"]
)
def create_group_post(group_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    content = clean_text(
        request.form.get("content"),
        MAX_POST_LENGTH
    )

    if not content:

        return (
            "Group post cannot be empty and must not exceed "
            "5000 characters."
        ), 400

    conn = get_db_connection()

    membership = conn.execute(
        """
        SELECT id
        FROM group_members
        WHERE group_id = ?
        AND user_id = ?
        """,
        (
            group_id,
            session["user_id"]
        )
    ).fetchone()

    if not membership:

        conn.close()

        return (
            "You must join the group first."
        ), 403

    group_exists = conn.execute(
        """
        SELECT id
        FROM groups
        WHERE id = ?
        """,
        (group_id,)
    ).fetchone()

    if not group_exists:

        conn.close()

        return "Group not found.", 404

    cursor = conn.execute(
        """
        INSERT INTO posts
        (
            user_id,
            content,
            group_id
        )
        VALUES (?, ?, ?)
        """,
        (
            session["user_id"],
            content,
            group_id
        )
    )

    post_id = cursor.lastrowid

    # --------------------------------------------------------
    # NOTIFY GROUP MEMBERS
    # --------------------------------------------------------

    group = conn.execute(
        """
        SELECT name
        FROM groups
        WHERE id = ?
        """,
        (group_id,)
    ).fetchone()

    group_name = group["name"] if group else "your group"

    author = conn.execute(
        """
        SELECT name
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    author_name = author["name"] if author else "A student"

    group_members = conn.execute(
        """
        SELECT user_id
        FROM group_members
        WHERE group_id = ?
        AND user_id != ?
        """,
        (
            group_id,
            session["user_id"]
        )
    ).fetchall()

    for member in group_members:

        conn.execute(
            """
            INSERT INTO notifications
            (
                user_id,
                sender_id,
                type,
                message,
                link
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                member["user_id"],
                session["user_id"],
                "group",
                f"{author_name} posted in {group_name} 👥",
                f"/group/{group_id}"
            )
        )

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "group_detail",
            group_id=group_id
        )
    )


# ============================================================
# MARKETPLACE
# ============================================================

@app.route("/marketplace")
def marketplace():

    # --------------------------------------------------------
    # LOGIN REQUIRED
    # --------------------------------------------------------

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    search = clean_text(
        request.args.get("search"),
        MAX_SEARCH_LENGTH
    )

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    category = clean_text(
        request.args.get("category"),
        MAX_NAME_LENGTH
    )

    # --------------------------------------------------------
    # VALIDATE SEARCH
    # --------------------------------------------------------

    if search is None:

        return (
            "Marketplace search query is too long."
        ), 400

    # --------------------------------------------------------
    # VALIDATE CATEGORY
    # --------------------------------------------------------

    if category is None:

        return (
            "Invalid marketplace category."
        ), 400

    # Ignore unknown categories rather than crashing.
    if (
        category
        and
        category not in MARKETPLACE_CATEGORIES
    ):

        category = ""

    # --------------------------------------------------------
    # DATABASE
    # --------------------------------------------------------

    conn = get_db_connection()

    sql = """
        SELECT
            products.*,

            users.name AS seller_name,

            users.university AS seller_university,

            users.profile_picture AS seller_profile_picture

        FROM products

        JOIN users
        ON products.seller_id = users.id

        WHERE products.status = 'available'
    """

    parameters = []

    # --------------------------------------------------------
    # SEARCH FILTER
    # --------------------------------------------------------

    if search:

        sql += """
            AND (
                products.name LIKE ?
                OR products.description LIKE ?
                OR products.location LIKE ?
            )
        """

        search_pattern = "%" + search + "%"

        parameters.extend([
            search_pattern,
            search_pattern,
            search_pattern
        ])

    # --------------------------------------------------------
    # CATEGORY FILTER
    # --------------------------------------------------------

    if category:

        sql += """
            AND products.category = ?
        """

        parameters.append(
            category
        )

    # --------------------------------------------------------
    # NEWEST PRODUCTS FIRST
    # --------------------------------------------------------

    sql += """
        ORDER BY products.created_at DESC
    """

    products = conn.execute(
        sql,
        parameters
    ).fetchall()

    conn.close()

    # --------------------------------------------------------
    # MARKETPLACE PAGE
    # --------------------------------------------------------

    return render_template(
        "marketplace.html",

        products=products,

        categories=MARKETPLACE_CATEGORIES,

        query=search or "",

        selected_category=category
    )


# ============================================================
# ADD / SELL PRODUCT
# ============================================================

@app.route(
    "/marketplace/add",
    methods=["GET", "POST"]
)
def add_product():

    # --------------------------------------------------------
    # LOGIN REQUIRED
    # --------------------------------------------------------

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    # ========================================================
    # GET
    # ========================================================
    #
    # Facebook/TikTok-style Marketplace:
    # Clicking "Sell Product" opens the product creation page.
    #
    # ========================================================

    if request.method == "GET":

        return render_template(
            "add_product.html",

            categories=MARKETPLACE_CATEGORIES
        )

    # ========================================================
    # POST
    # ========================================================

    # --------------------------------------------------------
    # PRODUCT NAME
    # --------------------------------------------------------

    name = clean_text(
        request.form.get("name"),
        MAX_PRODUCT_NAME_LENGTH
    )

    # --------------------------------------------------------
    # DESCRIPTION
    # --------------------------------------------------------

    description = clean_text(
        request.form.get("description"),
        MAX_PRODUCT_DESCRIPTION_LENGTH
    )

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price_text = request.form.get(
        "price",
        ""
    ).strip()

    # --------------------------------------------------------
    # CATEGORY
    # --------------------------------------------------------

    category = clean_text(
        request.form.get("category"),
        MAX_NAME_LENGTH
    )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    location = clean_text(
        request.form.get("location"),
        MAX_LOCATION_LENGTH
    )

    # --------------------------------------------------------
    # IMAGE
    # --------------------------------------------------------

    image = request.files.get(
        "image"
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    if not name:

        return (
            "Product name is required and must not exceed "
            "150 characters."
        ), 400

    if not description:

        return (
            "Product description is required and must not "
            "exceed 3000 characters."
        ), 400

    if not price_text:

        return (
            "Product price is required."
        ), 400

    if not category:

        return (
            "Please select a category."
        ), 400

    if category not in MARKETPLACE_CATEGORIES:

        return (
            "Invalid marketplace category."
        ), 400

    if not location:

        return (
            "Location is required and must not exceed "
            "150 characters."
        ), 400

    # ========================================================
    # PRICE VALIDATION
    # ========================================================

    try:

        price = float(
            price_text
        )

        if not math.isfinite(price):

            return (
                "Please enter a valid price."
            ), 400

        if price < 0:

            return (
                "Price cannot be negative."
            ), 400

        if price > MAX_PRICE:

            return (
                "Price is too high."
            ), 400

    except (
        ValueError,
        OverflowError
    ):

        return (
            "Please enter a valid price."
        ), 400

    # ========================================================
    # IMAGE UPLOAD
    # ========================================================

    image_filename = ""

    if image and image.filename:

        # ----------------------------------------------------
        # SECURITY VALIDATION
        # ----------------------------------------------------

        if not validate_image(image):

            return (
                "Invalid image. "
                "Please upload a genuine "
                "PNG, JPG, JPEG or GIF image "
                "under 4096x4096 pixels."
            ), 400

        # ----------------------------------------------------
        # EXTENSION
        # ----------------------------------------------------

        extension = image.filename.rsplit(
            ".",
            1
        )[1].lower()

        # ----------------------------------------------------
        # UNIQUE FILE NAME
        # ----------------------------------------------------

        image_filename = (
            "product_"
            + str(uuid4())
            + "."
            + extension
        )

        # ----------------------------------------------------
        # SAVE IMAGE
        # ----------------------------------------------------

        image.save(
            safe_upload_path(
                image_filename
            )
        )

    # ========================================================
    # DATABASE CONNECTION
    # ========================================================

    conn = get_db_connection()

    try:

        # ====================================================
        # CREATE PRODUCT
        # ====================================================

        cursor = conn.execute(
            """
            INSERT INTO products
            (
                seller_id,
                name,
                description,
                price,
                category,
                location,
                image,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["user_id"],
                name,
                description,
                price,
                category,
                location,
                image_filename,
                "available"
            )
        )

        # ====================================================
        # EXACT NEW PRODUCT ID
        # ====================================================

        new_product_id = cursor.lastrowid

        # ====================================================
        # GET SELLER
        # ====================================================

        seller = conn.execute(
            """
            SELECT
                id,
                name
            FROM users
            WHERE id = ?
            """,
            (
                session["user_id"],
            )
        ).fetchone()

        seller_name = (
            seller["name"]
            if seller
            else "A student"
        )

        # ====================================================
        # GET FRIENDS
        # ====================================================

        friends = conn.execute(
            """
            SELECT
                friend_id
            FROM friends
            WHERE user_id = ?
            """,
            (
                session["user_id"],
            )
        ).fetchall()

        # ====================================================
        # NOTIFY FRIENDS
        # ====================================================

        if new_product_id:

            for friend in friends:

                conn.execute(
                    """
                    INSERT INTO notifications
                    (
                        user_id,
                        sender_id,
                        type,
                        message,
                        link
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        friend["friend_id"],

                        session["user_id"],

                        "marketplace",

                        (
                            f"{seller_name} listed "
                            f"{name} on Marketplace 🛍️"
                        ),

                        (
                            f"/marketplace/product/"
                            f"{new_product_id}"
                        )
                    )
                )

        # ====================================================
        # SAVE PRODUCT + NOTIFICATIONS
        # ====================================================

        conn.commit()

    except Exception:

        # ----------------------------------------------------
        # Roll back database changes if something fails.
        # ----------------------------------------------------

        conn.rollback()

        raise

    finally:

        conn.close()

    # ========================================================
    # SUCCESS
    # ========================================================

    return redirect(
        url_for("marketplace")
    )


# ============================================================
# PRODUCT DETAIL
# ============================================================

@app.route(
    "/marketplace/product/<int:product_id>"
)
def product_detail(product_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    product = conn.execute(
        """
        SELECT
            products.*,
            users.name AS seller_name,
            users.email AS seller_email,
            users.university AS seller_university,
            users.id AS seller_id

        FROM products

        JOIN users
        ON products.seller_id = users.id

        WHERE products.id = ?
        """,
        (
            product_id,
        )
    ).fetchone()

    conn.close()

    if not product:

        return "Product not found.", 404

    return render_template(
        "product_detail.html",
        product=product
    )


# ============================================================
# MY PRODUCTS
# ============================================================

@app.route(
    "/marketplace/my-products"
)
def my_products():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    products = conn.execute(
        """
        SELECT *
        FROM products
        WHERE seller_id = ?
        ORDER BY created_at DESC
        """,
        (
            session["user_id"],
        )
    ).fetchall()

    conn.close()

    return render_template(
        "my_products.html",
        products=products
    )


# ============================================================
# DELETE PRODUCT
# ============================================================

@app.route(
    "/marketplace/delete/<int:product_id>",
    methods=["POST"]
)
def delete_product(product_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    product = conn.execute(
        """
        SELECT *
        FROM products
        WHERE id = ?
        AND seller_id = ?
        """,
        (
            product_id,
            session["user_id"]
        )
    ).fetchone()

    if not product:

        conn.close()

        return (
            "Product not found or "
            "you do not own this product."
        ), 404

    if product["image"]:

        image_path = safe_upload_path(
            product["image"]
        )

        if os.path.isfile(image_path):

            try:
                os.remove(image_path)
            except OSError:
                pass

    conn.execute(
        """
        DELETE FROM products
        WHERE id = ?
        AND seller_id = ?
        """,
        (
            product_id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("my_products")
    )


# ============================================================
# MARK PRODUCT AS SOLD
# ============================================================

@app.route(
    "/marketplace/sold/<int:product_id>",
    methods=["POST"]
)
def mark_product_sold(product_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    product = conn.execute(
        """
        SELECT id
        FROM products
        WHERE id = ?
        AND seller_id = ?
        """,
        (
            product_id,
            session["user_id"]
        )
    ).fetchone()

    if not product:

        conn.close()

        return (
            "Product not found or "
            "you do not own this product."
        ), 404

    conn.execute(
        """
        UPDATE products
        SET status = 'sold'
        WHERE id = ?
        AND seller_id = ?
        """,
        (
            product_id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("my_products")
    )


# ============================================================
# MESSAGES
# ============================================================

@app.route("/messages")
def messages():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    # ========================================================
    # PRIVATE CONVERSATIONS
    # ========================================================

    conversations = conn.execute(
        """
        SELECT
            u.id,
            u.name,
            u.profile_picture,
            m.message,
            m.created_at,
            m.sender_id,
            m.receiver_id

        FROM messages m

        JOIN users u
        ON u.id =
            CASE
                WHEN m.sender_id = ?
                THEN m.receiver_id
                ELSE m.sender_id
            END

        WHERE
            m.id IN (

                SELECT MAX(m2.id)

                FROM messages m2

                WHERE
                    m2.sender_id = ?
                    OR
                    m2.receiver_id = ?

                GROUP BY
                    CASE
                        WHEN m2.sender_id = ?
                        THEN m2.receiver_id
                        ELSE m2.sender_id
                    END
            )

        ORDER BY m.created_at DESC
        """,
        (
            current_user_id,
            current_user_id,
            current_user_id,
            current_user_id
        )
    ).fetchall()

    # ========================================================
    # GROUP CONVERSATIONS
    # ========================================================

    group_conversations = conn.execute(
        """
        SELECT
            g.id AS group_id,
            g.name AS group_name,
            gm.message,
            gm.created_at,
            gm.sender_id,
            u.name AS sender_name,
            u.profile_picture AS sender_picture

        FROM group_messages gm

        JOIN groups g
        ON g.id = gm.group_id

        JOIN users u
        ON u.id = gm.sender_id

        JOIN group_members membership
        ON membership.group_id = g.id

        WHERE membership.user_id = ?

        AND gm.id IN (

            SELECT MAX(gm2.id)

            FROM group_messages gm2

            WHERE gm2.group_id IN (

                SELECT group_id
                FROM group_members
                WHERE user_id = ?

            )

            GROUP BY gm2.group_id
        )

        ORDER BY gm.created_at DESC
        """,
        (
            current_user_id,
            current_user_id
        )
    ).fetchall()

    conn.close()

    return render_template(
        "messages.html",
        conversations=conversations,
        group_conversations=group_conversations
    )


# ============================================================
# POPUP NOTIFICATIONS API
# ============================================================

@app.route("/api/notifications/unread")
def unread_notifications():

    if "user_id" not in session:
        return {
            "unread_count": 0,
            "notifications": []
        }, 401

    try:
        after_id = int(
            request.args.get("after_id", 0)
        )
    except (TypeError, ValueError):
        after_id = 0

    conn = get_db_connection()

    # Get total unread notification count
    unread_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM notifications
        WHERE user_id = ?
        AND is_read = 0
        """,
        (
            session["user_id"],
        )
    ).fetchone()[0]

    # Get new unread notifications
    notifications_list = conn.execute(
        """
        SELECT
            notifications.id,
            notifications.type,
            notifications.message,
            notifications.link,
            notifications.created_at,
            users.name AS sender_name,
            users.profile_picture AS sender_picture

        FROM notifications

        LEFT JOIN users
        ON notifications.sender_id = users.id

        WHERE notifications.user_id = ?
        AND notifications.is_read = 0
        AND notifications.id > ?

        ORDER BY notifications.id ASC
        LIMIT 20
        """,
        (
            session["user_id"],
            after_id
        )
    ).fetchall()

    conn.close()

    return {
        "unread_count": unread_count,

        "notifications": [
            {
                "id": notification["id"],
                "type": notification["type"],
                "message": notification["message"],
                "link": notification["link"] or "",
                "created_at": notification["created_at"],
                "sender_name": (
                    notification["sender_name"]
                    or "UniCamplink"
                ),
                "sender_picture": (
                    notification["sender_picture"]
                    or ""
                )
            }
            for notification in notifications_list
        ]
    }

# ============================================================
# MARK NOTIFICATION AS READ
# ============================================================

@app.route(
    "/api/notifications/<int:notification_id>/read",
    methods=["POST"]
)
def mark_notification_as_read(notification_id):

    if "user_id" not in session:
        return {
            "success": False,
            "error": "Please log in."
        }, 401

    conn = get_db_connection()

    notification = conn.execute(
        """
        SELECT id
        FROM notifications
        WHERE id = ?
        AND user_id = ?
        """,
        (
            notification_id,
            session["user_id"]
        )
    ).fetchone()

    if not notification:
        conn.close()

        return {
            "success": False,
            "error": "Notification not found."
        }, 404

    conn.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
        AND user_id = ?
        """,
        (
            notification_id,
            session["user_id"]
        )
    )

    conn.commit()
    conn.close()

    return {
        "success": True
    }

# ============================================================
# NOTIFICATIONS
# ============================================================

@app.route("/notifications")
def notifications():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    conn = get_db_connection()

    notifications_list = conn.execute(
        """
        SELECT
            notifications.*,
            users.name AS sender_name,
            users.profile_picture AS sender_picture

        FROM notifications

        LEFT JOIN users
        ON notifications.sender_id = users.id

        WHERE notifications.user_id = ?

        ORDER BY notifications.created_at DESC
        """,
        (
            session["user_id"],
        )
    ).fetchall()

    conn.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE user_id = ?
        """,
        (
            session["user_id"],
        )
    )

    conn.commit()
    conn.close()

    return render_template(
        "notifications.html",
        notifications=notifications_list
    )


# ============================================================
# SEND FRIEND REQUEST
# ============================================================

@app.route(
    "/send-friend-request/<int:user_id>",
    methods=["POST"]
)
def send_friend_request(user_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    if user_id == current_user_id:

        return redirect(
            url_for(
                "view_user",
                user_id=user_id
            )
        )

    conn = get_db_connection()

    receiver = conn.execute(
        """
        SELECT id
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not receiver:

        conn.close()

        return "Student not found.", 404

    # Prevent sending another request when already friends.
    already_friends = conn.execute(
        """
        SELECT id
        FROM friends
        WHERE user_id = ?
        AND friend_id = ?
        """,
        (
            current_user_id,
            user_id
        )
    ).fetchone()

    if already_friends:

        conn.close()

        return redirect(
            url_for(
                "view_user",
                user_id=user_id
            )
        )

    existing_request = conn.execute(
        """
        SELECT *
        FROM friend_requests
        WHERE sender_id = ?
        AND receiver_id = ?
        """,
        (
            current_user_id,
            user_id
        )
    ).fetchone()

    if existing_request:

        conn.close()

        return redirect(
            url_for(
                "view_user",
                user_id=user_id
            )
        )

    reverse_request = conn.execute(
        """
        SELECT *
        FROM friend_requests
        WHERE sender_id = ?
        AND receiver_id = ?
        AND status = 'pending'
        """,
        (
            user_id,
            current_user_id
        )
    ).fetchone()

    if reverse_request:

        conn.close()

        return redirect(
            url_for(
                "view_user",
                user_id=user_id
            )
        )

    conn.execute(
        """
        INSERT INTO friend_requests
        (
            sender_id,
            receiver_id,
            status
        )
        VALUES (?, ?, ?)
        """,
        (
            current_user_id,
            user_id,
            "pending"
        )
    )

    conn.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            sender_id,
            type,
            message,
            link
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            current_user_id,
            "friend_request",
            "sent you a friend request ❤️",
            "/friend-requests"
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for(
            "view_user",
            user_id=user_id
        )
    )


# ============================================================
# FRIEND REQUESTS
# ============================================================

@app.route("/friend-requests")
def friend_requests():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    requests = conn.execute(
        """
        SELECT
            friend_requests.id,
            friend_requests.sender_id,
            users.name,
            users.university,
            users.profile_picture

        FROM friend_requests

        JOIN users
        ON friend_requests.sender_id = users.id

        WHERE friend_requests.receiver_id = ?

        AND friend_requests.status = 'pending'

        ORDER BY friend_requests.created_at DESC
        """,
        (
            current_user_id,
        )
    ).fetchall()

    conn.close()

    return render_template(
        "friend_requests.html",
        requests=requests
    )


# ============================================================
# FRIENDS LIST
# ============================================================

@app.route("/friends")
def friends():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    friends = conn.execute(
        """
        SELECT
            users.id,
            users.name,
            users.university,
            users.profile_picture

        FROM friends

        JOIN users
        ON friends.friend_id = users.id

        WHERE friends.user_id = ?

        ORDER BY users.name ASC
        """,
        (
            current_user_id,
        )
    ).fetchall()

    conn.close()

    return render_template(
        "friends.html",
        friends=friends
    )


# ============================================================
# ACCEPT FRIEND REQUEST
# ============================================================

@app.route(
    "/accept-friend-request/<int:request_id>",
    methods=["POST"]
)
def accept_friend_request(request_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    friend_request = conn.execute(
        """
        SELECT *
        FROM friend_requests
        WHERE id = ?
        AND receiver_id = ?
        AND status = 'pending'
        """,
        (
            request_id,
            current_user_id
        )
    ).fetchone()

    if not friend_request:

        conn.close()

        return redirect(
            url_for("friend_requests")
        )

    conn.execute(
        """
        UPDATE friend_requests
        SET status = 'accepted'
        WHERE id = ?
        """,
        (
            request_id,
        )
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO friends
        (
            user_id,
            friend_id
        )
        VALUES (?, ?)
        """,
        (
            current_user_id,
            friend_request["sender_id"]
        )
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO friends
        (
            user_id,
            friend_id
        )
        VALUES (?, ?)
        """,
        (
            friend_request["sender_id"],
            current_user_id
        )
    )

    conn.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            sender_id,
            type,
            message,
            link
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            friend_request["sender_id"],
            current_user_id,
            "friend_accepted",
            "accepted your friend request ❤️",
            "/profile"
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("friend_requests")
    )


# ============================================================
# REJECT FRIEND REQUEST
# ============================================================

@app.route(
    "/reject-friend-request/<int:request_id>",
    methods=["POST"]
)
def reject_friend_request(request_id):

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    conn = get_db_connection()

    friend_request = conn.execute(
        """
        SELECT *
        FROM friend_requests
        WHERE id = ?
        AND receiver_id = ?
        AND status = 'pending'
        """,
        (
            request_id,
            current_user_id
        )
    ).fetchone()

    if not friend_request:

        conn.close()

        return redirect(
            url_for("friend_requests")
        )

    conn.execute(
        """
        UPDATE friend_requests
        SET status = 'rejected'
        WHERE id = ?
        """,
        (
            request_id,
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("friend_requests")
    )




# ============================================================
# LOGOUT
# ============================================================

@app.route(
    "/logout",
    methods=["POST"]
)
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# PRIVATE CHAT
# ============================================================

@app.route(
    "/chat/<int:user_id>",
    methods=["GET", "POST"]
)
def chat(user_id):

    # --------------------------------------------------------
    # LOGIN REQUIRED
    # --------------------------------------------------------

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    current_user_id = session["user_id"]

    # --------------------------------------------------------
    # PREVENT SELF-MESSAGING
    # --------------------------------------------------------

    if user_id == current_user_id:

        return redirect(
            url_for("messages")
        )

    conn = get_db_connection()

    # --------------------------------------------------------
    # FIND OTHER USER
    # --------------------------------------------------------

    other_user = conn.execute(
        """
        SELECT
            id,
            name,
            university,
            profile_picture,
            last_seen
        FROM users
        WHERE id = ?
        """,
        (
            user_id,
        )
    ).fetchone()

    if not other_user:

        conn.close()

        return "Student not found.", 404

    # --------------------------------------------------------
    # CHECK MARKETPLACE CONTACT
    #
    # This is kept so seller contact through a product
    # continues to work normally.
    # --------------------------------------------------------

    product_id = request.args.get(
        "product_id",
        type=int
    )

    is_marketplace_contact = False

    if product_id:

        product = conn.execute(
            """
            SELECT id
            FROM products
            WHERE id = ?
            AND seller_id = ?
            """,
            (
                product_id,
                user_id
            )
        ).fetchone()

        if product:

            is_marketplace_contact = True

    # --------------------------------------------------------
    # SEND MESSAGE
    #
    # Students can now message other students directly.
    # Friendship is NOT required.
    # Marketplace seller contact remains supported.
    # --------------------------------------------------------

    if request.method == "POST":

        message = clean_text(
            request.form.get("message"),
            MAX_MESSAGE_LENGTH
        )

        if not message:

            conn.close()

            return (
                "Message cannot be empty and must not "
                "exceed 2000 characters."
            ), 400

        conn.execute(
            """
            INSERT INTO messages
            (
                sender_id,
                receiver_id,
                message
            )
            VALUES (?, ?, ?)
            """,
            (
                current_user_id,
                user_id,
                message
            )
        )

        conn.execute(
            """
            INSERT INTO notifications
            (
                user_id,
                sender_id,
                type,
                message,
                link
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                current_user_id,
                "message",
                "sent you a message 💬",
                "/chat/" + str(current_user_id)
            )
        )

        # --------------------------------------------------------
        # BROWSER PUSH - NEW DIRECT MESSAGE
        # --------------------------------------------------------

        sender = conn.execute(
            """
            SELECT name
            FROM users
            WHERE id = ?
            """,
            (current_user_id,)
        ).fetchone()

        sender_name = (
            sender["name"]
            if sender and sender["name"]
            else "Someone"
        )

        push_message = message[:180]

        if len(message) > 180:
            push_message += "..."

        send_push_notification(
            user_id,
            "\U0001F4AC " + sender_name,
            push_message,
            "/chat/" + str(current_user_id),
            "unicamplink-message"
        )

        conn.commit()
        conn.close()

        # Keep the user in the same chat.
        # Preserve product_id when this is a marketplace
        # seller conversation.
        if is_marketplace_contact and product_id:

            return redirect(
                url_for(
                    "chat",
                    user_id=user_id,
                    product_id=product_id
                )
            )

        return redirect(
            url_for(
                "chat",
                user_id=user_id
            )
        )

    # --------------------------------------------------------
    # LOAD CHAT MESSAGES
    # --------------------------------------------------------

    chat_messages = conn.execute(
        """
        SELECT
            messages.*,
            users.name AS sender_name,
            users.profile_picture

        FROM messages

        JOIN users
        ON users.id = messages.sender_id

        WHERE
            (
                messages.sender_id = ?
                AND messages.receiver_id = ?
            )

            OR

            (
                messages.sender_id = ?
                AND messages.receiver_id = ?
            )

        ORDER BY
            messages.created_at ASC,
            messages.id ASC
        """,
        (
            current_user_id,
            user_id,
            user_id,
            current_user_id
        )
    ).fetchall()

    # --------------------------------------------------------
    # MARK RECEIVED MESSAGES AS READ
    # --------------------------------------------------------

    conn.execute(
        """
        UPDATE messages
        SET is_read = 1
        WHERE sender_id = ?
        AND receiver_id = ?
        """,
        (
            user_id,
            current_user_id
        )
    )

    conn.commit()
    conn.close()

    return render_template(
        "chat.html",
        other_user=other_user,
        messages=chat_messages
    )


# ============================================================
# LIVE CHAT MESSAGES API
# ============================================================

@app.route("/api/chat/<int:user_id>/messages")
def api_chat_messages(user_id):

    if "user_id" not in session:
        return {
            "messages": []
        }, 401

    current_user_id = session["user_id"]

    # Prevent self-chat
    if user_id == current_user_id:
        return {
            "messages": []
        }, 400

    conn = get_db_connection()

    # Check that the other user exists
    other_user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id = ?
        """,
        (
            user_id,
        )
    ).fetchone()

    if not other_user:
        conn.close()

        return {
            "messages": []
        }, 404

    # --------------------------------------------------------
    # CHECK FRIENDSHIP
    # --------------------------------------------------------

    friendship = conn.execute(
        """
        SELECT id
        FROM friends
        WHERE user_id = ?
        AND friend_id = ?
        """,
        (
            current_user_id,
            user_id
        )
    ).fetchone()

    is_friend = bool(friendship)

    # --------------------------------------------------------
    # CHECK EXISTING CONVERSATION
    # --------------------------------------------------------

    existing_conversation = conn.execute(
        """
        SELECT id
        FROM messages
        WHERE
            (
                sender_id = ?
                AND receiver_id = ?
            )
            OR
            (
                sender_id = ?
                AND receiver_id = ?
            )
        LIMIT 1
        """,
        (
            current_user_id,
            user_id,
            user_id,
            current_user_id
        )
    ).fetchone()

    has_existing_conversation = bool(
        existing_conversation
    )

    # --------------------------------------------------------
    # CHECK MARKETPLACE CONTACT
    # --------------------------------------------------------

    product_id = request.args.get(
        "product_id",
        type=int
    )

    is_marketplace_contact = False

    if product_id:

        product = conn.execute(
            """
            SELECT id
            FROM products
            WHERE id = ?
            AND seller_id = ?
            """,
            (
                product_id,
                user_id
            )
        ).fetchone()

        if product:
            is_marketplace_contact = True

    # --------------------------------------------------------
    # AUTHORIZE CHAT
    # --------------------------------------------------------

    if not (
        is_friend
        or is_marketplace_contact
        or has_existing_conversation
    ):
        conn.close()

        return {
            "messages": []
        }, 403

    # --------------------------------------------------------
    # GET MESSAGES
    # --------------------------------------------------------

    chat_messages = conn.execute(
        """
        SELECT
            messages.id,
            messages.sender_id,
            messages.receiver_id,
            messages.message,
            messages.created_at,
            users.name AS sender_name,
            users.profile_picture

        FROM messages

        JOIN users
        ON users.id = messages.sender_id

        WHERE
            (
                messages.sender_id = ?
                AND messages.receiver_id = ?
            )

            OR

            (
                messages.sender_id = ?
                AND messages.receiver_id = ?
            )

        ORDER BY
            messages.created_at ASC,
            messages.id ASC
        """,
        (
            current_user_id,
            user_id,
            user_id,
            current_user_id
        )
    ).fetchall()

    # --------------------------------------------------------
    # MARK RECEIVED MESSAGES AS READ
    # --------------------------------------------------------

    conn.execute(
        """
        UPDATE messages
        SET is_read = 1
        WHERE sender_id = ?
        AND receiver_id = ?
        """,
        (
            user_id,
            current_user_id
        )
    )

    conn.commit()
    conn.close()

    return {
        "messages": [
            {
                "id": message["id"],
                "sender_id": message["sender_id"],
                "receiver_id": message["receiver_id"],
                "message": message["message"],
                "created_at": message["created_at"],
                "sender_name": (
                    message["sender_name"]
                    or "UniCamplink User"
                ),
                "profile_picture": (
                    message["profile_picture"]
                    or ""
                )
            }
            for message in chat_messages
         ],
    "other_user_last_seen": (
        other_user["last_seen"]
        or ""
    )
}
    

# ============================================================
# UPDATE USER LAST SEEN
# ============================================================
# ADMIN — DASHBOARD
# ============================================================

@app.route("/admin")
def admin_dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return "Admin access is not configured yet.", 500

    conn = get_db_connection()

    current_user = conn.execute(
        """
        SELECT
            id,
            name,
            email
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()
    print(
    "ADMIN DEBUG:",
    "session_user_id=", session.get("user_id"),
    "current_user=", dict(current_user) if current_user else None,
    "ADMIN_EMAIL=", repr(ADMIN_EMAIL)
)

    if (
        not current_user
        or current_user["email"].lower() != ADMIN_EMAIL
    ):
        conn.close()
        return "Access denied.", 403

    # --------------------------------------------------------
    # PLATFORM STATISTICS
    # --------------------------------------------------------

    total_users = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        """
    ).fetchone()[0]

    active_members = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE last_seen IS NOT NULL
        AND last_seen >= datetime('now', '-15 minutes')
        """
    ).fetchone()[0]

    total_posts = conn.execute(
        """
        SELECT COUNT(*)
        FROM posts
        """
    ).fetchone()[0]

    total_groups = conn.execute(
        """
        SELECT COUNT(*)
        FROM groups
        """
    ).fetchone()[0]

    total_products = conn.execute(
        """
        SELECT COUNT(*)
        FROM products
        """
    ).fetchone()[0]

    total_messages = conn.execute(
        """
        SELECT COUNT(*)
        FROM messages
        """
    ).fetchone()[0]

    total_friend_requests = conn.execute(
        """
        SELECT COUNT(*)
        FROM friend_requests
        """
    ).fetchone()[0]

    # --------------------------------------------------------
    # ADVERTISEMENT STATISTICS
    # --------------------------------------------------------

    total_advertisements = conn.execute(
        """
        SELECT COUNT(*)
        FROM advertisement_requests
        """
    ).fetchone()[0]

    pending_advertisements = conn.execute(
        """
        SELECT COUNT(*)
        FROM advertisement_requests
        WHERE status = 'pending'
        """
    ).fetchone()[0]

    # --------------------------------------------------------
    # CAMPUS AMBASSADORS
    # --------------------------------------------------------

    total_ambassadors = conn.execute(
        """
        SELECT COUNT(*)
        FROM campus_ambassadors
        WHERE active = 1
        """
    ).fetchone()[0]
    total_reports = conn.execute(
        """
        SELECT COUNT(*)
        FROM reports
        """
    ).fetchone()[0]

    pending_reports = conn.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'pending'
        """
    ).fetchone()[0]
    # --------------------------------------------------------
    # VERIFIED STUDENTS
    # --------------------------------------------------------

    total_verified_students = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE is_verified_student = 1
        """
    ).fetchone()[0]

    # --------------------------------------------------------
    # RECENT MEMBERS
    # --------------------------------------------------------

    recent_users = conn.execute(
        """
        SELECT
            id,
            name,
            email,
            university,
            profile_picture,
            joined_at,
            last_seen
        FROM users
        ORDER BY
            COALESCE(
                joined_at,
                '9999-12-31 23:59:59'
            ) DESC,
            id DESC
        LIMIT 10
        """
    ).fetchall()

    conn.close()

    return render_template(
        "admin_dashboard.html",

        current_user=current_user,

        total_users=total_users,
        active_members=active_members,
        total_posts=total_posts,
        total_groups=total_groups,
        total_products=total_products,
        total_messages=total_messages,
        total_friend_requests=total_friend_requests,

        total_advertisements=total_advertisements,
        pending_advertisements=pending_advertisements,

        total_ambassadors=total_ambassadors,
        total_reports=total_reports,
        pending_reports=pending_reports,
        total_verified_students=total_verified_students,

        recent_users=recent_users
    )
@app.route("/admin/announcements", methods=["GET"])
def admin_announcements():

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    announcements = conn.execute(
        """
        SELECT
            announcements.id,
            announcements.title,
            announcements.message,
            announcements.is_active,
            announcements.created_by,
            announcements.created_at,
            announcements.updated_at,
            users.name AS creator_name
        FROM announcements
        LEFT JOIN users
            ON users.id = announcements.created_by
        ORDER BY
            announcements.is_active DESC,
            announcements.created_at DESC,
            announcements.id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "admin_announcements.html",
        current_user=current_user,
        announcements=announcements
    )
@app.route(
    "/admin/announcements/create",
    methods=["POST"]
)
def admin_create_announcement():

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    title = clean_text(
        request.form.get("title"),
        150
    )

    message = clean_text(
        request.form.get("message"),
        3000
    )

    is_active = (
        1
        if request.form.get("is_active") == "1"
        else 0
    )

    notify_users = (
        request.form.get("notify_users") == "1"
    )

    if not title:
        conn.close()
        return "Announcement title is required.", 400

    if not message:
        conn.close()
        return "Announcement message is required.", 400

    cursor = conn.execute(
        """
        INSERT INTO announcements
        (
            title,
            message,
            is_active,
            created_by
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            title,
            message,
            is_active,
            current_user["id"]
        )
    )

    announcement_id = cursor.lastrowid

    if notify_users and is_active:

        notification_message = (
            f"📢 {title}: {message}"
        )

        users = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id != ?
            """,
            (current_user["id"],)
        ).fetchall()

        for user in users:

            conn.execute(
                """
                INSERT INTO notifications
                (
                    user_id,
                    sender_id,
                    type,
                    message,
                    link
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    current_user["id"],
                    "announcement",
                    notification_message,
                    "/announcements"
                )
            )

            push_body = message[:180] + ("..." if len(message) > 180 else "")

            send_push_notification(
                user["id"],
                "\U0001F4E2 " + title,
                push_body,
                "/announcements",
                "unicamplink-announcement"
            )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_announcements")
    )
@app.route(
    "/admin/announcements/<int:announcement_id>/toggle",
    methods=["POST"]
)
def admin_toggle_announcement(announcement_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    announcement = conn.execute(
        """
        SELECT id, is_active
        FROM announcements
        WHERE id = ?
        """,
        (announcement_id,)
    ).fetchone()

    if not announcement:
        conn.close()
        return "Announcement not found.", 404

    new_status = (
        0
        if announcement["is_active"]
        else 1
    )

    conn.execute(
        """
        UPDATE announcements
        SET
            is_active = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            new_status,
            announcement_id
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_announcements")
    )
@app.route(
    "/admin/announcements/<int:announcement_id>/delete",
    methods=["POST"]
)
def admin_delete_announcement(announcement_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    announcement = conn.execute(
        """
        SELECT id
        FROM announcements
        WHERE id = ?
        """,
        (announcement_id,)
    ).fetchone()

    if not announcement:
        conn.close()
        return "Announcement not found.", 404

    conn.execute(
        """
        DELETE FROM announcements
        WHERE id = ?
        """,
        (announcement_id,)
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_announcements")
    )
# ============================================================
# ADMIN — EDIT ANNOUNCEMENT
# ============================================================

@app.route(
    "/admin/announcements/<int:announcement_id>/edit",
    methods=["POST"]
)
def admin_edit_announcement(announcement_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    title = clean_text(
        request.form.get("title"),
        150
    )

    message = clean_text(
        request.form.get("message"),
        3000
    )

    if not title or not message:
        conn.close()
        return (
            "Announcement title and message are required.",
            400
        )

    announcement = conn.execute(
        """
        SELECT id
        FROM announcements
        WHERE id = ?
        """,
        (announcement_id,)
    ).fetchone()

    if not announcement:
        conn.close()
        return "Announcement not found.", 404

    conn.execute(
        """
        UPDATE announcements
        SET
            title = ?,
            message = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            title,
            message,
            announcement_id
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_announcements")
    )
# ============================================================
# ADMIN — MEMBERS
# ============================================================

@app.route("/admin/members")
def admin_members():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return "Admin access is not configured yet.", 500

    search = clean_text(
        request.args.get("q"),
        MAX_SEARCH_LENGTH
    )

    if search is None:
        return (
            "Member search query is too long. "
            "Maximum length is 100 characters."
        ), 400

    search = search or ""

    conn = get_db_connection()

    current_user = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["email"].lower() != ADMIN_EMAIL:
        conn.close()
        return "Access denied.", 403

    total_users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active_members = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE last_seen IS NOT NULL
        AND last_seen >= datetime('now', '-15 minutes')
        """
    ).fetchone()[0]

    if search:
        pattern = f"%{search}%"
        users = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                university,
                profile_picture,
                joined_at,
                last_seen,
                CASE
                    WHEN last_seen IS NOT NULL
                    AND last_seen >= datetime('now', '-15 minutes')
                    THEN 1
                    ELSE 0
                END AS is_active,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM campus_ambassadors ca
                        WHERE ca.user_id = users.id
                        AND ca.active = 1
                    )
                    THEN 1
                    ELSE 0
                END AS is_campus_ambassador
            FROM users
            WHERE
                LOWER(name) LIKE LOWER(?)
                OR LOWER(email) LIKE LOWER(?)
                OR LOWER(COALESCE(university, '')) LIKE LOWER(?)
            ORDER BY
                COALESCE(joined_at, '9999-12-31 23:59:59') DESC,
                id DESC
            """,
            (pattern, pattern, pattern)
        ).fetchall()
    else:
        users = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                university,
                profile_picture,
                joined_at,
                last_seen,
                CASE
                    WHEN last_seen IS NOT NULL
                    AND last_seen >= datetime('now', '-15 minutes')
                    THEN 1
                    ELSE 0
                END AS is_active,
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM campus_ambassadors ca
                        WHERE ca.user_id = users.id
                        AND ca.active = 1
                    )
                    THEN 1
                    ELSE 0
                END AS is_campus_ambassador
            FROM users
            ORDER BY
                COALESCE(joined_at, '9999-12-31 23:59:59') DESC,
                id DESC
            """
        ).fetchall()

    conn.close()

    return render_template(
        "admin_members.html",
        users=users,
        total_users=total_users,
        active_members=active_members,
        search=search
    )

# ============================================================
# ADMIN — CAMPUS AMBASSADORS
# ============================================================


def _require_admin():
    """Return the logged-in admin row, or a Flask response tuple."""
    if "user_id" not in session:
        return None, redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return None, ("Admin access is not configured yet.", 500)

    conn = get_db_connection()
    current_user = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["email"].lower() != ADMIN_EMAIL:
        conn.close()
        return None, ("Access denied.", 403)

    return current_user, conn
# ============================================================
# ADMIN — VERIFIED STUDENTS
# RAZOR / FACEBOOK-TIKTOK STYLE ADMIN PAGE
# ============================================================

@app.route("/admin/verified-students")
def admin_verified_students():

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # --------------------------------------------------------
    # SEARCH
    # --------------------------------------------------------

    search = clean_text(
        request.args.get("q"),
        MAX_SEARCH_LENGTH
    )

    if search is None:
        conn.close()

        return (
            "Search query is too long. "
            "Maximum length is 100 characters."
        ), 400

    search = search or ""

    # --------------------------------------------------------
    # SEARCH STUDENTS
    # --------------------------------------------------------

    if search:

        pattern = f"%{search}%"

        users = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                university,
                profile_picture,
                is_verified_student,
                verified_at,
                verified_by

            FROM users

            WHERE
                LOWER(name) LIKE LOWER(?)

                OR LOWER(email) LIKE LOWER(?)

                OR LOWER(
                    COALESCE(
                        university,
                        ''
                    )
                ) LIKE LOWER(?)

            ORDER BY
                COALESCE(
                    joined_at,
                    '9999-12-31 23:59:59'
                ) DESC,

                id DESC

            LIMIT 100
            """,
            (
                pattern,
                pattern,
                pattern
            )
        ).fetchall()

    # --------------------------------------------------------
    # ALL STUDENTS
    # --------------------------------------------------------

    else:

        users = conn.execute(
            """
            SELECT
                id,
                name,
                email,
                university,
                profile_picture,
                is_verified_student,
                verified_at,
                verified_by

            FROM users

            ORDER BY
                COALESCE(
                    joined_at,
                    '9999-12-31 23:59:59'
                ) DESC,

                id DESC

            LIMIT 100
            """
        ).fetchall()

    # --------------------------------------------------------
    # VERIFIED COUNT
    # --------------------------------------------------------

    total_verified_students = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE is_verified_student = 1
        """
    ).fetchone()[0]

    # --------------------------------------------------------
    # TOTAL STUDENTS
    # --------------------------------------------------------

    total_students = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        """
    ).fetchone()[0]

    conn.close()

    # --------------------------------------------------------
    # RENDER RAZOR ADMIN PAGE
    # --------------------------------------------------------

    return render_template(
        "admin_verified_students.html",

        current_user=current_user,

        users=users,

        search=search,

        total_verified_students=total_verified_students,

        total_students=total_students
    )
# ============================================================
# ADMIN — VERIFIED STUDENTS
# RAZOR / FACEBOOK-TIKTOK STYLE ADMIN SYSTEM
# ============================================================


@app.route(
    "/admin/verified-students/<int:user_id>/verify",
    methods=["POST"]
)
def admin_verify_student(user_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # ========================================================
    # FIND STUDENT
    # ========================================================

    user = conn.execute(
        """
        SELECT
            id,
            name,
            is_verified_student
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()

        return (
            "Student not found.",
            404
        )

    # ========================================================
    # ALREADY VERIFIED
    # Prevent duplicate verification notifications
    # ========================================================

    if user["is_verified_student"]:

        conn.close()

        return redirect(
            url_for(
                "admin_verified_students"
            )
        )

    # ========================================================
    # VERIFY STUDENT
    # ========================================================

    conn.execute(
        """
        UPDATE users
        SET
            is_verified_student = 1,
            verified_at = CURRENT_TIMESTAMP,
            verified_by = ?
        WHERE id = ?
        """,
        (
            current_user["id"],
            user_id
        )
    )

    # ========================================================
    # SEND VERIFICATION NOTIFICATION
    # ========================================================

    conn.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            sender_id,
            type,
            message,
            link
        )
        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        (
            user["id"],
            current_user["id"],
            "verification",
            "Your account has been verified as an Official UniCamplink Verified Student. ✅",
            "/profile"
        )
    )

    conn.commit()

    conn.close()

    # ========================================================
    # RETURN TO VERIFIED STUDENTS ADMIN PAGE
    # ========================================================

    return redirect(
        url_for(
            "admin_verified_students"
        )
    )



# ============================================================
# ADMIN — UNVERIFY STUDENT
# ============================================================


@app.route(
    "/admin/verified-students/<int:user_id>/unverify",
    methods=["POST"]
)
def admin_unverify_student(user_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # ========================================================
    # FIND STUDENT
    # ========================================================

    user = conn.execute(
        """
        SELECT
            id,
            name,
            is_verified_student
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()

        return (
            "Student not found.",
            404
        )

    # ========================================================
    # ALREADY UNVERIFIED
    # ========================================================

    if not user["is_verified_student"]:

        conn.close()

        return redirect(
            url_for(
                "admin_verified_students"
            )
        )

    # ========================================================
    # REMOVE VERIFIED STATUS
    # ========================================================

    conn.execute(
        """
        UPDATE users
        SET
            is_verified_student = 0,
            verified_at = NULL,
            verified_by = NULL
        WHERE id = ?
        """,
        (
            user_id,
        )
    )

    # ========================================================
    # SEND UNVERIFICATION NOTIFICATION
    # ========================================================

    conn.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            sender_id,
            type,
            message,
            link
        )
        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        (
            user["id"],
            current_user["id"],
            "verification",
            "Your UniCamplink Verified Student status has been removed.",
            "/profile"
        )
    )

    conn.commit()

    conn.close()

    return redirect(
        url_for(
            "admin_verified_students"
        )
    )



# ============================================================
# ADMIN — CAMPUS AMBASSADORS
# RAZOR / FACEBOOK-TIKTOK STYLE ADMIN SYSTEM
# ============================================================


@app.route(
    "/admin/campus-ambassadors"
)
def admin_campus_ambassadors():

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # ========================================================
    # SEARCH
    # ========================================================

    search = clean_text(
        request.args.get("q"),
        MAX_SEARCH_LENGTH
    )

    if search is None:

        conn.close()

        return (
            "Search query is too long. "
            "Maximum length is 100 characters."
        ), 400

    pattern = (
        f"%{search}%"
        if search
        else None
    )

    # ========================================================
    # SEARCH USERS
    # ========================================================

    if pattern:

        users = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                users.university,
                users.profile_picture,

                ca.campus
                    AS ambassador_campus,

                ca.school
                    AS ambassador_school,

                ca.active
                    AS ambassador_active,

                ca.appointed_at

            FROM users

            LEFT JOIN campus_ambassadors ca
                ON ca.user_id = users.id

            WHERE

                LOWER(users.name)
                    LIKE LOWER(?)

                OR LOWER(users.email)
                    LIKE LOWER(?)

                OR LOWER(
                    COALESCE(
                        users.university,
                        ''
                    )
                )
                    LIKE LOWER(?)

                OR LOWER(
                    COALESCE(
                        ca.campus,
                        ''
                    )
                )
                    LIKE LOWER(?)

                OR LOWER(
                    COALESCE(
                        ca.school,
                        ''
                    )
                )
                    LIKE LOWER(?)

            ORDER BY
                users.name COLLATE NOCASE ASC,
                users.id ASC

            LIMIT 100
            """,
            (
                pattern,
                pattern,
                pattern,
                pattern,
                pattern
            )
        ).fetchall()

    # ========================================================
    # ALL USERS
    # ========================================================

    else:

        users = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                users.university,
                users.profile_picture,

                ca.campus
                    AS ambassador_campus,

                ca.school
                    AS ambassador_school,

                ca.active
                    AS ambassador_active,

                ca.appointed_at

            FROM users

            LEFT JOIN campus_ambassadors ca
                ON ca.user_id = users.id

            ORDER BY
                users.name COLLATE NOCASE ASC,
                users.id ASC

            LIMIT 100
            """
        ).fetchall()

    # ========================================================
    # ACTIVE AMBASSADORS
    # ========================================================

    ambassadors = conn.execute(
        """
        SELECT
            ca.id,
            ca.user_id,
            ca.campus,
            ca.school,
            ca.appointed_at,

            users.name,
            users.email,
            users.university,
            users.profile_picture

        FROM campus_ambassadors ca

        JOIN users
            ON users.id = ca.user_id

        WHERE
            ca.active = 1

        ORDER BY
            ca.appointed_at DESC,
            ca.id DESC
        """
    ).fetchall()

    active_count = len(ambassadors)

    conn.close()

    # ========================================================
    # RENDER ADMIN PAGE
    # ========================================================

    return render_template(
        "admin_campus_ambassadors.html",

        current_user=current_user,

        users=users,

        ambassadors=ambassadors,

        active_count=active_count,

        search=search
    )



# ============================================================
# ADMIN — APPOINT CAMPUS AMBASSADOR
# ============================================================


@app.route(
    "/admin/campus-ambassadors/<int:user_id>/appoint",
    methods=["POST"]
)
def admin_appoint_campus_ambassador(user_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # ========================================================
    # GET CAMPUS / SCHOOL
    # ========================================================

    campus = clean_text(
        request.form.get("campus"),
        MAX_UNIVERSITY_LENGTH
    )

    school = clean_text(
        request.form.get("school"),
        MAX_UNIVERSITY_LENGTH
    )

    if not campus or not school:

        conn.close()

        return (
            "Campus and school are required.",
            400
        )

    # ========================================================
    # FIND USER
    # ========================================================

    user = conn.execute(
        """
        SELECT
            id,
            name
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:

        conn.close()

        return (
            "Student not found.",
            404
        )

    # ========================================================
    # CHECK EXISTING AMBASSADOR RECORD
    # ========================================================

    existing = conn.execute(
        """
        SELECT
            id
        FROM campus_ambassadors
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()

    # ========================================================
    # REACTIVATE / UPDATE EXISTING AMBASSADOR
    # ========================================================

    if existing:

        conn.execute(
            """
            UPDATE campus_ambassadors

            SET
                campus = ?,
                school = ?,
                appointed_at = CURRENT_TIMESTAMP,
                appointed_by = ?,
                active = 1,
                removed_at = NULL

            WHERE
                user_id = ?
            """,
            (
                campus,
                school,
                current_user["id"],
                user_id
            )
        )

    # ========================================================
    # CREATE NEW AMBASSADOR
    # ========================================================

    else:

        conn.execute(
            """
            INSERT INTO campus_ambassadors
            (
                user_id,
                campus,
                school,
                appointed_by,
                active
            )

            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                1
            )
            """,
            (
                user_id,
                campus,
                school,
                current_user["id"]
            )
        )

    # ========================================================
    # CAMPUS AMBASSADOR NOTIFICATION
    # ========================================================

    conn.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            sender_id,
            type,
            message,
            link
        )

        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        (
            user_id,
            current_user["id"],
            "campus_ambassador",
            "You have been appointed as an Official UniCamplink Campus Ambassador 🎓",
            "/profile"
        )
    )

    conn.commit()

    conn.close()

    return redirect(
        url_for(
            "admin_campus_ambassadors"
        )
    )



# ============================================================
# ADMIN — REMOVE CAMPUS AMBASSADOR
# ============================================================


@app.route(
    "/admin/campus-ambassadors/<int:user_id>/remove",
    methods=["POST"]
)
def admin_remove_campus_ambassador(user_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # ========================================================
    # FIND ACTIVE AMBASSADOR
    # ========================================================

    ambassador = conn.execute(
        """
        SELECT
            id
        FROM campus_ambassadors
        WHERE
            user_id = ?
            AND active = 1
        """,
        (user_id,)
    ).fetchone()

    if not ambassador:

        conn.close()

        return (
            "Active Campus Ambassador not found.",
            404
        )

    # ========================================================
    # REMOVE AMBASSADOR
    # ========================================================

    conn.execute(
        """
        UPDATE campus_ambassadors

        SET
            active = 0,
            removed_at = CURRENT_TIMESTAMP

        WHERE
            user_id = ?
        """,
        (user_id,)
    )

    # ========================================================
    # REMOVAL NOTIFICATION
    # ========================================================

    conn.execute(
        """
        INSERT INTO notifications
        (
            user_id,
            sender_id,
            type,
            message,
            link
        )

        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,
        (
            user_id,
            current_user["id"],
            "campus_ambassador",
            "Your Official UniCamplink Campus Ambassador status has been removed.",
            "/profile"
        )
    )

    conn.commit()

    conn.close()

    return redirect(
        url_for(
            "admin_campus_ambassadors"
        )
    )

# ============================================================
# ADVERTISE WITH US
# ============================================================

@app.route(
    "/advertise-with-us",
    methods=["GET", "POST"]
)
def advertise_with_us():

    # ------------------------------------------------------------
    # LOGIN REQUIRED
    # ------------------------------------------------------------
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        # --------------------------------------------------------
        # GET FORM DATA
        # --------------------------------------------------------

        # New Razor form field
        advertiser_name = clean_text(
            request.form.get("advertiser_name"),
            MAX_NAME_LENGTH
        )

        # Legacy compatibility field
        name = clean_text(
            request.form.get("name"),
            MAX_NAME_LENGTH
        )

        # If the new field is present, use it.
        # Otherwise fall back to the old "name" field.
        if not advertiser_name:
            advertiser_name = name

        if not name:
            name = advertiser_name

        email = (
            request.form.get("email", "")
            .strip()
            .lower()
        )

        business_name = clean_text(
            request.form.get("business_name"),
            MAX_NAME_LENGTH
        )

        advertising_type = clean_text(
            request.form.get("advertising_type"),
            MAX_NAME_LENGTH
        )

        message = clean_text(
            request.form.get("message"),
            MAX_MESSAGE_LENGTH
        )

        # --------------------------------------------------------
        # DATABASE REQUIRED FIELDS
        #
        # advertisement_requests requires:
        #
        # advertiser_name
        # business_name
        # email
        # category
        # subject
        # message
        #
        # We map the existing Razor form to those fields.
        # --------------------------------------------------------

        category = advertising_type

        subject = business_name

        # --------------------------------------------------------
        # VALIDATION
        # --------------------------------------------------------

        if (
            not advertiser_name
            or not business_name
            or not advertising_type
            or not message
        ):
            return render_template(
                "advertise_with_us.html",
                error="Please fill in all required fields.",
                form_data=request.form
            ), 400

        if not valid_email(email):
            return render_template(
                "advertise_with_us.html",
                error="Please enter a valid email address.",
                form_data=request.form
            ), 400

        # --------------------------------------------------------
        # SAVE ADVERTISEMENT REQUEST
        # --------------------------------------------------------

        conn = get_db_connection()

        try:

            cursor = conn.execute(
                """
                INSERT INTO advertisement_requests
                (
                    user_id,
                    advertiser_name,
                    business_name,
                    email,
                    category,
                    subject,
                    message,
                    status,
                    name,
                    advertising_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    session["user_id"],
                    advertiser_name,
                    business_name,
                    email,
                    category,
                    subject,
                    message,
                    name,
                    advertising_type
                )
            )

            request_id = cursor.lastrowid

            conn.commit()

            app.logger.info(
                "UniCamplink advertisement request saved successfully. "
                "request_id=%s user_id=%s",
                request_id,
                session["user_id"]
            )

        except Exception:

            conn.rollback()

            app.logger.exception(
                "UniCamplink advertisement request save failed."
            )

            conn.close()

            return render_template(
                "advertise_with_us.html",
                error=(
                    "We could not save your advertising request "
                    "right now. Please try again."
                ),
                form_data=request.form
            ), 500

        conn.close()

        # --------------------------------------------------------
        # SUCCESS
        # --------------------------------------------------------

        return render_template(
            "advertise_with_us.html",
            success=(
                "Your advertising request has been submitted "
                "successfully. Our team will review it and contact "
                "you shortly."
            ),
            form_data={}
        )

    # ------------------------------------------------------------
    # GET REQUEST
    # ------------------------------------------------------------

    return render_template(
        "advertise_with_us.html",
        form_data={}
    )

# ============================================================
# ADMIN — REPORTS
# ============================================================

@app.route("/admin/reports")
def admin_reports():

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # --------------------------------------------------------
    # BLOCKED USERS COUNT
    # --------------------------------------------------------

    blocked_users = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE is_blocked = 1
        """
    ).fetchone()[0]

    # --------------------------------------------------------
    # REPORTS
    # --------------------------------------------------------

    reports = conn.execute(
        """
        SELECT
            reports.id,
            reports.reporter_id,
            reports.reported_user_id,
            reports.target_type,
            reports.target_id,
            reports.reason,
            reports.details,
            reports.status,
            reports.reviewed_by,
            reports.reviewed_at,
            reports.resolution_note,
            reports.created_at,
            reports.updated_at,

            reporter.name AS reporter_name,
            reporter.email AS reporter_email,
            reporter.profile_picture AS reporter_picture,

            reported_user.name AS reported_name,
            reported_user.email AS reported_email,
            reported_user.profile_picture AS reported_picture,
            reported_user.is_blocked AS reported_user_blocked,

            reviewer.name AS reviewer_name

        FROM reports

        LEFT JOIN users AS reporter
            ON reporter.id = reports.reporter_id

        LEFT JOIN users AS reported_user
            ON reported_user.id = reports.reported_user_id

        LEFT JOIN users AS reviewer
            ON reviewer.id = reports.reviewed_by

        ORDER BY
            CASE
                WHEN reports.status = 'pending'
                THEN 0
                ELSE 1
            END,

            reports.created_at DESC,
            reports.id DESC
        """
    ).fetchall()

    # --------------------------------------------------------
    # REPORT COUNTS
    # --------------------------------------------------------

    total_reports = conn.execute(
        """
        SELECT COUNT(*)
        FROM reports
        """
    ).fetchone()[0]

    pending_reports = conn.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'pending'
        """
    ).fetchone()[0]

    resolved_reports = conn.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'resolved'
        """
    ).fetchone()[0]

    dismissed_reports = conn.execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status = 'dismissed'
        """
    ).fetchone()[0]

    conn.close()

    return render_template(
        "admin_reports.html",
        current_user=current_user,
        reports=reports,
        total_reports=total_reports,
        pending_reports=pending_reports,
        resolved_reports=resolved_reports,
        dismissed_reports=dismissed_reports,
        blocked_users=blocked_users
    )
@app.route(
    "/admin/reports/<int:report_id>/resolve",
    methods=["POST"]
)
def admin_resolve_report(report_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    resolution_note = clean_text(
        request.form.get("resolution_note"),
        1000
    )

    report = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE id = ?
        """,
        (report_id,)
    ).fetchone()

    if not report:
        conn.close()
        return "Report not found.", 404

    conn.execute(
        """
        UPDATE reports
        SET
            status = 'resolved',
            reviewed_by = ?,
            reviewed_at = CURRENT_TIMESTAMP,
            resolution_note = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            current_user["id"],
            resolution_note or "",
            report_id
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_reports")
    )


@app.route(
    "/admin/reports/<int:report_id>/dismiss",
    methods=["POST"]
)
def admin_dismiss_report(report_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    resolution_note = clean_text(
        request.form.get("resolution_note"),
        1000
    )

    report = conn.execute(
        """
        SELECT id
        FROM reports
        WHERE id = ?
        """,
        (report_id,)
    ).fetchone()

    if not report:
        conn.close()
        return "Report not found.", 404

    conn.execute(
        """
        UPDATE reports
        SET
            status = 'dismissed',
            reviewed_by = ?,
            reviewed_at = CURRENT_TIMESTAMP,
            resolution_note = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            current_user["id"],
            resolution_note or "",
            report_id
        )
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_reports")
    )
@app.route(
    "/admin/users/<int:user_id>/block",
    methods=["POST"]
)
def admin_block_user(user_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # Prevent admin from blocking themselves
    if user_id == current_user["id"]:
        conn.close()
        return "You cannot block your own admin account.", 400

    user = conn.execute(
        """
        SELECT id, name, email, is_blocked
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        return "User not found.", 404

    if user["is_blocked"]:
        conn.close()
        return redirect(url_for("admin_reports"))

    reason = clean_text(
        request.form.get("reason"),
        1000
    )

    conn.execute(
        """
        UPDATE users
        SET is_blocked = 1
        WHERE id = ?
        """,
        (user_id,)
    )

    conn.execute(
        """
        INSERT INTO moderation_logs
        (
            admin_id,
            target_user_id,
            action,
            reason
        )
        VALUES (?, ?, 'blocked', ?)
        """,
        (
            current_user["id"],
            user_id,
            reason or "Blocked through admin moderation."
        )
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin_reports"))
@app.route(
    "/admin/users/<int:user_id>/unblock",
    methods=["POST"]
)
def admin_unblock_user(user_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    user = conn.execute(
        """
        SELECT id, name, email, is_blocked
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        return "User not found.", 404

    if not user["is_blocked"]:
        conn.close()
        return redirect(url_for("admin_reports"))

    reason = clean_text(
        request.form.get("reason"),
        1000
    )

    conn.execute(
        """
        UPDATE users
        SET is_blocked = 0
        WHERE id = ?
        """,
        (user_id,)
    )

    conn.execute(
        """
        INSERT INTO moderation_logs
        (
            admin_id,
            target_user_id,
            action,
            reason
        )
        VALUES (?, ?, 'unblocked', ?)
        """,
        (
            current_user["id"],
            user_id,
            reason or "User unblocked through admin moderation."
        )
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin_reports"))
# ============================================================
# ADMIN — ADVERTISEMENT REQUESTS
# ============================================================

@app.route("/admin/advertisements")
def admin_advertisements():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return "Admin access is not configured yet.", 500

    conn = get_db_connection()

    current_user = conn.execute(
        """
        SELECT
            id,
            name,
            email
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if (
        not current_user
        or current_user["email"].lower() != ADMIN_EMAIL
    ):
        conn.close()
        return "Access denied.", 403

    advertisements = conn.execute(
        """
        SELECT
            id,
            user_id,

            name AS advertiser_name,

            business_name,

            email,

            advertising_type AS category,

            advertising_type AS subject,

            message,

            status,

            created_at

        FROM advertisement_requests

        ORDER BY
            created_at DESC,
            id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "admin_advertisements.html",
        current_user=current_user,
        advertisements=advertisements
    )


# ============================================================
# ADMIN — APPROVE ADVERTISEMENT
# ============================================================

@app.route(
    "/admin/advertisements/<int:advertisement_id>/approve",
    methods=["POST"]
)
def admin_approve_advertisement(advertisement_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    advertisement = conn.execute(
        """
        SELECT
            id,
            user_id,
            business_name,
            message,
            status
        FROM advertisement_requests
        WHERE id = ?
        """,
        (advertisement_id,)
    ).fetchone()

    if not advertisement:
        conn.close()
        return "Advertisement request not found.", 404

    # --------------------------------------------------------
    # PREVENT DUPLICATE SPONSORED POSTS
    # --------------------------------------------------------

    existing = conn.execute(
        """
        SELECT id
        FROM sponsored_posts
        WHERE advertisement_request_id = ?
        """,
        (advertisement_id,)
    ).fetchone()

    # --------------------------------------------------------
    # APPROVE REQUEST
    # --------------------------------------------------------

    conn.execute(
        """
        UPDATE advertisement_requests
        SET status = 'approved'
        WHERE id = ?
        """,
        (advertisement_id,)
    )

    # --------------------------------------------------------
    # CREATE SPONSORED POST DRAFT
    # --------------------------------------------------------

    if not existing:

        conn.execute(
            """
            INSERT INTO sponsored_posts
            (
                advertisement_request_id,
                advertiser_user_id,
                business_name,
                content,
                status
            )
            VALUES (?, ?, ?, ?, 'draft')
            """,
            (
                advertisement["id"],
                advertisement["user_id"],
                advertisement["business_name"],
                advertisement["message"]
            )
        )

    # --------------------------------------------------------
    # NOTIFY ADVERTISER
    # --------------------------------------------------------

    if advertisement["user_id"]:

        conn.execute(
            """
            INSERT INTO notifications
            (
                user_id,
                sender_id,
                type,
                message,
                link
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                advertisement["user_id"],
                current_user["id"],
                "advertisement",
                "Your UniCamplink advertising request has been approved. 📢",
                "/admin/advertisements"
            )
        )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_advertisements")
    )
# ============================================================
# ADMIN — SPONSORED POSTS
# ============================================================

@app.route("/admin/sponsored-posts")
def admin_sponsored_posts():

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    # --------------------------------------------------------
    # EXISTING ADVERTISER-BASED SPONSORED POSTS
    # --------------------------------------------------------
    sponsored_posts = conn.execute(
        """
        SELECT
            sp.*,
            ar.email AS advertiser_email,
            ar.advertising_type
        FROM sponsored_posts sp

        LEFT JOIN advertisement_requests ar
            ON ar.id = sp.advertisement_request_id

        ORDER BY
            sp.created_at DESC,
            sp.id DESC
        """
    ).fetchall()

    # --------------------------------------------------------
    # NORMAL FEED POSTS
    # These can be marked/unmarked as Sponsored by admin.
    # --------------------------------------------------------
    normal_posts = conn.execute(
        """
        SELECT
            posts.id,
            posts.user_id,
            posts.content,
            posts.image,
            posts.created_at,
            posts.is_sponsored,
            posts.sponsored_at,

            users.name AS author_name,
            users.university AS author_university,
            users.profile_picture,

            (
                SELECT COUNT(*)
                FROM likes
                WHERE likes.post_id = posts.id
            ) AS like_count,

            (
                SELECT COUNT(*)
                FROM comments
                WHERE comments.post_id = posts.id
            ) AS comment_count

        FROM posts

        JOIN users
            ON posts.user_id = users.id

        ORDER BY
            posts.created_at DESC,
            posts.id DESC
        """
    ).fetchall()

    conn.close()

    return render_template(
        "admin_sponsored_posts.html",
        current_user=current_user,
        sponsored_posts=sponsored_posts,
        normal_posts=normal_posts
    )
# ============================================================
# ADMIN — ACTIVATE SPONSORED POST
# ============================================================

@app.route(
    "/admin/sponsored-posts/<int:sponsored_post_id>/activate",
    methods=["POST"]
)
def admin_activate_sponsored_post(sponsored_post_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    sponsored_post = conn.execute(
        """
        SELECT
            id,
            advertisement_request_id,
            status
        FROM sponsored_posts
        WHERE id = ?
        """,
        (sponsored_post_id,)
    ).fetchone()

    if not sponsored_post:
        conn.close()
        return "Sponsored post not found.", 404

    conn.execute(
        """
        UPDATE sponsored_posts
        SET
            status = 'active',
            starts_at = COALESCE(
                starts_at,
                CURRENT_TIMESTAMP
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (sponsored_post_id,)
    )

    # Keep the original advertising request synchronized.
    if sponsored_post["advertisement_request_id"]:

        conn.execute(
            """
            UPDATE advertisement_requests
            SET status = 'active'
            WHERE id = ?
            """,
            (
                sponsored_post["advertisement_request_id"],
            )
        )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_sponsored_posts")
    )
# ============================================================
# ADMIN — PAUSE SPONSORED POST
# ============================================================

@app.route(
    "/admin/sponsored-posts/<int:sponsored_post_id>/pause",
    methods=["POST"]
)
def admin_pause_sponsored_post(sponsored_post_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    sponsored_post = conn.execute(
        """
        SELECT
            id,
            advertisement_request_id
        FROM sponsored_posts
        WHERE id = ?
        """,
        (sponsored_post_id,)
    ).fetchone()

    if not sponsored_post:
        conn.close()
        return "Sponsored post not found.", 404

    conn.execute(
        """
        UPDATE sponsored_posts
        SET
            status = 'paused',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (sponsored_post_id,)
    )

    if sponsored_post["advertisement_request_id"]:

        conn.execute(
            """
            UPDATE advertisement_requests
            SET status = 'paused'
            WHERE id = ?
            """,
            (
                sponsored_post["advertisement_request_id"],
            )
        )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_sponsored_posts")
    )


# ============================================================
# ADMIN — MARK NORMAL POST AS SPONSORED
# ============================================================

@app.route(
    "/admin/posts/<int:post_id>/mark-sponsored",
    methods=["POST"]
)
def admin_mark_post_sponsored(post_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    post = conn.execute(
        """
        SELECT id
        FROM posts
        WHERE id = ?
        """,
        (post_id,)
    ).fetchone()

    if not post:
        conn.close()
        return redirect(url_for("admin_sponsored_posts"))

    conn.execute(
        """
        UPDATE posts
        SET
            is_sponsored = 1,
            sponsored_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (post_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin_sponsored_posts"))


# ============================================================
# ADMIN — REMOVE SPONSORED FROM NORMAL POST
# ============================================================

@app.route(
    "/admin/posts/<int:post_id>/remove-sponsored",
    methods=["POST"]
)
def admin_remove_post_sponsored(post_id):

    current_user, result = _require_admin()

    if current_user is None:
        return result

    conn = result

    conn.execute(
        """
        UPDATE posts
        SET
            is_sponsored = 0,
            sponsored_at = NULL
        WHERE id = ?
        """,
        (post_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin_sponsored_posts"))

# ============================================================
# ADMIN — REJECT ADVERTISEMENT
# ============================================================

@app.route(
    "/admin/advertisements/<int:advertisement_id>/reject",
    methods=["POST"]
)
def admin_reject_advertisement(advertisement_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return "Admin access is not configured yet.", 500

    conn = get_db_connection()

    current_user = conn.execute(
        """
        SELECT
            id,
            name,
            email
        FROM users
        WHERE id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if (
        not current_user
        or current_user["email"].lower() != ADMIN_EMAIL
    ):
        conn.close()
        return "Access denied.", 403

    advertisement = conn.execute(
        """
        SELECT id
        FROM advertisement_requests
        WHERE id = ?
        """,
        (advertisement_id,)
    ).fetchone()

    if not advertisement:
        conn.close()
        return "Advertisement request not found.", 404

    conn.execute(
        """
        UPDATE advertisement_requests
        SET status = 'rejected'
        WHERE id = ?
        """,
        (advertisement_id,)
    )

    conn.commit()
    conn.close()

    return redirect(
        url_for("admin_advertisements")
    )



# ============================================================
# INTERNAL FRIEND SUGGESTION PUSH JOB
# ============================================================

def get_people_you_may_know_for_user(current_user_id, university):
    conn = get_db_connection()

    try:
        return conn.execute(
            """
            SELECT
                candidate.id,
                candidate.name,
                candidate.university,
                candidate.bio,
                candidate.profile_picture,

                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM campus_ambassadors ca
                        WHERE ca.user_id = candidate.id
                        AND ca.active = 1
                    )
                    THEN 1
                    ELSE 0
                END AS is_campus_ambassador,

                (
                    SELECT COUNT(*)
                    FROM friends fc
                    WHERE fc.user_id = candidate.id
                ) AS friend_count,

                (
                    SELECT COUNT(*)
                    FROM friends myf
                    WHERE myf.user_id = ?
                    AND EXISTS (
                        SELECT 1
                        FROM friends cf
                        WHERE cf.user_id = candidate.id
                        AND cf.friend_id = myf.friend_id
                    )
                ) AS mutual_friend_count,

                CASE
                    WHEN LOWER(COALESCE(candidate.university, ''))
                         = LOWER(COALESCE(?, ''))
                    THEN 1
                    ELSE 0
                END AS same_university

            FROM users candidate

            WHERE candidate.id != ?

            AND NOT EXISTS (
                SELECT 1
                FROM friends existing_friendship
                WHERE
                    (
                        existing_friendship.user_id = ?
                        AND existing_friendship.friend_id = candidate.id
                    )
                    OR
                    (
                        existing_friendship.user_id = candidate.id
                        AND existing_friendship.friend_id = ?
                    )
            )

            AND NOT EXISTS (
                SELECT 1
                FROM friend_requests existing_request
                WHERE
                    existing_request.status = 'pending'
                    AND (
                        (
                            existing_request.sender_id = ?
                            AND existing_request.receiver_id = candidate.id
                        )
                        OR
                        (
                            existing_request.sender_id = candidate.id
                            AND existing_request.receiver_id = ?
                        )
                    )
            )

            ORDER BY
                same_university DESC,
                mutual_friend_count DESC,
                is_campus_ambassador DESC,
                friend_count DESC,
                candidate.joined_at DESC,
                candidate.id DESC

            LIMIT 6
            """,
            (
                current_user_id,
                university,
                current_user_id,
                current_user_id,
                current_user_id,
                current_user_id,
                current_user_id,
            )
        ).fetchall()

    finally:
        conn.close()


def process_friend_suggestion_pushes():
    conn = get_db_connection()

    try:
        users = conn.execute(
            """
            SELECT
                u.id,
                u.name,
                u.university
            FROM users u
            WHERE EXISTS (
                SELECT 1
                FROM push_subscriptions ps
                WHERE ps.user_id = u.id
            )
            ORDER BY u.id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    processed_users = 0
    sent_notifications = 0

    for user in users:
        suggestions = get_people_you_may_know_for_user(
            user["id"],
            user["university"]
        )

        for person in suggestions:
            conn = get_db_connection()

            try:
                already_notified = conn.execute(
                    """
                    SELECT 1
                    FROM notifications
                    WHERE user_id = ?
                    AND sender_id = ?
                    AND type = 'friend_suggestion'
                    LIMIT 1
                    """,
                    (
                        user["id"],
                        person["id"],
                    )
                ).fetchone()
            finally:
                conn.close()

            if already_notified:
                continue

            message = (
                f"You may know {person['name']} on UniCamplink."
            )

            sent_count = send_push_notification(
                user["id"],
                "People You May Know",
                message,
                link="/dashboard",
                tag="unicamplink-friend-suggestion"
            )

            if sent_count <= 0:
                continue

            conn = get_db_connection()

            try:
                conn.execute(
                    """
                    INSERT INTO notifications (
                        user_id,
                        sender_id,
                        type,
                        message,
                        link,
                        is_read
                    )
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (
                        user["id"],
                        person["id"],
                        "friend_suggestion",
                        message,
                        "/dashboard",
                    )
                )

                conn.commit()
                sent_notifications += 1

            finally:
                conn.close()

        processed_users += 1

    return {
        "processed_users": processed_users,
        "sent_notifications": sent_notifications,
    }


@app.route(
    "/api/internal/friend-suggestions/run",
    methods=["POST"]
)
@csrf.exempt
def run_friend_suggestion_job():

    configured_secret = os.environ.get(
        "FRIEND_SUGGESTION_CRON_SECRET",
        ""
    )

    supplied_secret = request.headers.get(
        "X-UniCamplink-Cron-Secret",
        ""
    )

    if (
        not configured_secret
        or not supplied_secret
        or not hmac.compare_digest(
            supplied_secret,
            configured_secret
        )
    ):
        return {
            "success": False,
            "error": "Unauthorized."
        }, 401

    try:
        result = process_friend_suggestion_pushes()

        return {
            "success": True,
            **result
        }, 200

    except Exception:
        app.logger.exception(
            "Friend suggestion push job failed."
        )

        return {
            "success": False,
            "error": "Friend suggestion job failed."
        }, 500


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
