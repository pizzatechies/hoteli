"""Validation for uploaded logo files (checked by content, not by file name)."""

from django.core.exceptions import ValidationError

MAX_BYTES = {"logo": 2 * 1024 * 1024, "logo-light": 2 * 1024 * 1024, "favicon": 512 * 1024}
SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
]


def sniff_image(data):
    """Return the image MIME type from the file's bytes, or None if it is not a supported image."""
    for magic, mime in SIGNATURES:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    head = data[:2048].lstrip(b"\xef\xbb\xbf").lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "image/svg+xml"
    return None


def read_logo(upload, kind):
    """Validate an uploaded file and return (content_type, bytes)."""
    limit = MAX_BYTES.get(kind, MAX_BYTES["logo"])
    if upload.size > limit:
        raise ValidationError(f"The file is too large – the limit is {limit // 1024} KB.")
    data = upload.read()
    content_type = sniff_image(data)
    if content_type is None:
        raise ValidationError("Upload a PNG, JPG, WebP, GIF, SVG or ICO image.")
    if kind == "favicon" and content_type == "image/gif":
        raise ValidationError("Use a PNG, ICO or SVG file for the favicon.")
    return content_type, data
