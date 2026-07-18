import os
import sys
import logging
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("gcs_migration.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("migration")

from config import Config
from services.storage import get_storage_service, map_local_path_to_gcs_path
import db

# Map database table columns to search for migration
DB_MAPPINGS = [
    {
        "table": "company_profile",
        "column": "logo_filename",
        "folder": "logos"
    },
    {
        "table": "students",
        "column": "photo_filename",
        "folder": "student_photos"
    },
    {
        "table": "students",
        "column": "student_signature_filename",
        "folder": "signatures"
    },
    {
        "table": "students",
        "column": "parent_signature_filename",
        "folder": "signatures"
    },
    {
        "table": "student_uploaded_documents",
        "column": "file_path",
        "folder": "documents"
    },
    {
        "table": "leave_requests",
        "column": "document_filename",
        "folder": "documents"
    },
    {
        "table": "certificate_templates",
        "column": "background_filename",
        "folder": "certificates"
    },
    {
        "table": "certificate_templates",
        "column": "authorized_signature_image",
        "folder": "certificates"
    },
    {
        "table": "certificate_templates",
        "column": "seal_image",
        "folder": "certificates"
    },
    {
        "table": "lms_assignments",
        "column": "file_path",
        "folder": "documents"
    },
    {
        "table": "lms_assignment_submissions",
        "column": "file_path",
        "folder": "documents"
    }
]

# Define directories to scan locally
LOCAL_DIR_MAPPINGS = [
    {
        "dir": "static/images/student_photos",
        "folder": "student_photos"
    },
    {
        "dir": "static/images/student_signatures",
        "folder": "signatures"
    },
    {
        "dir": "static/images/company_logo",
        "folder": "logos"
    },
    {
        "dir": "static/certificates",
        "folder": "certificates"
    },
    {
        "dir": "uploads/student_documents",
        "folder": "documents"
    },
    {
        "dir": "instance/uploads/leave_docs",
        "folder": "documents"
    },
    {
        "dir": "instance/uploads/assignments",
        "folder": "documents"
    },
    {
        "dir": "instance/uploads/submissions",
        "folder": "documents"
    }
]

def migrate_files():
    logger.info("Starting file migration to Google Cloud Storage...")
    
    # Force GCS provider for migration
    Config.STORAGE_PROVIDER = "gcs"
    storage_service = get_storage_service()
    
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    stats = {
        "scanned": 0,
        "uploaded": 0,
        "skipped": 0,
        "db_updated": 0,
        "failed": 0
    }
    
    # 1. SCAN AND UPLOAD FILES
    for mapping in LOCAL_DIR_MAPPINGS:
        local_dir = os.path.join(base_dir, mapping["dir"])
        gcs_folder = mapping["folder"]
        
        if not os.path.isdir(local_dir):
            logger.warning(f"Local directory does not exist, skipping: {mapping['dir']}")
            continue
            
        logger.info(f"Scanning directory: {mapping['dir']} -> GCS folder: {gcs_folder}")
        for root, dirs, files in os.walk(local_dir):
            for file in files:
                stats["scanned"] += 1
                local_filepath = os.path.join(root, file)
                rel_path = os.path.relpath(local_filepath, local_dir).replace("\\", "/")
                
                # Form GCS destination path
                dest_path = f"{gcs_folder}/{rel_path}"
                
                try:
                    # Skip if already exists on GCS
                    if storage_service.file_exists(dest_path):
                        logger.info(f"File already exists in storage (skipping upload): {dest_path}")
                        stats["skipped"] += 1
                        continue
                        
                    # Upload
                    logger.info(f"Uploading file: {local_filepath} -> {dest_path}")
                    with open(local_filepath, "rb") as f:
                        file_bytes = f.read()
                    
                    storage_service.upload_file(file_bytes, dest_path)
                    stats["uploaded"] += 1
                    
                except Exception as e:
                    logger.error(f"Failed to upload {local_filepath}: {e}", exc_info=True)
                    stats["failed"] += 1
                    
    # 2. UPDATE DATABASE RECORDS FOR PARITY
    logger.info("Syncing and migrating database file path records...")
    conn = db.get_conn()
    
    try:
        cur = conn.cursor()
        for mapping in DB_MAPPINGS:
            table = mapping["table"]
            col = mapping["column"]
            folder = mapping["folder"]
            
            logger.info(f"Processing table: {table}, column: {col}...")
            
            # Fetch all records with non-empty paths
            cur.execute(f"SELECT id, `{col}` FROM `{table}` WHERE `{col}` IS NOT NULL AND `{col}` != ''")
            rows = cur.fetchall()
            
            for row in rows:
                row_id = row["id"]
                db_val = row[col]
                
                # If it already begins with the folder prefix, it's already migrated
                if db_val.startswith(f"{folder}/"):
                    continue
                    
                # Clean and map path
                new_val = map_local_path_to_gcs_path(db_val)
                
                # If path changed, update it
                if new_val != db_val:
                    logger.info(f"Updating database: {table}.{col} for ID {row_id}: '{db_val}' -> '{new_val}'")
                    try:
                        cur.execute(
                            f"UPDATE `{table}` SET `{col}` = ? WHERE id = ?",
                            (new_val, row_id)
                        )
                        stats["db_updated"] += 1
                    except Exception as db_err:
                        logger.error(f"Failed to update db record {table}.{col} ID {row_id}: {db_err}")
                        stats["failed"] += 1
                        
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database sync failed: {e}", exc_info=True)
    finally:
        conn.close()
        
    logger.info("=== MIGRATION SUMMARY ===")
    logger.info(f"Total Scanned Local Files: {stats['scanned']}")
    logger.info(f"Uploaded to GCS:           {stats['uploaded']}")
    logger.info(f"Already on GCS (Skipped):  {stats['skipped']}")
    logger.info(f"Database records updated:  {stats['db_updated']}")
    logger.info(f"Failures encountered:      {stats['failed']}")
    logger.info("Migration complete!")

if __name__ == '__main__':
    migrate_files()
