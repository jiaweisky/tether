"""Parse the small set of in-chat commands the bridge handles itself.

The commands are ``/stop`` (interrupt the running turn), ``/new`` (start a fresh
agent session), ``/whoami`` (report the sender's id), ``/status`` (report a
snapshot of the conversation) and ``/help`` (list the commands). A command is
intercepted locally and never forwarded to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CommandKind = Literal["stop", "new", "whoami", "status", "send", "help"]


@dataclass(frozen=True)
class CommandSpec:
    """A self-handled command: its word, optional argument syntax and purpose."""

    name: CommandKind
    description: str
    usage: str = ""


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("stop", "Interrupt the turn that is currently running."),
    CommandSpec("new", "Start a fresh agent session (admins only)."),
    CommandSpec("whoami", "Show your sender id and this conversation."),
    CommandSpec("status", "Show a snapshot of the conversation and the bridge."),
    CommandSpec(
        "send", "Send a file from the project to this conversation.", usage="<path>"
    ),
    CommandSpec("help", "List the available commands."),
)
_SPECS: dict[str, CommandSpec] = {spec.name: spec for spec in COMMANDS}


def help_text(prefix: str = "/") -> str:
    """Render the command list shown by ``/help``: name, usage and description."""
    lines = [f"📖 Commands (prefix `{prefix}`)"]
    for spec in COMMANDS:
        form = f"{prefix}{spec.name}"
        if spec.usage:
            form += f" {spec.usage}"
        lines.append(f"`{form}` — {spec.description}")
    lines.append(f"In a group, mention the bot first (e.g. `@bot {prefix}stop`).")
    return "\n".join(lines)


@dataclass
class Command:
    kind: CommandKind
    args: str = ""


def parse_command(text: str, prefix: str = "/") -> Command | None:
    """Return the command encoded in ``text``, or ``None`` for plain messages.

    An argument-less command matches only when it appears *exactly* (``/stop`` is a
    command; ``/stop now`` and ``/status of build`` are plain messages). A command
    that declares ``usage`` also accepts trailing text as its argument (``/send
    <path>``; ``/send`` alone is not a command).
    """
    stripped = _strip_leading_mentions(text.strip())
    if not stripped.startswith(prefix):
        return None
    body = stripped[len(prefix) :].strip()
    parts = body.split(maxsplit=1)
    spec = _SPECS.get(parts[0].lower()) if parts else None
    if spec is None:
        return None
    tail = parts[1].strip() if len(parts) > 1 else ""
    if spec.usage:
        if not tail:
            return None
        return Command(kind=spec.name, args=tail)
    if tail:
        return None
    return Command(kind=spec.name)


def unescape_command(text: str, prefix: str = "/") -> tuple[str, bool]:
    """Collapse a doubled prefix so a command word can be sent as plain text.

    Only an escaped *command* is collapsed: ``//help`` is delivered as ``/help``,
    while ``// TODO`` and ``//server`` are forwarded untouched. Returns the text
    to forward and whether an escape was found; when ``False`` the text is
    returned untouched.
    """
    if not prefix:
        return text, False
    stripped = text.strip()
    body = _strip_leading_mentions(stripped)
    if not body.startswith(prefix + prefix):
        return text, False
    if parse_command(body[len(prefix) :], prefix) is None:
        return text, False
    mentions = stripped[: len(stripped) - len(body)]
    return mentions + body[len(prefix) :], True


def _strip_leading_mentions(text: str) -> str:
    """Drop leading ``@mention`` tokens.

    A group message is delivered with the bot mention kept in the text (WeCom
    ``@Bot /stop``, Feishu ``@_user_1 /stop``), which would otherwise hide a
    command. Used only to *detect* a command or an escape — the original text is
    still what is forwarded otherwise.
    """
    while text.startswith("@"):
        parts = text.split(maxsplit=1)
        text = parts[1].lstrip() if len(parts) > 1 else ""
    return text
