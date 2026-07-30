import os
import re
import base64
import logging
from config import Config

logger = logging.getLogger("app.storage")


_TENANT_PATH_RE = re.compile(r"^tenants/([1-9][0-9]*)/(.+)$")


def _payload_size(file_data):
    if isinstance(file_data, bytes):
        return len(file_data)
    if isinstance(file_data, str):
        encoded = file_data.split(",", 1)[1] if "," in file_data else file_data
        return len(base64.b64decode(encoded))
    if hasattr(file_data, "seek") and hasattr(file_data, "tell"):
        position = file_data.tell()
        file_data.seek(0, os.SEEK_END)
        size = file_data.tell()
        file_data.seek(position)
        return int(size)
    raise ValueError("Unable to determine upload size for quota enforcement.")


def _storage_write_guard(canonical_path, file_data):
    """Lock subscription capacity until storage metadata is committed."""
    from db import get_conn
    from services.subscriptions import lock_and_check_limit
    from services.tenant_context import get_current_institute_id

    tenant_id, _ = parse_tenant_storage_path(canonical_path)
    institute_id = tenant_id or get_current_institute_id(default=1)
    size_bytes = _payload_size(file_data)
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT size_bytes FROM tenant_storage_objects WHERE object_path = ?",
            (canonical_path,),
        ).fetchone()
        previous_size = int(existing["size_bytes"] or 0) if existing else 0
        requested = max(0, size_bytes - previous_size)
        lock_and_check_limit(conn, institute_id, "storage", requested)
        return conn, int(institute_id), size_bytes
    except Exception:
        conn.rollback()
        conn.close()
        raise


def _commit_storage_write(conn, institute_id, canonical_path, size_bytes, content_type):
    conn.execute(
        """
        INSERT INTO tenant_storage_objects (
            institute_id, object_path, size_bytes, content_type, created_at, updated_at
        ) VALUES (?, ?, ?, ?, NOW(), NOW())
        ON DUPLICATE KEY UPDATE institute_id = VALUES(institute_id),
            size_bytes = VALUES(size_bytes), content_type = VALUES(content_type),
            updated_at = NOW()
        """,
        (institute_id, canonical_path, size_bytes, content_type),
    )
    conn.commit()
    conn.close()


