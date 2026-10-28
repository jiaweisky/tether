"""Mask secret-looking fields when rendering a configuration for display."""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEY = re.compile(
    r"token|secret|password|passwd|api[_-]?key|credential|bearer", re.IGNORECASE
)
_MASK = "***"


def redact_secrets(value: Any) -> Any:
    """Recursively replace the value of any secret-named key with ``***``.

    A key is masked when its name matches a sensitive pattern; an empty value is
    left untouched so the dump still distinguishes "unset" from "configured".
    """
    if isinstance(value, dict):
        return {
            key: (_MASK if _is_secret(key, item) else redact_secrets(item))
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [redact_secrets(item) for item in value]

    return value


def _is_secret(key: str, value: Any) -> bool:
    return bool(value) and _SECRET_KEY.search(key) is not None
