"""Helpers for handling media safely: MIME sniffing and image compression."""

from __future__ import annotations

import mimetypes


def sniff_mime(data: bytes, name: str | None, declared: str | None) -> str:
    """Best-effort MIME type: trust a specific declaration, else sniff, else guess."""
    if declared and declared != "application/octet-stream":
        return declared

    guessed = _guess_by_content(data)
    if guessed:
        return guessed

    if name:
        by_extension, _ = mimetypes.guess_type(name)
        if by_extension:
            return by_extension

    return declared or "application/octet-stream"


def _guess_by_content(data: bytes) -> str | None:
    try:
        import filetype

        kind = filetype.guess(data)
        return kind.mime if kind is not None else None
    except Exception:  # filetype is optional
        return None


def compress_image(data: bytes, *, max_bytes: int, mime: str) -> bytes:
    """Shrink an image to fit ``max_bytes`` when Pillow is available.

    Returns the original bytes when Pillow is missing or compression fails.
    """
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            fmt = "JPEG" if mime in ("image/jpeg", "image/jpg") else "PNG"
            source = image.convert("RGB") if fmt == "JPEG" else image
            return _encode_within_limit(source, fmt, max_bytes)
    except Exception:
        return data


def _encode_within_limit(image, fmt: str, max_bytes: int) -> bytes:  # noqa: ANN001
    from io import BytesIO

    buffer = BytesIO()
    quality = 85
    while quality > 20:
        buffer.seek(0)
        buffer.truncate()
        image.save(buffer, format=fmt, quality=quality, optimize=True)

        if buffer.tell() <= max_bytes:
            break
        quality -= 15

    return buffer.getvalue()
