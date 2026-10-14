"""Decide whether a file may be delivered outbound, from ordered glob rules.

Patterns are matched against a file's **resolved absolute path** (never the
basename), gitignore-style: a leading ``!`` negates, later matches win, and the
``{working_dir}`` placeholder expands to a conversation's project root.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

_WORKING_DIR = "{working_dir}"


def resolve_under(path: str, working_dir: str | None) -> Path:
    """Resolve ``path`` against ``working_dir`` (an absolute ``path`` wins).

    Collapses ``..`` and follows symlinks, producing the value the policy is
    matched against — so an escape cannot slip past an allow-list.
    """
    return Path(os.path.realpath(Path(working_dir or ".") / Path(path).expanduser()))


def compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate a glob ``pattern`` into an anchored regular expression.

    ``**`` crosses ``/`` (``**/`` may appear anywhere), ``*`` and ``?`` stay within
    one path segment, ``[...]`` is a character class, and a trailing ``/`` means the
    directory and its contents. A leading ``!`` is handled by :class:`PathPolicy`,
    not here.
    """
    if pattern.endswith("/"):
        pattern += "**"
    out: list[str] = ["^"]
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
            elif pattern.startswith("**", i):
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(char))
                i += 1
            else:
                body = pattern[i + 1 : end]
                out.append(f"[{'^' + body[1:] if body.startswith('!') else body}]")
                i = end + 1
        else:
            out.append(re.escape(char))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def compile_rules(
    patterns: Iterable[str], working_dir: str | None
) -> list[tuple[bool, re.Pattern[str]]]:
    """Compile ``patterns`` into ``(negate, regex)`` rules for one ``working_dir``.

    Expands ``{working_dir}`` to the resolved root so a rule can be anchored inside
    the project; rules without it are independent of the conversation.
    """
    root = str(Path(working_dir or ".").resolve())
    rules: list[tuple[bool, re.Pattern[str]]] = []
    for raw in patterns:
        if not raw:
            continue
        negate = raw.startswith("!")
        body = raw[1:] if negate else raw
        rules.append((negate, compile_glob(body.replace(_WORKING_DIR, root))))
    return rules


class PathPolicy:
    """Ordered allow/deny glob rules evaluated against resolved absolute paths."""

    def __init__(self, patterns: Iterable[str]) -> None:
        self._patterns = list(patterns)
        self._cache: dict[str | None, list[tuple[bool, re.Pattern[str]]]] = {}

    def allowed(self, path: str | Path, *, working_dir: str | None) -> bool:
        """Whether ``path`` is allowed; default-deny, last matching rule wins."""
        real = str(Path(path).resolve())
        allowed = False
        for negate, regex in self._rules(working_dir):
            if regex.match(real):
                allowed = not negate
        return allowed

    def _rules(self, working_dir: str | None) -> list[tuple[bool, re.Pattern[str]]]:
        rules = self._cache.get(working_dir)
        if rules is None:
            rules = compile_rules(self._patterns, working_dir)
            self._cache[working_dir] = rules
        return rules
