"""Interpret the agent's weakly-typed usage map for the fields the bridge shows.

agentd passes the provider's usage through verbatim, keyed by provider name, and
does not normalize it (provider field names differ). So each model's format has
to be understood here; an unrecognized provider falls back to the normalized
fields agentd also happens to send.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class UsageTokens:
    """One step's usage, reduced to the counters the usage line needs."""

    full_input: int = 0  # prompt tokens actually sent == session context used
    output: int = 0  # total output tokens (includes reasoning)
    reasoning: int = 0
    cache_read: int = 0
    cache_write: int = 0

    @property
    def new_input(self) -> int:
        """Input tokens not served from cache (the "new" part of a call)."""
        return max(0, self.full_input - self.cache_read - self.cache_write)

    @property
    def visible_output(self) -> int:
        return max(0, self.output - self.reasoning)

    @classmethod
    def from_normalized(cls, tokens: dict[str, Any]) -> UsageTokens:
        """Fallback: agentd's normalized fields (input=non-cached, output=visible)."""
        cache = tokens.get("cache")
        read = _nested(cache, "read")
        write = _nested(cache, "write")
        reasoning = _nested(tokens, "reasoning")
        visible = _nested(tokens, "output")
        new_input = _nested(tokens, "input")

        return cls(
            full_input=new_input + read + write,
            output=visible + reasoning,
            reasoning=reasoning,
            cache_read=read,
            cache_write=write,
        )


def parse_usage(metadata: Any) -> UsageTokens | None:
    """Read the provider's raw usage map (``{provider: {...}}``) into counters.

    Returns ``None`` when the map is empty or no provider is recognized, so the
    caller can fall back to the normalized fields.
    """
    if not isinstance(metadata, dict):
        return None

    for provider, raw in metadata.items():
        if not isinstance(raw, dict):
            continue
        parsed = _parse_provider(str(provider).lower(), raw)
        if parsed is not None:
            return parsed

    return None


def _parse_provider(provider: str, raw: dict[str, Any]) -> UsageTokens | None:
    if provider in _OPENAI:
        return _openai(raw)

    if provider in _ANTHROPIC:
        return _anthropic(raw)

    if provider in _GOOGLE:
        return _google(raw)

    if provider in _BEDROCK:
        return _bedrock(raw)

    return None


_OPENAI = {"openai", "openai-compatible", "openai-compatible-chat", "openai-compatible-responses"}
_ANTHROPIC = {"anthropic", "anthropic-messages"}
_GOOGLE = {"google", "gemini", "google-generative-ai", "google-vertex"}
_BEDROCK = {"bedrock", "amazon-bedrock", "aws-bedrock", "bedrock-converse"}


def _openai(raw: dict[str, Any]) -> UsageTokens | None:
    # Chat Completions style. DeepSeek extends it with explicit cache buckets
    # (prompt_cache_hit_tokens / prompt_cache_miss_tokens); prefer those and only
    # fall back to the generic prompt_tokens_details.cached_tokens shape.
    if "prompt_tokens" in raw or "completion_tokens" in raw:
        full = _nested(raw, "prompt_tokens")
        hit = _nested(raw, "prompt_cache_hit_tokens")
        miss = _nested(raw, "prompt_cache_miss_tokens")

        if hit == 0 and miss == 0:
            hit = _nested(raw, "prompt_tokens_details", "cached_tokens")
            miss = full - hit

        return UsageTokens(
            full_input=full or (hit + miss),
            output=_nested(raw, "completion_tokens"),
            reasoning=_nested(raw, "completion_tokens_details", "reasoning_tokens"),
            cache_read=hit,
        )

    # Responses style (input_tokens/output_tokens).
    if "input_tokens" in raw:
        return UsageTokens(
            full_input=_nested(raw, "input_tokens"),
            output=_nested(raw, "output_tokens"),
            reasoning=_nested(raw, "output_tokens_details", "reasoning_tokens"),
            cache_read=_nested(raw, "input_tokens_details", "cached_tokens"),
        )

    return None


def _anthropic(raw: dict[str, Any]) -> UsageTokens | None:
    if "input_tokens" not in raw and "output_tokens" not in raw:
        return None

    cache_read = _nested(raw, "cache_read_input_tokens")
    cache_write = _nested(raw, "cache_creation_input_tokens")
    # Anthropic's input_tokens excludes cache; the full prompt adds both back.
    new_input = _nested(raw, "input_tokens")

    return UsageTokens(
        full_input=new_input + cache_read + cache_write,
        output=_nested(raw, "output_tokens"),
        cache_read=cache_read,
        cache_write=cache_write,
    )


def _google(raw: dict[str, Any]) -> UsageTokens | None:
    if "promptTokenCount" not in raw and "candidatesTokenCount" not in raw:
        return None

    # Gemini's promptTokenCount is the whole prompt (cached included).
    return UsageTokens(
        full_input=_nested(raw, "promptTokenCount"),
        output=_nested(raw, "candidatesTokenCount"),
        reasoning=_nested(raw, "thoughtsTokenCount"),
        cache_read=_nested(raw, "cachedContentTokenCount"),
    )


def _bedrock(raw: dict[str, Any]) -> UsageTokens | None:
    if "inputTokens" not in raw and "outputTokens" not in raw:
        return None

    # Bedrock's inputTokens is the whole prompt (cache included).
    return UsageTokens(
        full_input=_nested(raw, "inputTokens"),
        output=_nested(raw, "outputTokens"),
        cache_read=_nested(raw, "cacheReadInputTokens"),
        cache_write=_nested(raw, "cacheWriteInputTokens"),
    )


def _nested(obj: Any, *keys: str) -> int:
    for key in keys:
        if not isinstance(obj, dict):
            return 0
        obj = obj.get(key)

    if isinstance(obj, bool) or obj is None:
        return 0

    try:
        return int(obj)
    except (TypeError, ValueError):
        return 0
