import os
import re
import base64
import logging
from config import Config

logger = logging.getLogger("app.storage")

def map_local_path_to_gcs_path(path):
    """
    Compatibility helper: Maps a local file path (e.g. static/... or uploads/...)
    to the corresponding target GCS object path (e.g. student_photos/...).
    """
    if not path:
        return ""
    
    # Normalize backslashes to forward slashes
    path = path.replace("\\", "/")
    
    # Extract path from absolute paths if needed
    if "static/images/certificate_templates/" in path:
        filename = path.split("static/images/certificate_templates/")[-1]
        return f"certificates/{filename}"
    elif "certificate.png" in path or "default.png" in path:
        filename = path.split("/")[-1]
        return f"certificates/{filename}"
    elif "static/images/student_photos/" in path:
        filename = path.split("static/images/student_photos/")[-1]
        return f"student_photos/{filename}"
    elif "static/images/student_signatures/" in path:
        filename = path.split("static/images/student_signatures/")[-1]
        return f"signatures/{filename}"
    elif "static/images/company_logo/" in path:
        filename = path.split("static/images/company_logo/")[-1]
        return f"logos/{filename}"
    elif "uploads/student_documents/" in path:
        filename = path.split("uploads/student_documents/")[-1]
        return f"documents/{filename}"
    elif "uploads/leave_docs/" in path or "instance/uploads/leave_docs/" in path:
        filename = path.split("leave_docs/")[-1]
        return f"documents/{filename}"
    elif "uploads/submissions/" in path or "instance/uploads/submissions/" in path:
        filename = path.split("submissions/")[-1]
        return f"documents/{filename}"
    elif "uploads/assignments/" in path or "instance/uploads/assignments/" in path:
        filename = path.split("assignments/")[-1]
        return f"documents/{filename}"
    elif "static/certificates/" in path:
        filename = path.split("static/certificates/")[-1]
        return f"certificates/{filename}"
    
    # Clean standard prefixes
    for prefix in ["instance/uploads/", "uploads/", "static/"]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            
    # If the path is just a filename (no slashes)
    if "/" not in path:
        if "signature" in path:
            return f"signatures/{path}"
        elif "company_logo" in path:
            return f"logos/{path}"
        elif path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.svg')):
            return f"student_photos/{path}"
        else:
            return f"documents/{path}"

    return path

