import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
UPLOAD_DIR = os.path.join(INSTANCE_DIR, "uploads", "content")

os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Create subdirectories for each content type
for content_type in ['videos', 'pdfs', 'images', 'downloads', 'html']:
    os.makedirs(os.path.join(UPLOAD_DIR, content_type), exist_ok=True)

load_dotenv(os.path.join(BASE_DIR, ".env"))

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key:
    raise RuntimeError(
        "SECRET_KEY is not set. Add SECRET_KEY=<random hex> to your .env file."
    )

DB_PATH = os.path.join(INSTANCE_DIR, "database.db")

class Config:
    SECRET_KEY = _secret_key
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session: sliding expiry — stays alive while active, expires after 7 days idle
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = True

    # Secure cookie flags
    SESSION_COOKIE_SECURE = True    # HTTPS only
    SESSION_COOKIE_HTTPONLY = True  # Prevent JS access
    SESSION_COOKIE_SAMESITE = "Lax" # CSRF mitigation

    # CSRF protection (Flask-WTF)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # Tokens live for the full session (needed for 7-day sessions)
