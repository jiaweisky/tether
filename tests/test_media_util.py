from __future__ import annotations

from tether.util.media import compress_image, sniff_mime


def test_sniff_mime_trusts_a_specific_declaration():
    assert sniff_mime(b"\x00\x01", "x.png", "image/jpeg") == "image/jpeg"


def test_sniff_mime_guesses_by_extension_when_unsniffable():
    assert sniff_mime(b"not-an-image", "report.pdf", None) == "application/pdf"


def test_sniff_mime_falls_back_to_octet_stream():
    assert sniff_mime(b"\x00\x01", None, None) == "application/octet-stream"
    assert sniff_mime(b"\x00\x01", None, "application/octet-stream") == "application/octet-stream"


def test_compress_image_returns_bytes():
    out = compress_image(b"not-an-image", max_bytes=10, mime="image/jpeg")
    assert out == b"not-an-image"  # undecodable → returned unchanged
