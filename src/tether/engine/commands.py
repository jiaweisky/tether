"""Parse the small set of in-chat commands the bridge handles itself.

The only command is ``/stop``. A command is intercepted locally and never
forwarded to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class Command:
    kind: Literal["stop"]
    args: list[str]


def parse_command(text: str, prefix: str = "/") -> Command | None:
    """Return the command encoded in ``text``, or ``None`` for plain messages."""
    stripped = text.strip()
    if not stripped.startswith(prefix):
        return None
    body = stripped[len(prefix) :].strip()
    if not body:
        return None
    parts = body.split()
    if parts[0].lower() == "stop":
        return Command(kind="stop", args=parts[1:])
    return None
