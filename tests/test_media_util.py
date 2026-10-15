from __future__ import annotations

import os
from io import BytesIO

from tether.util.media import downsample, safe_filename, spool_name


def _noisy_png(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.frombytes("RGB", (width, height), os.urandom(width * height * 3)).save(buffer, "PNG")
    return buffer.getvalue()


def test_safe_filename_keeps_unicode():
    assert safe_filename("季度报表.xlsx") == "季度报表.xlsx"


def test_safe_filename_strips_directory_components():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("a\\b\\c.txt") == "c.txt"
    assert safe_filename(".bashrc") == "bashrc"


def test_safe_filename_replaces_unsafe_characters():
    assert safe_filename("a b:c?.txt") == "a_b_c_.txt"


def test_safe_filename_falls_back_when_empty():
    assert safe_filename(None) == "file"
    assert safe_filename("") == "file"
    assert safe_filename("...") == "file"
    assert safe_filename("!!!", default="x") == "x"


def test_safe_filename_truncates_long_names():
    assert len(safe_filename("a" * 500)) == 180


def test_spool_name_is_content_addressed():
    assert spool_name(b"payload", "季度报表.xlsx").endswith("_季度报表.xlsx")
    assert spool_name(b"payload", None).endswith("_file")


def test_downsample_image_fits_and_is_jpeg():
    from PIL import Image

    source = _noisy_png(1200, 900)
    assert len(source) > 262144  # the input is genuinely over the limit
    result = downsample(source, mime="image/png", max_bytes=262144)
    assert result is not None
    out, out_mime = result
    assert out_mime == "image/jpeg"
    assert 0 < len(out) <= 262144
    assert out[:2] == b"\xff\xd8"  # JPEG magic
    assert Image.open(BytesIO(out)).size[0] <= 1568


def test_downsample_unknown_mime_returns_none():
    assert downsample(b"whatever", mime="application/pdf", max_bytes=100) is None
