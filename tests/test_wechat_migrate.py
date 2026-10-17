from __future__ import annotations

import json

import pytest

from tether.config import Config
from tether.connectors.wechat import migrate as migrate_module
from tether.connectors.wechat.migrate import migrate_legacy_wechat_files
from tether.store.sqlite import RouteStore


@pytest.mark.asyncio
async def test_imports_and_removes_legacy_json(tmp_path, monkeypatch):
    legacy = tmp_path / "wechat"
    legacy.mkdir()
    monkeypatch.setattr(migrate_module, "_LEGACY_DIR", str(legacy))
    cred_path = legacy / "assistant.json"
    state_path = legacy / "assistant.json.state.json"
    cred_path.write_text(
        json.dumps(
            {
                "token": "tok",
                "baseUrl": "https://api.example",
                "botId": "bot-1",
                "userId": "user-1",
            }
        )
    )
    state_path.write_text(
        json.dumps(
            {
                "cursor": "cursor-1",
                "context_tokens": {"peer-1": "ctx-1"},
            }
        )
    )
    config = Config.model_validate(
        {
            "channels": {
                "wechat": {
                    "enabled": True,
                    "bots": [
                        {
                            "id": "assistant",
                            "identity": {"display_name": "小助手"},
                            "login_via": [{"channel": "wecom", "user": "admin"}],
                        }
                    ],
                }
            }
        }
    )
    store = RouteStore(tmp_path / "routes.sqlite3")
    await store.connect()
    await migrate_legacy_wechat_files(config, store)

    account = await store.wechat_account("assistant")
    assert account is not None
    assert account["token"] == "tok"
    assert account["ilink_bot_id"] == "bot-1"
    assert await store.wechat_state("assistant") == ("cursor-1", {"peer-1": "ctx-1"})
    assert not cred_path.exists()
    assert not state_path.exists()
    await store.close()
