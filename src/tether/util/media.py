"""Helpers for handling media safely: filenames, MIME sniffing, compression."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_NAME = 180


def safe_filename(name: str | None, *, default: str = "file") -> str:
    """Return a filename stripped of directory components and unsafe characters."""
    if not name:
        return default
    basename = name.replace("\\", "/").split("/")[-1].strip().lstrip(".")
    cleaned = _UNSAFE.sub("_", basename).strip("_")
    return (cleaned or default)[:_MAX_NAME]


def spool_name(data: bytes, name: str | None) -> str:
    """Content-addressed spool filename: a short digest plus a safe basename."""
    digest = hashlib.sha256(data).hexdigest()[:8]
    return f"{digest}_{safe_filename(name)}"


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
    except Exception:  # Pillow/filetype are optional dependencies.
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


def spool_path(root: Path, data: bytes, name: str | None) -> Path:
    """Return the spool path for ``data``, creating the spool directory if needed."""
    root.mkdir(parents=True, exist_ok=True)
    return root / spool_name(data, name)
