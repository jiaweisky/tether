"""Parse the small set of in-chat commands the bridge handles itself.

The commands are ``/stop`` (interrupt the running turn) and ``/new`` (start a
fresh agent session for this conversation). A command is intercepted locally
and never forwarded to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class Command:
    kind: Literal["stop", "new", "whoami"]
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
    name = parts[0].lower()
    if name == "stop":
        return Command(kind="stop", args=parts[1:])
    if name == "new":
        return Command(kind="new", args=parts[1:])
    if name == "whoami":
        return Command(kind="whoami", args=parts[1:])
    return None
