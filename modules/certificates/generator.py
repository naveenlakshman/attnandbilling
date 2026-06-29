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

    return {
        "certificate": dict(cert),
        "template": dict(template),
        "completion_month": month,
        "completion_year": year,
        "qr_base64": qr_base64,
        "overlay_styles": overlay_styles
    }
