from __future__ import annotations

import pytest
from pydantic import ValidationError

from tether.config import Config, validate_startup
from tether.models import Conversation


def _wechat(**kwargs):
    return Config.model_validate(
        {
            "channels": {
                "feishu": {"enabled": True},
                "wechat": {"enabled": True, **kwargs},
            }
        }
    )


def _bot(bot_id="assistant", **kwargs):
    return {
        "id": bot_id,
        "identity": {"display_name": f"Bot {bot_id}"},
        "login_via": [{"channel": "feishu", "user": f"user-{bot_id}"}],
        **kwargs,
    }


def test_bot_specs():
    config = _wechat(
        bots=[
            _bot("assistant"),
            _bot("ops", enabled=False),
        ]
    )
    specs = config.channels.wechat.bot_specs()
    assert [s.id for s in specs] == ["assistant", "ops"]
    assert specs[0].instance_id == "wechat@assistant"
    validate_startup(config)


def test_enabled_channel_requires_at_least_one_bot():
    config = _wechat(bots=[])
    with pytest.raises(ValueError):
        validate_startup(config)


def test_bot_id_charset_is_enforced():
    with pytest.raises(ValidationError):
        _wechat(bots=[_bot("Bad/Id")])


def test_bot_display_name_is_required():
    config = _wechat(bots=[{"id": "assistant"}])
    with pytest.raises(ValueError):
        validate_startup(config)


def test_duplicate_bot_ids_are_rejected():
    config = _wechat(bots=[_bot("a"), _bot("a")])
    with pytest.raises(ValueError):
        validate_startup(config)


def test_login_via_must_map_to_one_bot():
    via = [{"channel": "wecom", "user": "T1"}]
    config = _wechat(
        bots=[
            _bot("a", login_via=via),
            _bot("b", login_via=via),
        ]
    )
    with pytest.raises(ValueError):
        validate_startup(config)


def test_login_via_can_have_multiple_entries_per_bot():
    config = _wechat(
        bots=[
            _bot(
                "assistant",
                login_via=[
                    {"channel": "wecom", "user": "T1"},
                    {"channel": "feishu", "user": "ou_1"},
                ],
            )
        ]
    )
    validate_startup(config)
    bot = config.channels.wechat.bot_for_login("wecom", "T1")
    assert bot is not None and bot.id == "assistant"
    assert config.channels.wechat.bot_for_login("qq", "T1") is None


def test_conversation_key_includes_account_and_keeps_legacy_shape():
    legacy = Conversation(channel="wechat", kind="direct", id="u1")
    assert legacy.key == "wechat:direct:None:u1:None"
    account = Conversation(channel="wechat", kind="direct", id="u1", account="assistant")
    assert account.key == "wechat@assistant:direct:None:u1:None"


def test_bot_identity_is_resolved_per_bot():
    config = _wechat(
        bots=[
            _bot("assistant", identity={"display_name": "小助手", "description": "d"}),
            _bot("ops"),
        ]
    )
    assistant = config.channels.wechat.account_identity("assistant")
    assert assistant.display_name == "小助手"
    assert config.channels.wechat.account_identity("missing").display_name is None


def test_admins_wechat_keys_must_match_bot_ids():
    config = Config.model_validate(
        {
            "channels": {"wechat": {"enabled": True, "bots": [_bot("assistant")]}},
            "access": {"admins": {"wechat": {"missing": ["u1"]}}},
        }
    )
    with pytest.raises(ValueError):
        validate_startup(config)


@pytest.mark.asyncio
async def test_route_store_round_trips_account(tmp_path):
    from tether.models import Route
    from tether.store.sqlite import RouteStore

    store = RouteStore(tmp_path / "routes.sqlite3")
    await store.connect()
    route = Route(
        conversation=Conversation(
            channel="wechat", kind="direct", id="u1", account="assistant"
        ),
        session_id="ses_1",
        server_base="http://agentd",
        agent="build",
    )
    await store.put(route)
    loaded = await store.get(route.key)
    assert loaded is not None
    assert loaded.conversation.account == "assistant"
    assert loaded.key == "wechat@assistant:direct:None:u1:None"
    await store.close()


@pytest.mark.asyncio
async def test_wechat_runtime_state_and_unbind(tmp_path):
    from tether.store.sqlite import RouteStore

    store = RouteStore(tmp_path / "routes.sqlite3")
    await store.connect()
    await store.save_wechat_login("assistant", "bot-1", "tok", "https://api", "user")
    await store.save_wechat_cursor("assistant", "cursor-1")
    await store.save_wechat_context_token("assistant", "peer-1", "ctx-1")
    cursor, tokens = await store.wechat_state("assistant")
    assert cursor == "cursor-1"
    assert tokens == {"peer-1": "ctx-1"}
    assert await store.wechat_account("assistant") is not None
    await store.unbind_wechat("assistant")
    assert await store.wechat_account("assistant") is None
    assert await store.wechat_state("assistant") == ("", {})
    await store.close()


def test_bot_requires_login_via():
    config = _wechat(bots=[_bot("assistant", login_via=[])])
    with pytest.raises(ValueError):
        validate_startup(config)


def test_login_via_needs_an_enabled_channel():
    config = Config.model_validate(
        {
            "channels": {
                "wechat": {
                    "enabled": True,
                    "bots": [
                        {
                            "id": "assistant",
                            "identity": {"display_name": "A"},
                            "login_via": [{"channel": "wecom", "user": "u"}],
                        }
                    ],
                }
            }
        }
    )
    with pytest.raises(ValueError):
        validate_startup(config)
