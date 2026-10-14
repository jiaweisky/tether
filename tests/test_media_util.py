from __future__ import annotations

from tether.util.media import safe_filename, spool_name


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