class LocalStorageProvider:
    """Fallback storage provider for local development."""
    def __init__(self):
        self.base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    def _resolve_local_path(self, destination_path):
        # Map destination path back to a local storage location
        # e.g., student_photos/filename.jpg -> static/images/student_photos/filename.jpg
        destination_path = map_local_path_to_gcs_path(destination_path)
        
        if destination_path.startswith("student_photos/"):
            filename = destination_path.split("student_photos/")[-1]
            return os.path.join(self.base_dir, "static", "images", "student_photos", filename)
        elif destination_path.startswith("signatures/"):
            filename = destination_path.split("signatures/")[-1]
            return os.path.join(self.base_dir, "static", "images", "student_signatures", filename)
        elif destination_path.startswith("logos/"):
            filename = destination_path.split("logos/")[-1]
            return os.path.join(self.base_dir, "static", "images", "company_logo", filename)
        elif destination_path.startswith("certificates/"):
            filename = destination_path.split("certificates/")[-1]
            return os.path.join(self.base_dir, "static", "certificates", filename)
        
        # Default fallback folder is uploads/
        return os.path.join(self.base_dir, "uploads", destination_path)

    def upload_file(self, file_data, destination_path, content_type=None):
        logger.info(f"LocalUpload: {destination_path}")
        local_path = self._resolve_local_path(destination_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        if isinstance(file_data, str) and (file_data.startswith("data:") or "," in file_data):
            # Base64 string decode
            if "," in file_data:
                file_data = file_data.split(",")[1]
            data_bytes = base64.b64decode(file_data)
            with open(local_path, "wb") as f:
                f.write(data_bytes)
        elif isinstance(file_data, bytes):
            with open(local_path, "wb") as f:
                f.write(file_data)
        else:
            # File-like object (Flask FileStorage)
            file_data.seek(0)
            file_data.save(local_path)
            
        return map_local_path_to_gcs_path(destination_path)

    def delete_file(self, destination_path):
        logger.info(f"LocalDelete: {destination_path}")
        local_path = self._resolve_local_path(destination_path)
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logger.error(f"Failed to delete local file {local_path}: {e}")

    def file_exists(self, destination_path):
        local_path = self._resolve_local_path(destination_path)
        return os.path.isfile(local_path)

    def generate_public_url(self, destination_path):
        # For local, serve from the application's static/uploads mount
        destination_path = map_local_path_to_gcs_path(destination_path)
        
        if destination_path.startswith("student_photos/"):
            filename = destination_path.split("student_photos/")[-1]
            return f"/static/images/student_photos/{filename}"
        elif destination_path.startswith("signatures/"):
            filename = destination_path.split("signatures/")[-1]
            return f"/static/images/student_signatures/{filename}"
        elif destination_path.startswith("logos/"):
            filename = destination_path.split("logos/")[-1]
            return f"/static/images/company_logo/{filename}"
        elif destination_path.startswith("certificates/"):
            filename = destination_path.split("certificates/")[-1]
            return f"/static/certificates/{filename}"
            
        return f"/uploads/{destination_path}"

    def download_file(self, destination_path):
        local_path = self._resolve_local_path(destination_path)
        with open(local_path, "rb") as f:
            return f.read()

    def replace_file(self, file_data, old_destination_path, new_destination_path, content_type=None):
        if old_destination_path:
            self.delete_file(old_destination_path)
        return self.upload_file(file_data, new_destination_path, content_type)


class GCSStorageProvider:
    """Production storage provider for Google Cloud Storage."""
    def __init__(self):
        from google.cloud import storage
        self.client = storage.Client()
        self.bucket_name = getattr(Config, "GCS_BUCKET_NAME", "global-it-erp-storage")
        self.bucket = self.client.bucket(self.bucket_name)

    def upload_file(self, file_data, destination_path, content_type=None):
        logger.info(f"GCSUpload: {destination_path}")
        gcs_path = map_local_path_to_gcs_path(destination_path)
        blob = self.bucket.blob(gcs_path)

        if isinstance(file_data, str) and (file_data.startswith("data:") or "," in file_data):
            # Base64 string decode
            if "," in file_data:
                file_data = file_data.split(",")[1]
            data_bytes = base64.b64decode(file_data)
            blob.upload_from_string(data_bytes, content_type=content_type or "image/jpeg")
        elif isinstance(file_data, bytes):
            blob.upload_from_string(file_data, content_type=content_type or "application/octet-stream")
        else:
            # File-like object (Flask FileStorage)
            file_data.seek(0)
            if hasattr(file_data, "read"):
                # GCS upload_from_file expects stream
                blob.upload_from_file(file_data, content_type=content_type or file_data.content_type)
            else:
                file_data.save(blob)

        return gcs_path

    def delete_file(self, destination_path):
        logger.info(f"GCSDelete: {destination_path}")
        gcs_path = map_local_path_to_gcs_path(destination_path)
        blob = self.bucket.blob(gcs_path)
        try:
            blob.delete()
        except Exception as e:
            # GCS returns exception if object doesn't exist, we can ignore it
            logger.debug(f"Failed to delete GCS object {gcs_path}: {e}")

    def file_exists(self, destination_path):
        gcs_path = map_local_path_to_gcs_path(destination_path)
        blob = self.bucket.blob(gcs_path)
        return blob.exists()

    def generate_public_url(self, destination_path):
        gcs_path = map_local_path_to_gcs_path(destination_path)
        # Standard GCS public URL format
        return f"https://storage.googleapis.com/{self.bucket_name}/{gcs_path}"

    def download_file(self, destination_path):
        gcs_path = map_local_path_to_gcs_path(destination_path)
        blob = self.bucket.blob(gcs_path)
        return blob.download_as_bytes()

    def replace_file(self, file_data, old_destination_path, new_destination_path, content_type=None):
        if old_destination_path:
            self.delete_file(old_destination_path)
        return self.upload_file(file_data, new_destination_path, content_type)


# Single-instance storage service factory
_storage_service = None

def get_storage_service():
    global _storage_service
    if _storage_service is None:
        provider = getattr(Config, "STORAGE_PROVIDER", "local").lower()
        if provider == "gcs":
            logger.info("Initializing Google Cloud Storage Provider")
            _storage_service = GCSStorageProvider()
        else:
            logger.info("Initializing Local Filesystem Storage Provider")
            _storage_service = LocalStorageProvider()
    return _storage_service
