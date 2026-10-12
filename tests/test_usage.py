from __future__ import annotations

from tether.agent.usage import UsageTokens, parse_usage

# Captured verbatim from agentd for the three deepseek-flash protocols.
OPENAI_CHAT = {
    "completion_tokens": 17,
    "completion_tokens_details": {"reasoning_tokens": 15},
    "prompt_cache_hit_tokens": 3072,
    "prompt_cache_miss_tokens": 250,
    "prompt_tokens": 3322,
    "prompt_tokens_details": {"cached_tokens": 3072},
    "total_tokens": 3339,
}
OPENAI_RESPONSES = {
    "input_tokens": 3322,
    "input_tokens_details": {"cached_tokens": 3072},
    "output_tokens": 2,
    "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 3324,
}
ANTHROPIC = {
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 128,
    "input_tokens": 3194,
    "output_tokens": 2,
    "service_tier": "standard",
}


def test_openai_chat_usage():
    tokens = parse_usage({"openai": OPENAI_CHAT})
    assert tokens is not None
    assert tokens.full_input == 3322  # context used
    assert tokens.new_input == 250  # 3322 - 3072 cached
    assert tokens.visible_output == 2  # 17 - 15 reasoning
    assert tokens.reasoning == 15
    assert tokens.cache_read == 3072


def test_openai_responses_usage():
    tokens = parse_usage({"openai": OPENAI_RESPONSES})
    assert tokens is not None
    assert tokens.full_input == 3322
    assert tokens.new_input == 250
    assert tokens.visible_output == 2
    assert tokens.cache_read == 3072


def test_anthropic_usage_adds_cache_back():
    tokens = parse_usage({"anthropic": ANTHROPIC})
    assert tokens is not None
    assert tokens.full_input == 3322  # 3194 + 128 + 0
    assert tokens.new_input == 3194  # anthropic input_tokens excludes cache
    assert tokens.visible_output == 2
    assert tokens.cache_read == 128


def test_unknown_provider_returns_none():
    assert parse_usage({"some-new-provider": {"weird": 1}}) is None
    assert parse_usage(None) is None
    assert parse_usage({}) is None


def test_fallback_from_normalized_fields():
    tokens = UsageTokens.from_normalized(
        {"input": 250, "output": 2, "reasoning": 1, "cache": {"read": 3072, "write": 0}}
    )
    assert tokens.full_input == 3322
    assert tokens.new_input == 250
    assert tokens.visible_output == 2
    assert tokens.reasoning == 1


# DeepSeek's extension over openai-chat: explicit hit/miss buckets, no
# prompt_tokens_details. (Mirrors examples/chat/usage.go in go-agent-sdk.)
DEEPSEEK_EXTENDED = {
    "prompt_cache_hit_tokens": 1088,
    "prompt_cache_miss_tokens": 128,
    "prompt_tokens": 1216,
    "completion_tokens": 50,
}


def test_deepseek_extended_cache_fields():
    tokens = parse_usage({"openai": DEEPSEEK_EXTENDED})
    assert tokens is not None
    assert tokens.full_input == 1216  # 1088 + 128
    assert tokens.cache_read == 1088
    assert tokens.new_input == 128  # prompt_cache_miss_tokens
    assert tokens.output == 50
