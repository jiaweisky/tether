"""The error type raised by the agent client and safe user-facing messages."""

from __future__ import annotations

_ERROR_MESSAGES = {
    "bad_request": "The request was rejected. Please try again.",
    "unauthorized": "The bridge is not authorized to reach the agent service.",
    "forbidden": "This operation is not permitted.",
    "not_found": "The conversation's agent session was not found.",
    "conflict": "The agent is busy; please wait for the current turn to finish.",
    "unavailable": "The agent service is temporarily unavailable. Please retry.",
    "internal": "Internal error, please retry later.",
}


_DETAILED_ERROR_CODES = {"bad_request", "too_large"}


class AgentError(Exception):
    """An error returned by the agent service, carrying its code and status."""

    def __init__(
        self, code: str, message: str = "", *, status: int | None = None, ref: str | None = None
    ) -> None:
        self.code = code
        self.detail = message or None
        self.message = message or _ERROR_MESSAGES.get(code, "Request failed.")
        self.status = status
        self.ref = ref
        super().__init__(f"{code}: {self.message}")


def user_message(
    code: str,
    fallback: str | None = None,
    *,
    detail: str | None = None,
    status: int | None = None,
) -> str:
    """Return a safe, user-facing message for an agent error.

    Request-level 4xx errors carry a concrete reason (for example the body-size
    limit on a 413); surface it so the user can act on it. Well-known bridge
    states keep their stable wording instead of exposing server internals.
    """
    if detail and (
        code in _DETAILED_ERROR_CODES
        or (status is not None and 400 <= status < 500 and code not in _ERROR_MESSAGES)
    ):
        return detail

    if code in _ERROR_MESSAGES:
        return _ERROR_MESSAGES[code]

    return fallback or "Something went wrong. Please retry."
