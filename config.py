import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
UPLOAD_DIR = os.path.join(INSTANCE_DIR, "uploads", "content")
LEAVE_DOCS_DIR = os.path.join(INSTANCE_DIR, "uploads", "leave_docs")

os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LEAVE_DOCS_DIR, exist_ok=True)

# Create subdirectories for each content type
for content_type in ['videos', 'pdfs', 'images', 'downloads', 'html']:
    os.makedirs(os.path.join(UPLOAD_DIR, content_type), exist_ok=True)

load_dotenv(os.path.join(BASE_DIR, ".env"))


def _env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


APP_ENV = os.environ.get(
    "APP_ENV",
    "production" if os.environ.get("K_SERVICE") else "development",
).strip().lower()

if APP_ENV not in {"development", "testing", "production"}:
    raise RuntimeError("APP_ENV must be development, testing, or production")

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Add SECRET_KEY=<random hex> to your .env file."
    )

DB_PATH = os.path.join(INSTANCE_DIR, "database.db")

class Config:
    APP_ENV = APP_ENV
    ENV = APP_ENV
    SECRET_KEY = _secret_key
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DB_TYPE = os.environ.get("DB_TYPE", "sqlite")
    MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DB = os.environ.get("MYSQL_DB", "attn_billing_db")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
    MYSQL_UNIX_SOCKET = os.environ.get("MYSQL_UNIX_SOCKET")
    # "cloud-sql-connector" enables the in-process Python connector. The default
    # remains a normal TCP/socket connection (local MySQL or Auth Proxy).
    DB_CONNECTION_MODE = os.environ.get("DB_CONNECTION_MODE", "direct")
    CLOUD_SQL_CONNECTION_NAME = os.environ.get("CLOUD_SQL_CONNECTION_NAME")
    CLOUD_SQL_IAM_PRINCIPAL = os.environ.get(
        "CLOUD_SQL_IAM_PRINCIPAL",
        "644631083795-compute@developer.gserviceaccount.com",
    )
    CLOUD_SQL_ENABLE_IAM_AUTH = _env_bool("CLOUD_SQL_ENABLE_IAM_AUTH", default=False)
    CLOUD_SQL_IP_TYPE = os.environ.get("CLOUD_SQL_IP_TYPE", "PUBLIC").upper()
    STORAGE_PROVIDER = os.environ.get("STORAGE_PROVIDER", "local")
    GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "global-it-erp-storage")




    # Session: sliding expiry — stays alive while active, expires after 7 days idle
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = True

    # Secure cookie flags
    # Keep False for local http://127.0.0.1 development, set True in production HTTPS.
    SESSION_COOKIE_SECURE = _env_bool(
        "SESSION_COOKIE_SECURE", default=APP_ENV == "production"
    )
    SESSION_COOKIE_HTTPONLY = True  # Prevent JS access
    SESSION_COOKIE_SAMESITE = "Lax" # CSRF mitigation
    SESSION_COOKIE_NAME = os.environ.get(
        "SESSION_COOKIE_NAME", "__Host-erp_session" if APP_ENV == "production" else "erp_session"
    )

    # CSRF protection (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None if APP_ENV != "production" else 3600

    # Flask-Limiter
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "")

    # App debug mode
    DEBUG_MODE = _env_bool("DEBUG_MODE", default=False)

    # Only trust forwarding headers when running behind a known reverse proxy.
    PROXY_FIX_X_FOR = int(os.environ.get("PROXY_FIX_X_FOR", "1" if APP_ENV == "production" else "0"))
    PROXY_FIX_X_PROTO = int(os.environ.get("PROXY_FIX_X_PROTO", "1" if APP_ENV == "production" else "0"))
    PROXY_FIX_X_HOST = int(os.environ.get("PROXY_FIX_X_HOST", "1" if APP_ENV == "production" else "0"))

    SECURITY_HEADERS_ENABLED = _env_bool(
        "SECURITY_HEADERS_ENABLED", default=APP_ENV == "production"
    )
    HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "31536000"))
    CONTENT_SECURITY_POLICY = os.environ.get(
        "CONTENT_SECURITY_POLICY",
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'self'; form-action 'self'; "
        "img-src 'self' data: blob: https:; media-src 'self' blob: https:; "
        "font-src 'self' data: https:; style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
        "connect-src 'self' https:",
    )

    # Student Portal session timeout (minutes)
    STUDENT_SESSION_TIMEOUT_MINUTES = int(os.environ.get("STUDENT_SESSION_TIMEOUT_MINUTES", "120"))
    STUDENT_MOBILE_SESSION_DAYS = int(os.environ.get("STUDENT_MOBILE_SESSION_DAYS", "30"))
    STUDENT_MOBILE_REMEMBER_COOKIE = os.environ.get(
        "STUDENT_MOBILE_REMEMBER_COOKIE",
        "student_mobile_auth",
    )

    # Google AI (Gemini)
    GOOGLE_AI_API_KEY = os.environ.get("GOOGLE_AI_API_KEY")

    # Google Maps (Geocoding / Pincode lookup)
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY")

    # TinyMCE Rich Text Editor
    TINYMCE_API_KEY = os.environ.get("TINYMCE_API_KEY", "no-api-key")

    # SMS Gateway (api.sms-gate.app cloud relay)
    SMS_GATEWAY_USER = os.environ.get("SMS_GATEWAY_USER", "")
    SMS_GATEWAY_PASSWORD = os.environ.get("SMS_GATEWAY_PASSWORD", "")

    # LMS File Uploads
    UPLOAD_FOLDER = UPLOAD_DIR

    ALLOWED_EXTENSIONS = {
        'video_file': {'mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm'},
        'pdf':        {'pdf'},
        'image':      {'jpg', 'jpeg', 'png', 'gif', 'webp'},
        'download':   {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'txt', 'ppt', 'pptx'},
        'html':       {'html', 'htm'},
    }

    FILE_LIMITS = {
        'video_file': 500 * 1024 * 1024,   # 500 MB
        'pdf':         50 * 1024 * 1024,   #  50 MB
        'image':       10 * 1024 * 1024,   #  10 MB
        'download':   100 * 1024 * 1024,   # 100 MB
        'html':        10 * 1024 * 1024,   #  10 MB
    }

    @classmethod
    def validate(cls):
        if cls.APP_ENV != "production":
            return
        errors = []
        if len(cls.SECRET_KEY) < 32 or cls.SECRET_KEY.lower().startswith("replace-"):
            errors.append("SECRET_KEY must be a random value of at least 32 characters")
        if cls.DEBUG_MODE:
            errors.append("DEBUG_MODE must be false")
        if not cls.SESSION_COOKIE_SECURE:
            errors.append("SESSION_COOKIE_SECURE must be true")
        if cls.RATELIMIT_STORAGE_URI == "memory://":
            errors.append("RATELIMIT_STORAGE_URI must use shared storage in production")
        if cls.DB_TYPE != "mysql":
            errors.append("DB_TYPE must be mysql")
        if cls.STORAGE_PROVIDER != "gcs":
            errors.append("STORAGE_PROVIDER must be gcs")
        if errors:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))
