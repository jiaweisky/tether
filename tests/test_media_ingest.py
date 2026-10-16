from __future__ import annotations

import pytest

from tether.config import Config
from tether.engine.media_ingest import MediaIngest
from tether.models import Attachment, MediaBytes


class FakeConnector:
    name = "fake"

    def __init__(
        self, data: bytes, *, fail: bool = False, download_name: str | None = None
    ) -> None:
        self._data = data
        self._fail = fail
        self._download_name = download_name
        self.downloads = 0

    async def download(self, att: Attachment) -> MediaBytes:
        self.downloads += 1
        if self._fail:
            raise RuntimeError("download failed")
        return MediaBytes(data=self._data, mime=att.mime, name=self._download_name or att.name)


def _ingest(connector) -> MediaIngest:
    return MediaIngest(Config(), connector)


@pytest.mark.asyncio
async def test_attachment_becomes_an_inline_file_part():
    ingest = _ingest(FakeConnector(b"\x89PNG\r\n\x1a\n"))
    att = Attachment(kind="image", name="a.png", handle={"url": "x"})
    result = await ingest.ingest([att])
    assert result.files
    part = result.files[0]
    assert part["uri"].startswith("data:image/png;base64,")
    assert part["name"] == "a.png" and part["mime"] == "image/png"


@pytest.mark.asyncio
async def test_declared_oversized_attachment_is_skipped_before_download():
    connector = FakeConnector(b"x")
    ingest = _ingest(connector)
    oversized = Config().media.max_attachment_bytes + 1
    att = Attachment(kind="video", name="big.mp4", size=oversized, handle={"url": "x"})
    result = await ingest.ingest([att])
    assert connector.downloads == 0, "must not download an attachment we will reject"
    assert not result.files
    assert any("too large" in note for note in result.notes)


@pytest.mark.asyncio
async def test_download_failure_is_reported():
    ingest = _ingest(FakeConnector(b"", fail=True))
    att = Attachment(kind="image", name="a.png", handle={"url": "x"})
    result = await ingest.ingest([att])
    assert not result.files
    assert any("Failed to download" in note for note in result.notes)


@pytest.mark.asyncio
async def test_downloaded_filename_is_used():
    ingest = _ingest(FakeConnector(b"x", download_name="季度报表.xlsx"))
    att = Attachment(kind="file", name=None, handle={"url": "x"})
    result = await ingest.ingest([att])
    assert result.files[0]["name"] == "季度报表.xlsx"
