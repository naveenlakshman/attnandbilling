import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config
from services.storage import get_storage_service, map_local_path_to_gcs_path

def test_provider(provider_type):
    print(f"\n================ TESTING PROVIDER: {provider_type.upper()} ================")
    # Temporarily override configuration
    original_provider = Config.STORAGE_PROVIDER
    Config.STORAGE_PROVIDER = provider_type
    
    # Force re-initialization of storage service singleton
    import services.storage
    services.storage._storage_service = None
    
    service = get_storage_service()
    
    test_file_content = b"ERP GCS MIGRATION TEST CONTENT"
    test_photo_path = "student_photos/TEST_STUDENT_CODE.jpg"
    test_doc_path = "documents/TEST_DOC_UUID.pdf"
    
    try:
        # Test 1: Upload File
        print(f"1. Uploading test student photo to '{test_photo_path}'...")
        uploaded_path = service.upload_file(test_file_content, test_photo_path, content_type="image/jpeg")
        print(f"   Returned Path: {uploaded_path}")
        assert uploaded_path == test_photo_path, f"Upload path mismatch: {uploaded_path} != {test_photo_path}"
        
        # Test 2: File Exists
        print("2. Checking file existence...")
        exists = service.file_exists(test_photo_path)
        print(f"   Exists: {exists}")
        assert exists, "File should exist after upload"
        
        # Test 3: Generate URL
        print("3. Generating public URL...")
        url = service.generate_public_url(test_photo_path)
        print(f"   Generated URL: {url}")
        if provider_type == "gcs":
            assert "storage.googleapis.com" in url, "GCS URL must contain googleapis.com"
        else:
            assert url.startswith("/static/images/student_photos/"), "Local URL must point to static mount"
            
        # Test 4: Download File
        print("4. Downloading file...")
        downloaded_bytes = service.download_file(test_photo_path)
        print(f"   Downloaded size: {len(downloaded_bytes)} bytes")
        assert downloaded_bytes == test_file_content, "Downloaded content must match uploaded content"
        
        # Test 5: Replace File
        print("5. Replacing file...")
        new_content = b"REPLACED ERP CONTENT"
        replaced_path = service.replace_file(new_content, test_photo_path, test_photo_path, content_type="image/jpeg")
        downloaded_replaced = service.download_file(test_photo_path)
        assert downloaded_replaced == new_content, "Replaced content must match"
        print("   Replace successful")
        
        # Test 6: Delete File
        print("6. Deleting file...")
        service.delete_file(test_photo_path)
        exists_after_delete = service.file_exists(test_photo_path)
        print(f"   Exists after delete: {exists_after_delete}")
        assert not exists_after_delete, "File must not exist after delete"
        
        print(f"SUCCESS: {provider_type.upper()} provider passed all checks!")
        
    except Exception as e:
        print(f"FAILURE on {provider_type.upper()} provider: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Cleanup
        try:
            service.delete_file(test_photo_path)
        except Exception:
            pass
        Config.STORAGE_PROVIDER = original_provider
        services.storage._storage_service = None

if __name__ == '__main__':
    # Test local provider
    test_provider("local")
    
    # Test GCS provider (if environment is set up or CLI is authenticated)
    if os.environ.get("GCS_BUCKET_NAME") or "gcs" in sys.argv:
        test_provider("gcs")
    else:
        print("\nSkipping GCS provider tests. Run with argument 'gcs' or set GCS_BUCKET_NAME to test GCS.")
