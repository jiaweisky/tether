"""Helpers for handling media safely: filenames, MIME sniffing, compression."""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path

_UNSAFE = re.compile(r"[^\w.-]+")
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


_IMAGE_MAX_DIM = 1568
_AV_MAX_INPUT_BYTES = 512 * 1024 * 1024  # do not transcode enormous inputs
_AV_TIMEOUT_S = 30


def downsample(data: bytes, *, mime: str, max_bytes: int) -> tuple[bytes, str] | None:
    """Shrink media to fit ``max_bytes``, or return ``None`` if it cannot.

    Returns the re-encoded ``(bytes, mime)`` — the mime changes (images become JPEG,
    audio MP3, video MP4). Images are shrunk in-process with Pillow; audio and video
    with ``ffmpeg`` when it is on ``PATH``. ``None`` means "leave it alone" — the tool
    is missing, the input is too large to process, or the result still exceeds the cap.
    """
    if mime.startswith("image/"):
        out = _shrink_image(data, max_bytes)
        return (out, "image/jpeg") if out is not None else None
    if mime.startswith("audio/"):
        out = _shrink_av(
            data,
            mime,
            "mp3",
            ["-vn", "-c:a", "libmp3lame", "-b:a", "32k", "-ac", "1", "-ar", "16000"],
            max_bytes,
        )
        return (out, "audio/mpeg") if out is not None else None
    if mime.startswith("video/"):
        out = _shrink_av(
            data,
            mime,
            "mp4",
            [
                "-vf",
                "scale='min(854,iw)':-2",
                "-c:v",
                "libx264",
                "-crf",
                "28",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-b:a",
                "64k",
                "-movflags",
                "+faststart",
            ],
            max_bytes,
        )
        return (out, "video/mp4") if out is not None else None
    return None


def _shrink_image(data: bytes, max_bytes: int) -> bytes | None:
    try:
        from io import BytesIO

        from PIL import Image
    except Exception:  # Pillow is optional; without it we cannot shrink images
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            image.draft("RGB", (_IMAGE_MAX_DIM, _IMAGE_MAX_DIM))  # fast JPEG scale-on-decode
            base = image.convert("RGB")
            for cap in (_IMAGE_MAX_DIM, 1024, 768):
                frame = base.copy()
                frame.thumbnail((cap, cap), Image.Resampling.LANCZOS)
                for quality in (85, 70, 55, 40):
                    buffer = BytesIO()
                    frame.save(buffer, format="JPEG", quality=quality, optimize=True)
                    if buffer.tell() <= max_bytes:
                        return buffer.getvalue()
    except Exception:  # noqa: BLE001 - corrupt or unsupported input
        return None
    return None


def _shrink_av(
    data: bytes, mime: str, out_ext: str, args: list[str], max_bytes: int
) -> bytes | None:
    import shutil
    import subprocess
    import tempfile

    if len(data) > _AV_MAX_INPUT_BYTES or shutil.which("ffmpeg") is None:
        return None
    in_ext = re.sub(r"[^A-Za-z0-9]", "", mime.split("/", 1)[-1])[:8] or "bin"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in.{in_ext}"
        dst = Path(tmp) / f"out.{out_ext}"
        src.write_bytes(data)
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src), *args, str(dst),
        ]
        try:
            subprocess.run(command, check=True, timeout=_AV_TIMEOUT_S, capture_output=True)
            out = dst.read_bytes()
        except (subprocess.SubprocessError, OSError, TimeoutError):
            return None
    return out if 0 < len(out) <= max_bytes else None
