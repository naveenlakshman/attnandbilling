import qrcode
import io
import base64
import datetime

def generate_qr_code_base64(url):
    """
    Generates a QR code image for a URL in-memory and returns its base64 string representation.
    """
    qr = qrcode.QRCode(version=1, box_size=8, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def get_month_year_from_date(date_str):
    """
    Parses a YYYY-MM-DD date and returns a tuple (MonthName, Year).
    """
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        month = dt.strftime("%B")
        year = dt.strftime("%Y")
        return month, year
    except:
        return "", ""

def ensure_template_preview(bg_filename):
    import os
    from flask import current_app
    from PIL import Image
    from services.storage import get_storage_service, map_local_path_to_gcs_path
    
    bg_filename = map_local_path_to_gcs_path(bg_filename)
    if "/" in bg_filename:
        bg_filename = bg_filename.split("/")[-1]
        
    dest_dir = os.path.join(current_app.root_path, 'static', 'images', 'certificate_templates')
    original_path = os.path.join(dest_dir, bg_filename)
    preview_name = os.path.splitext(bg_filename)[0] + "_preview.webp"
    preview_path = os.path.join(dest_dir, preview_name)
    
    storage_service = get_storage_service()
    if current_app.config.get("STORAGE_PROVIDER", "local") == "gcs":
        gcs_preview_path = f"certificates/{preview_name}"
        try:
            # 1. Check if the preview image already exists in GCS
            if storage_service.file_exists(gcs_preview_path):
                return preview_name
            
            # 2. Otherwise download and generate the preview from the original background
            gcs_bg_path = f"certificates/{bg_filename}"
            if not storage_service.file_exists(gcs_bg_path):
                return bg_filename
                
            bg_bytes = storage_service.download_file(gcs_bg_path)
            import io
            img = Image.open(io.BytesIO(bg_bytes))
            
            # Resize image
            resample_mode = getattr(Image, 'Resampling', None)
            mode = resample_mode.LANCZOS if (resample_mode and hasattr(resample_mode, 'LANCZOS')) else Image.BICUBIC
            img.thumbnail((1200, 1200), mode)
            
            # Save resampled image to memory and upload to GCS
            out_io = io.BytesIO()
            img.save(out_io, "WEBP", quality=80)
            out_io.seek(0)
            storage_service.upload_file(out_io.read(), gcs_preview_path, content_type="image/webp")
            return preview_name
        except Exception as e:
            print("Error creating template preview in GCS mode:", e)
            return bg_filename

    # Local fallback mode
    if os.path.exists(original_path):
        if os.path.exists(preview_path):
            return preview_name
        try:
            img = Image.open(original_path)
            resample_mode = getattr(Image, 'Resampling', None)
            mode = resample_mode.LANCZOS if (resample_mode and hasattr(resample_mode, 'LANCZOS')) else Image.BICUBIC
            img.thumbnail((1200, 1200), mode)
            img.save(preview_path, "WEBP", quality=80)
            return preview_name
        except Exception as e:
            print("Error creating local template preview:", e)
            return bg_filename

    return bg_filename

def get_certificate_render_data(cur, cert_id, base_url):
    """
    Combines certificate metadata, active templates, and dynamic position parameters 
    into structured CSS coordinates and base64 assets for rendering.
    """
    cert = cur.execute(
        """
        SELECT c.*, s.photo_filename, b.branch_name
        FROM certificates c
        JOIN students s ON s.id = c.student_id
        LEFT JOIN branches b ON b.id = s.branch_id
        WHERE c.id = ?
        """,
        (cert_id,)
    ).fetchone()
    
    if not cert:
        return None
        
    template = cur.execute(
        "SELECT * FROM certificate_templates WHERE id = ?",
        (cert["template_id"],)
    ).fetchone()
    
    if not template:
        return None
        
    fields = cur.execute(
        "SELECT * FROM certificate_template_fields WHERE template_id = ?",
        (template["id"],)
    ).fetchall()
    
    # Map completion date to month name and year representation
    month, year = get_month_year_from_date(cert["snapshot_completion_date"])
    
    # Generate verification QR Code locally targeting the public verify endpoint
    verification_url = f"{base_url.rstrip('/')}/verify-certificate/{cert['certificate_number']}"
    qr_base64 = generate_qr_code_base64(verification_url)
    
    # Build overlay CSS style block dictionary based on database parameters
    overlay_styles = {}
    for f in fields:
        style_parts = []
        if f["is_visible"]:
            style_parts.append("position: absolute;")
            style_parts.append("z-index: 2;")
            if f["left_position"]: style_parts.append(f"left: {f['left_position']};")
            if f["top_position"]: style_parts.append(f"top: {f['top_position']};")
            if f["width"]: style_parts.append(f"width: {f['width']};")
            if f["height"]: style_parts.append(f"height: {f['height']};")
            if f["font_family"]: style_parts.append(f"font-family: {f['font_family']}, sans-serif;")
            if f["font_size"]: style_parts.append(f"font-size: {f['font_size']};")
            if f["font_weight"]: style_parts.append(f"font-weight: {f['font_weight']};")
            if f["font_color"]: style_parts.append(f"color: {f['font_color']};")
            if f["text_align"]: 
                style_parts.append(f"text-align: {f['text_align']};")
            
            # Apply layout center offset translation
            if f["text_align"] == "center":
                if f["rotation"]:
                    style_parts.append(f"transform: translate(-50%, 0) rotate({f['rotation']}deg);")
                else:
                    style_parts.append("transform: translate(-50%, 0);")
            elif f["rotation"]:
                style_parts.append(f"transform: rotate({f['rotation']}deg);")
        else:
            style_parts.append("display: none;")
            
        overlay_styles[f["field_name"]] = " ".join(style_parts)

    cert_dict = dict(cert)
    if cert_dict.get("issue_date"):
        try:
            dt = datetime.datetime.strptime(cert_dict["issue_date"], "%Y-%m-%d")
            cert_dict["formatted_issue_date"] = dt.strftime("%d-%b-%Y")
        except Exception:
            cert_dict["formatted_issue_date"] = cert_dict["issue_date"]
    else:
        cert_dict["formatted_issue_date"] = ""

    template_dict = dict(template)
    template_dict["preview_filename"] = ensure_template_preview(template_dict["background_filename"])

    return {
        "certificate": cert_dict,
        "template": template_dict,
        "completion_month": month,
        "completion_year": year,
        "qr_base64": qr_base64,
        "overlay_styles": overlay_styles
    }
