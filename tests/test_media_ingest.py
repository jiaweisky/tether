from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fakes import FakeAgentClient

from tether.config import Config
from tether.engine.media_ingest import MediaIngest
from tether.models import Attachment, MediaBytes


class FakeConnector:
    name = "fake"

    def __init__(self, data: bytes, *, fail: bool = False) -> None:
        self._data = data
        self._fail = fail
        self.downloads = 0

    async def download(self, att: Attachment) -> MediaBytes:
        self.downloads += 1
        if self._fail:
            raise RuntimeError("download failed")
        return MediaBytes(data=self._data, mime=att.mime, name=att.name)


def _ingest(tmp_path, connector) -> MediaIngest:
    return MediaIngest(Config(), connector, FakeAgentClient(), working_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_small_supported_image_is_inlined(tmp_path):
    ingest = _ingest(tmp_path, FakeConnector(b"\x89PNG\r\n\x1a\n"))
    att = Attachment(kind="image", name="a.png", handle={"url": "x"})
    result = await ingest.ingest("ses_1", [att], model_inputs={"image", "text"})
    assert result.files and result.files[0]["mediaSource"] == "inline"
    assert not result.spooled


@pytest.mark.asyncio
async def test_unsupported_modality_is_spooled_not_dropped(tmp_path):
    connector = FakeConnector(b"wav-bytes")
    ingest = _ingest(tmp_path, connector)
    att = Attachment(kind="audio", name="voice.amr", handle={"url": "x"})
    result = await ingest.ingest("ses_1", [att], model_inputs={"image", "text"})
    assert result.spooled, "unsupported media must be spooled, not dropped"
    spooled = await asyncio.to_thread(Path(result.spooled[0]).read_bytes)
    assert spooled == b"wav-bytes"
    assert any("not supported by the model" in note for note in result.notes)


@pytest.mark.asyncio
async def test_oversized_attachment_skipped_before_download(tmp_path):
    connector = FakeConnector(b"x")
    ingest = _ingest(tmp_path, connector)
    att = Attachment(
        kind="video", name="big.mp4", size=Config().media.max_bytes + 1, handle={"url": "x"}
    )
    result = await ingest.ingest("ses_1", [att], model_inputs={"image", "text"})
    assert connector.downloads == 0, "must not download media we will reject"
    assert any("exceeds the size limit" in note for note in result.notes)


@pytest.mark.asyncio
async def test_download_failure_is_reported(tmp_path):
    ingest = _ingest(tmp_path, FakeConnector(b"", fail=True))
    att = Attachment(kind="image", name="a.png", handle={"url": "x"})
    result = await ingest.ingest("ses_1", [att], model_inputs={"image", "text"})
    assert not result.files and not result.spooled
    assert any("Failed to download" in note for note in result.notes)


@pytest.mark.asyncio
async def test_spool_failure_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "blocker"
    await asyncio.to_thread(blocker.write_text, "x")
    config = Config()
    config.media.spool_dir = str(blocker / "sub")
    ingest = MediaIngest(
        config, FakeConnector(b"wav"), FakeAgentClient(), working_dir=str(tmp_path)
    )
    att = Attachment(kind="audio", name="v.amr", handle={"url": "x"})
    result = await ingest.ingest("ses_1", [att], model_inputs={"image", "text"})
    assert not result.spooled
    assert any("Could not save" in note for note in result.notes)
