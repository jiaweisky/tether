"""Parse the small set of in-chat commands the bridge handles itself.

The commands are ``/stop`` (interrupt the running turn), ``/new`` (start a fresh
agent session), ``/whoami`` (report the sender's id) and ``/status`` (report a
snapshot of the conversation). A command is intercepted locally and never
forwarded to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CommandKind = Literal["stop", "new", "whoami", "status"]
_KINDS: dict[str, CommandKind] = {
    "stop": "stop",
    "new": "new",
    "whoami": "whoami",
    "status": "status",
}


@dataclass
class Command:
    kind: CommandKind


def parse_command(text: str, prefix: str = "/") -> Command | None:
    """Return the command encoded in ``text``, or ``None`` for plain messages."""
    stripped = _strip_leading_mentions(text.strip())
    if not stripped.startswith(prefix):
        return None
    body = stripped[len(prefix) :].strip()
    if not body:
        return None
    kind = _KINDS.get(body.split(maxsplit=1)[0].lower())
    if kind is None:
        return None
    return Command(kind=kind)


def _strip_leading_mentions(text: str) -> str:
    """Drop leading ``@mention`` tokens.

    A group message is delivered with the bot mention kept in the text (WeCom
    ``@Bot /stop``, Feishu ``@_user_1 /stop``), which would otherwise hide a
    command. Only used to detect a command — the original text is still what is
    forwarded when it is not a command.
    """
    while text.startswith("@"):
        parts = text.split(maxsplit=1)
        text = parts[1].lstrip() if len(parts) > 1 else ""
    return text
