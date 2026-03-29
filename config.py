import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
UPLOAD_DIR = os.path.join(INSTANCE_DIR, "uploads", "content")

os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Create subdirectories for each content type
for content_type in ['videos', 'pdfs', 'images', 'downloads', 'html']:
    os.makedirs(os.path.join(UPLOAD_DIR, content_type), exist_ok=True)

SECRET_KEY = "your-secret-key"
DB_PATH = os.path.join(INSTANCE_DIR, "database.db")

class Config:
    SECRET_KEY = SECRET_KEY
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # File Upload Configuration
    UPLOAD_FOLDER = UPLOAD_DIR
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max file size
    
    # File type restrictions (mapped by content_mode)
    ALLOWED_EXTENSIONS = {
        'video_file': {'mp4', 'webm', 'ogv', 'avi', 'mov', 'mkv'},
        'pdf': {'pdf'},
        'image': {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'},
        'download': {'zip', 'rar', '7z', 'xls', 'xlsx', 'doc', 'docx', 'ppt', 'pptx', 'txt', 'csv'},
        'html': {'html', 'htm'}
    }
    
    # File size limits per type (in bytes)
    FILE_LIMITS = {
        'video_file': 50 * 1024 * 1024,    # 50MB for videos
        'pdf': 20 * 1024 * 1024,           # 20MB for PDFs
        'image': 10 * 1024 * 1024,         # 10MB for images
        'download': 30 * 1024 * 1024,      # 30MB for downloads
        'html': 5 * 1024 * 1024            # 5MB for HTML files
    }