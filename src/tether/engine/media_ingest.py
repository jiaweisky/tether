"""Prepare inbound attachments for the agentd prompt.

Tether owns only the connector side: it downloads the bytes and resolves the file
name, and guards against pulling an attachment the platform declares oversized
before the download. The delivery decision — inline, provider file, url,
downsample, spool — is owned by agentd, so every attachment is handed over as a
byte-backed inline file part and agentd applies its ``servers[].media`` policy.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field

from tether.agent.base import PromptFile
from tether.config import Config
from tether.connector import IMConnector
from tether.models import Attachment, MediaBytes, normalize_media_kind
from tether.util.logging import get_logger
from tether.util.media import sniff_mime

log = get_logger("tether.media")


@dataclass
class IngestResult:
    files: list[PromptFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def note_text(self) -> str:
        return "\n".join(self.notes)


class MediaIngest:
    def __init__(self, config: Config, connector: IMConnector) -> None:
        self.config = config
        self.connector = connector

    async def ingest(self, attachments: list[Attachment]) -> IngestResult:
        result = IngestResult()
        for attachment in attachments:
            await self._ingest_one(attachment, result)

        return result

    async def _ingest_one(self, attachment: Attachment, result: IngestResult) -> None:
        """Download one attachment and hand it to agentd as an inline file part."""
        label = attachment.name or normalize_media_kind(attachment.kind)
        limit = self.config.media.max_attachment_bytes
        if limit and attachment.size is not None and attachment.size > limit:
            log.warning("attachment_too_large", name=label, size=attachment.size, limit=limit)
            result.notes.append(
                f"⚠️ Attachment `{label}` is too large to download (limit {limit} bytes)."
            )
            return

        media = await self._download(attachment, label, result)
        if media is None:
            return

        # Some platforms only reveal the file name on download (e.g. via a
        # Content-Disposition header), so prefer it over the message's name.
        name = media.name or attachment.name
        mime = sniff_mime(media.data, name, media.mime or attachment.mime)
        log.info(
            "attachment_ingested",
            name=name,
            mime=mime,
            bytes=len(media.data),
            kind=attachment.kind,
        )

        result.files.append(_inline_file(media.data, mime, name))

    async def _download(
        self, attachment: Attachment, label: str, result: IngestResult
    ) -> MediaBytes | None:
        try:
            return await self.connector.download(attachment)
        except Exception as exc:  # noqa: BLE001 - degrade, never drop silently
            log.warning("media_download_failed", error=str(exc))
            result.notes.append(f"⚠️ Failed to download attachment `{label}`.")
            return None


def _inline_file(data: bytes, mime: str, name: str | None) -> PromptFile:
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return PromptFile(uri=uri, mime=mime, name=name)
