"""Redacted OpenCode configuration summaries."""

from __future__ import annotations

from typing import Any

from tether.agent.base import BackendDescription, ConfigSummary
from tether.agent.opencode.models import format_model_ref


def describe(
    info: dict[str, Any], *, endpoint_id: str, locations: list[str]
) -> BackendDescription:
    return BackendDescription(
        backend_id="opencode",
        endpoint_id=endpoint_id,
        version=_string_or_none(info.get("version")),
        pid=_int_or_none(info.get("pid")),
        urls=[str(item) for item in (info.get("urls") or info.get("servers") or [])],
        locations=locations,
    )


def summary(entries: Any) -> ConfigSummary:
    documents = entries if isinstance(entries, list) else []
    merged: dict[str, Any] = {}
    for entry in documents:
        if not isinstance(entry, dict) or entry.get("type") != "document":
            continue
        info = entry.get("info")
        if isinstance(info, dict):
            merged.update(info)

    providers = merged.get("providers")
    provider_ids = sorted(str(key) for key in providers) if isinstance(providers, dict) else []
    agents = merged.get("agents")
    models = merged.get("models")

    return ConfigSummary(
        default_agent=_string_or_none(merged.get("default_agent")),
        default_model=format_model_ref(merged.get("model")),
        providers=provider_ids,
        agents=len(agents) if isinstance(agents, dict) else 0,
        models=len(models) if isinstance(models, dict) else 0,
    )


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["describe", "summary"]
