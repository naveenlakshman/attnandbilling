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
    import io
    from flask import current_app
    from PIL import Image
    from services.storage import (
        get_storage_service,
        map_local_path_to_gcs_path,
        parse_tenant_storage_path
    )
    
    if not bg_filename:
        return ""
        
    canonical_bg = map_local_path_to_gcs_path(bg_filename)
    tenant_id, tenant_relative = parse_tenant_storage_path(canonical_bg)
    
    bg_basename = os.path.basename(tenant_relative or canonical_bg)
    preview_basename = os.path.splitext(bg_basename)[0] + "_preview.webp"
    
    if tenant_id is not None:
        rel_dir = os.path.dirname(tenant_relative) or "certificates"
        canonical_preview = f"tenants/{tenant_id}/{rel_dir}/{preview_basename}"
    else:
        rel_dir = os.path.dirname(canonical_bg) if "/" in canonical_bg else "certificates"
        canonical_preview = f"{rel_dir}/{preview_basename}" if rel_dir else f"certificates/{preview_basename}"
        
    storage_service = get_storage_service()
    
    try:
        if storage_service.file_exists(canonical_preview):
            return canonical_preview
    except Exception as e:
        print("Error checking template preview existence:", e)
        
    try:
        bg_bytes = None
        if storage_service.file_exists(canonical_bg):
            bg_bytes = storage_service.download_file(canonical_bg)
        else:
            # Check local fallback paths
            dest_dir = os.path.join(current_app.root_path, 'static', 'images', 'certificate_templates')
            local_path = os.path.join(dest_dir, bg_basename)
            if os.path.exists(local_path):
                with open(local_path, "rb") as f:
                    bg_bytes = f.read()
            else:
                alt_dir = os.path.join(current_app.root_path, 'static', 'certificates')
                alt_path = os.path.join(alt_dir, bg_basename)
                if os.path.exists(alt_path):
                    with open(alt_path, "rb") as f:
                        bg_bytes = f.read()
                        
        if not bg_bytes:
            return canonical_bg
            
        img = Image.open(io.BytesIO(bg_bytes))
        resample_mode = getattr(Image, 'Resampling', None)
        mode = resample_mode.LANCZOS if (resample_mode and hasattr(resample_mode, 'LANCZOS')) else Image.BICUBIC
        img.thumbnail((1200, 1200), mode)
        
        out_io = io.BytesIO()
        img.save(out_io, "WEBP", quality=80)
        preview_bytes = out_io.getvalue()
        
        storage_service.upload_file(preview_bytes, canonical_preview, content_type="image/webp")
        
        # Save to local static folders if present
        for subfolder in ['images/certificate_templates', 'certificates']:
            dest_dir = os.path.join(current_app.root_path, 'static', subfolder)
            if os.path.exists(dest_dir):
                try:
                    with open(os.path.join(dest_dir, preview_basename), "wb") as f:
                        f.write(preview_bytes)
                except Exception:
                    pass
                    
        return canonical_preview
    except Exception as e:
        print("Error creating template preview:", e)
        return canonical_bg

def get_certificate_render_data(cur, cert_id, base_url):
    """
    Combines certificate metadata, active templates, and dynamic position parameters 
    into structured CSS coordinates and base64 assets for rendering.
    """
    cert = cur.execute(
        """
        SELECT c.*, s.photo_filename, b.branch_name, cr.duration AS course_live_duration, cr.duration_hours AS course_live_duration_hours
        FROM certificates c
        JOIN students s ON s.id = c.student_id
        LEFT JOIN branches b ON b.id = s.branch_id
        LEFT JOIN courses cr ON cr.id = c.course_id
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
    if not (cert_dict.get("snapshot_course_duration") or "").strip():
        live_dur = (cert_dict.get("course_live_duration") or "").strip()
        if not live_dur and cert_dict.get("course_live_duration_hours"):
            live_dur = f"{cert_dict['course_live_duration_hours']} Hours"
        cert_dict["snapshot_course_duration"] = live_dur

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