def _remove_storage_record(canonical_path):
    from db import get_conn

    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM tenant_storage_objects WHERE object_path = ?",
            (canonical_path,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Could not remove storage quota metadata for %s", canonical_path)
    finally:
        conn.close()


def parse_tenant_storage_path(path):
    normalized = (path or "").replace("\\", "/").lstrip("/")
    match = _TENANT_PATH_RE.fullmatch(normalized)
    if not match:
        return None, normalized
    relative = match.group(2)
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        return None, normalized
    return int(match.group(1)), relative


def map_local_path_to_gcs_path(path):
    """
    Compatibility helper: Maps a local file path (e.g. static/... or uploads/...)
    to the corresponding target GCS object path (e.g. student_photos/...).
    """
    if not path:
        return ""
    
    # Normalize backslashes to forward slashes
    path = path.replace("\\", "/").lstrip("/")
    tenant_id, tenant_relative = parse_tenant_storage_path(path)
    if tenant_id is not None:
        return f"tenants/{tenant_id}/{tenant_relative}"
    
    if "student_photos/" in path:
        filename = path.split("student_photos/")[-1]
        return f"student_photos/{filename}"
        
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


def tenant_storage_path(path, institute_id=None):
    """Return the canonical object key for the current institute.

    Institute 1 retains legacy object keys during migration. Every secondary
    institute is always namespaced, and an already namespaced key is preserved.
    """
    canonical = map_local_path_to_gcs_path(path)
    existing_tenant_id, _ = parse_tenant_storage_path(canonical)
    if existing_tenant_id is not None:
        try:
            from flask import has_request_context, session
            from services.tenant_context import get_current_institute_id

            current_id = get_current_institute_id()
            is_platform_owner = (
                has_request_context()
                and session.get("platform_role") == "platform_owner"
                and session.get("support_session_id")
            )
            if (
                current_id is not None
                and current_id != existing_tenant_id
                and not is_platform_owner
            ):
                raise PermissionError("Cross-institute storage access denied.")
        except RuntimeError:
            pass
        return canonical
    if institute_id is None:
        try:
            from services.tenant_context import get_current_institute_id
            institute_id = get_current_institute_id(default=1)
        except Exception:
            institute_id = 1
    institute_id = int(institute_id or 1)
    return canonical if institute_id == 1 else f"tenants/{institute_id}/{canonical}"

class LocalStorageProvider:
    """Fallback storage provider for local development."""
    def __init__(self):
        self.base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

    def _resolve_local_path(self, destination_path):
        # Map destination path back to a local storage location
        # e.g., student_photos/filename.jpg -> static/images/student_photos/filename.jpg
        destination_path = tenant_storage_path(destination_path)
        tenant_id, _ = parse_tenant_storage_path(destination_path)
        if tenant_id is not None:
            return os.path.join(self.base_dir, "uploads", *destination_path.split("/"))
        
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
        canonical_path = tenant_storage_path(destination_path)
        quota_conn, institute_id, size_bytes = _storage_write_guard(
            canonical_path, file_data
        )
        local_path = self._resolve_local_path(canonical_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        try:
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
            _commit_storage_write(
                quota_conn, institute_id, canonical_path, size_bytes, content_type
            )
            return canonical_path
        except Exception:
            quota_conn.rollback()
            quota_conn.close()
            raise

    def delete_file(self, destination_path):
        logger.info(f"LocalDelete: {destination_path}")
        canonical_path = tenant_storage_path(destination_path)
        local_path = self._resolve_local_path(canonical_path)
        if os.path.isfile(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                logger.error(f"Failed to delete local file {local_path}: {e}")
                return
        _remove_storage_record(canonical_path)

    def file_exists(self, destination_path):
        local_path = self._resolve_local_path(destination_path)
        return os.path.isfile(local_path)

    def generate_public_url(self, destination_path):
        # For local, serve from the application's static/uploads mount
        destination_path = tenant_storage_path(destination_path)
        tenant_id, _ = parse_tenant_storage_path(destination_path)
        if tenant_id is not None:
            return f"/tenant-files/{destination_path}"
        
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
        stored_path = self.upload_file(file_data, new_destination_path, content_type)
        if old_destination_path and tenant_storage_path(old_destination_path) != stored_path:
            self.delete_file(old_destination_path)
        return stored_path


class GCSStorageProvider:
    """Production storage provider for Google Cloud Storage."""
    def __init__(self):
        from google.cloud import storage
        self.client = storage.Client()
        self.bucket_name = getattr(Config, "GCS_BUCKET_NAME", "global-it-erp-storage")
        self.bucket = self.client.bucket(self.bucket_name)

    def upload_file(self, file_data, destination_path, content_type=None):
        logger.info(f"GCSUpload: {destination_path}")
        gcs_path = tenant_storage_path(destination_path)
        quota_conn, institute_id, size_bytes = _storage_write_guard(gcs_path, file_data)
        blob = self.bucket.blob(gcs_path)
        try:
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
            _commit_storage_write(
                quota_conn, institute_id, gcs_path, size_bytes, content_type
            )
            return gcs_path
        except Exception:
            quota_conn.rollback()
            quota_conn.close()
            raise

    def delete_file(self, destination_path):
        logger.info(f"GCSDelete: {destination_path}")
        gcs_path = tenant_storage_path(destination_path)
        blob = self.bucket.blob(gcs_path)
        try:
            blob.delete()
            _remove_storage_record(gcs_path)
        except Exception as e:
            # GCS returns exception if object doesn't exist, we can ignore it
            logger.debug(f"Failed to delete GCS object {gcs_path}: {e}")

    def file_exists(self, destination_path):
        gcs_path = tenant_storage_path(destination_path)
        blob = self.bucket.blob(gcs_path)
        return blob.exists()

    def generate_public_url(self, destination_path):
        gcs_path = tenant_storage_path(destination_path)
        tenant_id, _ = parse_tenant_storage_path(gcs_path)
        if tenant_id is not None:
            return f"/tenant-files/{gcs_path}"
        if gcs_path.startswith("certificates/"):
            # Certificate backgrounds are private GCS objects. Proxy legacy
            # institute-1 assets through Flask instead of returning a direct
            # storage.googleapis.com URL that browsers receive as HTTP 403.
            filename = gcs_path.split("certificates/", 1)[1]
            return f"/certificate-files/{filename}"
        if gcs_path.startswith("student_photos/"):
            filename = gcs_path.split("student_photos/", 1)[1]
            return f"/student-photos/{filename}"
        if gcs_path.startswith("signatures/"):
            filename = gcs_path.split("signatures/", 1)[1]
            return f"/student-signatures/{filename}"
        # Legacy Global IT compatibility until its stored objects are migrated.
        return f"https://storage.googleapis.com/{self.bucket_name}/{gcs_path}"

    def download_file(self, destination_path):
        gcs_path = tenant_storage_path(destination_path)
        blob = self.bucket.blob(gcs_path)
        return blob.download_as_bytes()

    def replace_file(self, file_data, old_destination_path, new_destination_path, content_type=None):
        stored_path = self.upload_file(file_data, new_destination_path, content_type)
        if old_destination_path and tenant_storage_path(old_destination_path) != stored_path:
            self.delete_file(old_destination_path)
        return stored_path


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
