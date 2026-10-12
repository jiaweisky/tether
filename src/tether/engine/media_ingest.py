"""Decide how each inbound attachment reaches the agent.

Small supported media is inlined as a data URL; large media is uploaded to the
provider's file API when available; anything else is spooled into a controlled
directory inside the working directory and referenced by path in the prompt.
The agent is never sent bytes it cannot use, and nothing is dropped silently.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from ..agent.client import AgentClient
from ..agent.errors import AgentError
from ..config import Config, resolve_spool_dir
from ..connector import IMConnector
from ..models import Attachment, normalize_media_kind
from ..util.logging import get_logger
from ..util.media import sniff_mime, spool_path

log = get_logger("tether.media")

_DEFAULT_MODEL_INPUTS = {"image", "text"}


@dataclass
class IngestResult:
    files: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    spooled: list[str] = field(default_factory=list)

    def note_text(self) -> str:
        return "\n".join(self.notes)


class MediaIngest:
    def __init__(
        self,
        config: Config,
        connector: IMConnector,
        client: AgentClient,
        *,
        working_dir: str | None = None,
    ) -> None:
        self.config = config
        self.connector = connector
        self.client = client
        self.working_dir = working_dir

    async def ingest(
        self, sid: str, attachments: list[Attachment], *, model_inputs: set[str] | None = None
    ) -> IngestResult:
        result = IngestResult()
        inputs = model_inputs or _DEFAULT_MODEL_INPUTS
        for attachment in attachments:
            await self._ingest_one(sid, attachment, inputs, result)
        return result

    async def _ingest_one(
        self, sid: str, attachment: Attachment, inputs: set[str], result: IngestResult
    ) -> None:
        kind = normalize_media_kind(attachment.kind)
        label = attachment.name or kind
        if kind not in inputs:
            result.notes.append(
                f"⚠️ Attachment `{label}` dropped: the model does not accept this modality."
            )
            return
        try:
            media = await self.connector.download(attachment)
        except Exception as exc:  # noqa: BLE001 - degrade, never drop silently
            log.warning("media_download_failed", kind=kind, error=str(exc))
            result.notes.append(f"⚠️ Failed to download attachment `{label}`.")
            return
        data = media.data
        if len(data) > self.config.media.max_bytes:
            result.notes.append(f"⚠️ Attachment `{label}` exceeds the size limit and was skipped.")
            return

        mime = sniff_mime(data, attachment.name, media.mime or attachment.mime)
        if len(data) <= self.config.media.inline_limit_bytes:
            result.files.append(_inline_file(data, mime, attachment.name))
            return
        if await self._try_provider_upload(sid, data, mime, attachment.name, result):
            return
        self._spool(attachment, data, result, reason="large media; no upload channel")

    async def _try_provider_upload(
        self, sid: str, data: bytes, mime: str, name: str | None, result: IngestResult
    ) -> bool:
        try:
            uploaded = await self.client.upload_file(sid, data=data, mime=mime, name=name)
        except AgentError as exc:
            log.info("provider_upload_unavailable", error=exc.code)
            return False
        file_id = uploaded.get("fileId") or uploaded.get("id") or uploaded.get("uri")
        if not file_id:
            return False
        result.files.append(
            {
                "uri": str(file_id),
                "mime": mime,
                "name": name,
                "mediaSource": "file",
                "fileId": str(file_id),
            }
        )
        return True

    def _spool(
        self, attachment: Attachment, data: bytes, result: IngestResult, *, reason: str
    ) -> None:
        root = resolve_spool_dir(self.config.media.spool_dir, self.working_dir)
        path = spool_path(root, data, attachment.name)
        path.write_bytes(data)
        result.spooled.append(str(path))
        result.notes.append(f"📎 Attachment saved as `{path}` ({reason}); read it with a tool.")


def _inline_file(data: bytes, mime: str, name: str | None) -> dict[str, Any]:
    uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return {"uri": uri, "mime": mime, "name": name, "mediaSource": "inline"}
