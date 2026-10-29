"""OpenCode Model.Ref parsing and formatting helpers."""

from __future__ import annotations

from typing import Any


def parse_model_ref(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)

    provider_end = value.find("/")
    if provider_end <= 0:
        raise ValueError(f"invalid model reference: {value!r}")

    variant_start = value.find("#", provider_end + 1)
    model_id = value[provider_end + 1 : variant_start if variant_start != -1 else None]
    variant = value[variant_start + 1 :] if variant_start != -1 else None
    if not model_id or "#" in value[:provider_end] or (variant is not None and not variant):
        raise ValueError(f"invalid model reference: {value!r}")

    ref: dict[str, Any] = {"providerID": value[:provider_end], "id": model_id}
    if variant:
        ref["variant"] = variant
    return ref


def format_model_ref(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return str(value)

    provider = value.get("providerID") or value.get("provider_id") or ""
    model = value.get("id") or value.get("modelID") or value.get("model_id") or ""
    if not provider or not model:
        return str(model or provider or "") or None

    variant = value.get("variant")
    return f"{provider}/{model}" + (f"#{variant}" if variant else "")


def model_context_key(model_id: str) -> str:
    """Model.Info is keyed by provider/id; variants only select behaviour."""
    return model_id.split("#", 1)[0]
