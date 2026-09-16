import os
import sqlite3
import math
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


# ============================================================
# INITIALIZE DATABASE
# ============================================================

create_tables()
update_users_table()
update_posts_table()
update_comments_table()
update_advertisement_requests_table()
update_campus_ambassadors_table()
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

        if len(email) > MAX_EMAIL_LENGTH:

            return (
                "Invalid email or password."
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

                        return (
                            "Too many failed login attempts. "
                            f"Please try again in "
                            f"{remaining_minutes} minute(s)."
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

            return (
                "Too many failed login attempts. "
                "Please try again in 10 minutes."
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

        return (
            "Invalid email or password."
        )

    return render_template(
        "login.html"
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

    conn.close()

    if not user:

        session.clear()

        return redirect(
            url_for("login")
        )

    return render_template(
        "dashboard.html",
        user=user
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
            return jsonify({"success": False, "error": message}), 400
        return message, 400

    if content is None:
        message = "Post text is too long. Maximum length is 5000 characters."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": message}), 400
        return message, 400

    image_filename = ""

    if image and image.filename:
        if not validate_image(image):
            message = (
                "Invalid image. Please upload a genuine PNG, JPG, JPEG "
                "or GIF image under 4096x4096 pixels."
            )
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": message}), 400
            return message, 400

        extension = image.filename.rsplit(".", 1)[1].lower()
        image_filename = "post_" + str(uuid4()) + "." + extension

        try:
            image.save(safe_upload_path(image_filename))
        except OSError:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "success": False,
                    "error": "The image could not be saved. Please try again."
                }), 500
            return "The image could not be saved. Please try again.", 500

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
        SELECT id, name, university, profile_picture
        FROM users
        WHERE id = ?
        """,
        (current_user_id,)
    ).fetchone()

    author_name = author["name"] if author else "A student"

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
        "author_name": author["name"] if author else "UniCamplink User",
        "author_university": author["university"] if author else "",
        "profile_picture": author["profile_picture"] if author else "",
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

    return redirect(url_for("feed"))


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
                    "/feed"
                )
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
                "/feed"
            )
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
                    "/feed"
                )
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
            u.name,
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
            u.name,
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
        SELECT *
        FROM posts
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (
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
        campus_ambassador=campus_ambassador
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

    conn.execute(
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

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    search = clean_text(
        request.args.get("search"),
        MAX_SEARCH_LENGTH
    )

    category = clean_text(
        request.args.get("category"),
        MAX_NAME_LENGTH
    )

    if search is None:

        return (
            "Marketplace search query is too long."
        ), 400

    if category is None:

        return (
            "Invalid marketplace category."
        ), 400

    if (
        category
        and
        category not in MARKETPLACE_CATEGORIES
    ):

        category = ""

    conn = get_db_connection()

    sql = """
        SELECT
            products.*,
            users.name AS seller_name,
            users.university AS seller_university

        FROM products

        JOIN users
        ON products.seller_id = users.id

        WHERE products.status = 'available'
    """

    parameters = []

    if search:

        sql += """
            AND (
                products.name LIKE ?
                OR products.description LIKE ?
            )
        """

        parameters.extend([
            "%" + search + "%",
            "%" + search + "%"
        ])

    if category:

        sql += """
            AND products.category = ?
        """

        parameters.append(category)

    sql += """
        ORDER BY products.created_at DESC
    """

    products = conn.execute(
        sql,
        parameters
    ).fetchall()

    conn.close()

    return render_template(
        "marketplace.html",
        products=products,
        categories=MARKETPLACE_CATEGORIES,
        query=search or "",
        selected_category=category
    )


# ============================================================
# ADD PRODUCT
# ============================================================

@app.route(
    "/marketplace/add",
    methods=["GET", "POST"]
)
def add_product():

    if "user_id" not in session:

        return redirect(
            url_for("login")
        )

    if request.method == "POST":

        name = clean_text(
            request.form.get("name"),
            MAX_PRODUCT_NAME_LENGTH
        )

        description = clean_text(
            request.form.get("description"),
            MAX_PRODUCT_DESCRIPTION_LENGTH
        )

        price_text = request.form.get(
            "price",
            ""
        ).strip()

        category = clean_text(
            request.form.get("category"),
            MAX_NAME_LENGTH
        )

        location = clean_text(
            request.form.get("location"),
            MAX_LOCATION_LENGTH
        )

        image = request.files.get(
            "image"
        )

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

        # ----------------------------------------------------
        # SAFE PRICE VALIDATION
        # ----------------------------------------------------

        try:

            price = float(price_text)

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

        except (ValueError, OverflowError):

            return (
                "Please enter a valid price."
            ), 400

        image_filename = ""

        if image and image.filename:

            if not validate_image(image):

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

            image_filename = (
                "product_"
                + str(uuid4())
                + "."
                + extension
            )

            image.save(
                safe_upload_path(image_filename)
            )

        conn = get_db_connection()

        conn.execute(
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

        conn.commit()
        conn.close()

        return redirect(
            url_for("marketplace")
        )

    return render_template(
        "add_product.html"
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

    conn.close()

    return render_template(
        "messages.html",
        conversations=conversations
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
    # CHAT AUTHORIZATION
    # --------------------------------------------------------

    if not (
        is_friend
        or is_marketplace_contact
        or has_existing_conversation
    ):

        conn.close()

        return (
            "You can only message students who are "
            "your friends or contact a seller through "
            "a marketplace product."
        ), 403

    # --------------------------------------------------------
    # SEND MESSAGE
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

        conn.commit()
        conn.close()

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

    total_posts = conn.execute(
        "SELECT COUNT(*) FROM posts"
    ).fetchone()[0]

    total_groups = conn.execute(
        "SELECT COUNT(*) FROM groups"
    ).fetchone()[0]

    total_products = conn.execute(
        "SELECT COUNT(*) FROM products"
    ).fetchone()[0]

    total_messages = conn.execute(
        "SELECT COUNT(*) FROM messages"
    ).fetchone()[0]

    total_friend_requests = conn.execute(
        "SELECT COUNT(*) FROM friend_requests"
    ).fetchone()[0]

    total_advertisements = conn.execute(
        "SELECT COUNT(*) FROM advertisement_requests"
    ).fetchone()[0]

    pending_advertisements = conn.execute(
        """
        SELECT COUNT(*)
        FROM advertisement_requests
        WHERE status = 'pending'
        """
    ).fetchone()[0]

    total_ambassadors = conn.execute(
        """
        SELECT COUNT(*)
        FROM campus_ambassadors
        WHERE active = 1
        """
    ).fetchone()[0]

    recent_users = conn.execute(
        """
        SELECT id, name, email, university, joined_at, last_seen
        FROM users
        ORDER BY COALESCE(
            joined_at,
            '9999-12-31 23:59:59'
        ) DESC, id DESC
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
        recent_users=recent_users
    )

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
        "SELECT id, name, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["email"].lower() != ADMIN_EMAIL:
        conn.close()
        return "Access denied.", 403

    advertisements = conn.execute(
    """
    SELECT
        id,
        user_id,
        advertiser_name,
        business_name,
        email,
        category,
        subject,
        message,
        status,
        created_at
    FROM advertisement_requests
    ORDER BY created_at DESC, id DESC
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

@app.route("/admin/advertisements/<int:advertisement_id>/approve", methods=["POST"])
def admin_approve_advertisement(advertisement_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return "Admin access is not configured yet.", 500

    conn = get_db_connection()

    current_user = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["email"].lower() != ADMIN_EMAIL:
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
        SET status = 'approved'
        WHERE id = ?
        """,
        (advertisement_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin_advertisements"))


# ============================================================
# ADMIN — REJECT ADVERTISEMENT
# ============================================================

@app.route("/admin/advertisements/<int:advertisement_id>/reject", methods=["POST"])
def admin_reject_advertisement(advertisement_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not ADMIN_EMAIL:
        return "Admin access is not configured yet.", 500

    conn = get_db_connection()

    current_user = conn.execute(
        "SELECT id, name, email FROM users WHERE id = ?",
        (session["user_id"],)
    ).fetchone()

    if not current_user or current_user["email"].lower() != ADMIN_EMAIL:
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

    return redirect(url_for("admin_advertisements"))
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


@app.route("/admin/campus-ambassadors")
def admin_campus_ambassadors():
    current_user, result = _require_admin()
    if current_user is None:
        return result

    conn = result
    search = clean_text(
        request.args.get("q"),
        MAX_SEARCH_LENGTH
    )

    if search is None:
        conn.close()
        return (
            "Search query is too long. Maximum length is 100 characters."
        ), 400

    pattern = f"%{search}%" if search else None

    if pattern:
        users = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                users.university,
                users.profile_picture,
                ca.campus AS ambassador_campus,
                ca.school AS ambassador_school,
                ca.active AS ambassador_active,
                ca.appointed_at
            FROM users
            LEFT JOIN campus_ambassadors ca
                ON ca.user_id = users.id
            WHERE
                LOWER(users.name) LIKE LOWER(?)
                OR LOWER(users.email) LIKE LOWER(?)
                OR LOWER(COALESCE(users.university, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(ca.campus, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(ca.school, '')) LIKE LOWER(?)
            ORDER BY users.name COLLATE NOCASE ASC, users.id ASC
            LIMIT 100
            """,
            (pattern, pattern, pattern, pattern, pattern)
        ).fetchall()
    else:
        users = conn.execute(
            """
            SELECT
                users.id,
                users.name,
                users.email,
                users.university,
                users.profile_picture,
                ca.campus AS ambassador_campus,
                ca.school AS ambassador_school,
                ca.active AS ambassador_active,
                ca.appointed_at
            FROM users
            LEFT JOIN campus_ambassadors ca
                ON ca.user_id = users.id
            ORDER BY users.name COLLATE NOCASE ASC, users.id ASC
            LIMIT 100
            """
        ).fetchall()

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
        JOIN users ON users.id = ca.user_id
        WHERE ca.active = 1
        ORDER BY ca.appointed_at DESC, ca.id DESC
        """
    ).fetchall()

    active_count = len(ambassadors)
    conn.close()

    return render_template(
        "admin_campus_ambassadors.html",
        current_user=current_user,
        users=users,
        ambassadors=ambassadors,
        active_count=active_count,
        search=search
    )


@app.route("/admin/campus-ambassadors/<int:user_id>/appoint", methods=["POST"])
def admin_appoint_campus_ambassador(user_id):
    current_user, result = _require_admin()
    if current_user is None:
        return result

    conn = result

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
        return "Campus and school are required.", 400

    user = conn.execute(
        "SELECT id, name FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        return "Student not found.", 404

    existing = conn.execute(
        "SELECT id FROM campus_ambassadors WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE campus_ambassadors
            SET campus = ?,
                school = ?,
                appointed_at = CURRENT_TIMESTAMP,
                appointed_by = ?,
                active = 1,
                removed_at = NULL
            WHERE user_id = ?
            """,
            (campus, school, current_user["id"], user_id)
        )
    else:
        conn.execute(
            """
            INSERT INTO campus_ambassadors
            (user_id, campus, school, appointed_by, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (user_id, campus, school, current_user["id"])
        )

    conn.execute(
        """
        INSERT INTO notifications
        (user_id, sender_id, type, message, link)
        VALUES (?, ?, ?, ?, ?)
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

    return redirect(url_for("admin_campus_ambassadors"))


@app.route("/admin/campus-ambassadors/<int:user_id>/remove", methods=["POST"])
def admin_remove_campus_ambassador(user_id):
    current_user, result = _require_admin()
    if current_user is None:
        return result

    conn = result

    ambassador = conn.execute(
        """
        SELECT id
        FROM campus_ambassadors
        WHERE user_id = ? AND active = 1
        """,
        (user_id,)
    ).fetchone()

    if not ambassador:
        conn.close()
        return "Active Campus Ambassador not found.", 404

    conn.execute(
        """
        UPDATE campus_ambassadors
        SET active = 0,
            removed_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        (user_id,)
    )

    conn.commit()
    conn.close()

    return redirect(url_for("admin_campus_ambassadors"))


# ============================================================
# ADVERTISE WITH US
# ============================================================

@app.route(
    "/advertise-with-us",
    methods=["GET", "POST"]
)
def advertise_with_us():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        name = clean_text(
            request.form.get("name"),
            MAX_NAME_LENGTH
        )

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

        if (
            not name
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

        # WhatsApp number for UniCamplink advertising
        whatsapp_number = "2349161162607"

        whatsapp_message = (
            "Hello UniCamplink 👋\n\n"
            "I want to advertise on UniCamplink.\n\n"
            f"Name: {name}\n"
            f"Email: {email}\n"
            f"Business Name: {business_name}\n"
            f"Advertising Type: {advertising_type}\n\n"
            f"Message:\n{message}"
        )

        from urllib.parse import quote

        whatsapp_url = (
            "https://wa.me/"
            + whatsapp_number
            + "?text="
            + quote(whatsapp_message)
        )

        return redirect(whatsapp_url)

    return render_template(
        "advertise_with_us.html"
    )



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