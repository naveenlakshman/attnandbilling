# LMS Content File Upload System

## Overview
Admins can now directly upload content files (PDFs, videos, images, downloadables) from the content creation/edit forms. Files are automatically stored in organized folders and linked to the content in the database.

## Features
✅ **Multiple Content Types Supported**
- 📹 Video Files (.mp4, .webm, .ogv, .avi, .mov, .mkv) - max 50MB
- 📄 PDF Documents (.pdf) - max 20MB  
- 🖼️ Images (.jpg, .png, .gif, .webp, .bmp) - max 10MB
- ⬇️ Downloadable Resources (.zip, .rar, .xls, .doc, etc.) - max 30MB

✅ **Smart File Handling**
- Automatic filename sanitization and uniqueness (timestamp-based)
- File validation (type & size checks)
- Organized folder structure by content type
- Existing file replacement on update
- User-friendly error messages

✅ **Security Features**
- File type whitelist validation
- File size limits per type
- Secure filename generation
- Path traversal prevention

## File Organization
```
instance/
├── uploads/
│   └── content/
│       ├── videos/          (MP4, WebM, OGV, etc.)
│       ├── pdfs/            (PDF documents)
│       ├── images/          (JPG, PNG, GIF, etc.)
│       └── downloads/       (ZIP, XLS, DOC, etc.)
└── database.db
```

## How to Use

### Adding New Content with File Upload

1. Go to **LMS Admin > Programs > Select Program > Chapters > Select Chapter > Topics > Select Topic > Contents > New**
2. Fill in **Content Title**
3. Select **Content Type** (e.g., "📕 PDF Document")
4. **📁 Upload Your File** - Click the file input and select your file
5. Add optional description
6. Set display order
7. Click **Add Content** to save

### Editing Content and Replacing Files

1. Go to content's **Edit** button
2. To change the file: Click the file input in the content section
3. Select a new file (existing file will be replaced)
4. Click **Save Changes**

### File Upload Validation

The system automatically validates:
- **File format**: Only accepts specific extensions per content type
- **File size**: Enforces maximum size limits
- **File integrity**: Saves with timestamp-based unique names

Example error handling:
```
❌ File type .exe not allowed. Allowed: zip, rar, 7z, xls, xlsx, doc, docx, ppt, pptx, txt, csv
❌ File size 55.5MB exceeds limit of 50MB
✅ File uploaded successfully: my-lecture.mp4
```

## Database Storage
Files are stored with **relative paths** in the database for portability:
```
/uploads/content/videos/20260329_143025_lecture.mp4
/uploads/content/pdfs/20260329_143030_guide.pdf
/uploads/content/images/20260329_143035_diagram.png
```

This allows:
- Easy migration to different servers
- Backup and restore operations
- URL generation for file serving

## Technical Details

### Configuration (config.py)
```python
# Added to Config class:
UPLOAD_FOLDER = instance/uploads/content
MAX_CONTENT_LENGTH = 100MB  # Total upload limit
ALLOWED_EXTENSIONS = {...}  # File type whitelist
FILE_LIMITS = {...}         # Per-type size limits
```

### Upload Handler (routes.py)
- Function: `upload_file(file_obj, content_type)`
- Returns: (success: bool, file_path or error_msg: str)
- Handles: Validation, sanitization, storage, error reporting

### File Serving (app.py)
- Route: `/uploads/content/<path:filename>`
- Purpose: Serve uploaded files to students/users
- Security: Limited to uploads/content directory

### Form Updates (template)
- Added `enctype="multipart/form-data"` to form
- Replaced text inputs with file inputs
- Shows file format & size requirements
- Displays current file for existing content

## Limits & Restrictions

| Content Type | Max Size | Allowed Formats |
|---|---|---|
| Video | 50 MB | mp4, webm, ogv, avi, mov, mkv |
| PDF | 20 MB | pdf |
| Image | 10 MB | jpg, jpeg, png, gif, webp, bmp |
| Download | 30 MB | zip, rar, 7z, xls, xlsx, doc, docx, ppt, pptx, txt, csv |

## Troubleshooting

**Issue: "File upload failed: File type not allowed"**
- Ensure file has correct extension
- Use supported formats from the table above

**Issue: "File size exceeds limit"**
- Compress the file or split into smaller parts
- Check the content type's size limit

**Issue: "Error saving file"**
- Check disk space availability
- Verify folder permissions (instance/uploads/content/)
- Check write permissions on the instance folder

**Issue: File not displaying/downloading**
- Verify file was uploaded successfully (check in instance/uploads/content/)
- Check file path in database
- Ensure Flask app has file serving route configured

## Future Enhancements
- Drag-and-drop file upload UI
- File preview before upload
- Batch file upload for multiple content items
- Storage quota per admin/department
- Malware scanning integration
- Video transcoding for multiple formats

## Support
For issues or questions about file uploads, contact system administrator.
