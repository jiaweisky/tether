from __future__ import annotations

import pytest

from tether.config import ChannelIdentity, WeChatBotSpec
from tether.connectors.wechat.login import (
    LoginSession,
    WeChatLoginError,
    WeChatLoginRejected,
    WeChatLoginService,
    WeChatQRExpired,
)
from tether.store.sqlite import (
    RouteStore,
    WeChatBindingConflict,
    WeChatRebindRequired,
)


def _spec(bot_id="a") -> WeChatBotSpec:
    return WeChatBotSpec(
        id=bot_id,
        enabled=True,
        identity=ChannelIdentity(display_name=f"Bot {bot_id}"),
    )


async def _store(tmp_path) -> RouteStore:
    store = RouteStore(tmp_path / "routes.sqlite3")
    await store.connect()
    return store


@pytest.mark.asyncio
async def test_new_and_same_id_bindings_are_allowed(tmp_path):
    store = await _store(tmp_path)
    await store.save_wechat_login("a", "bot-a", "tok", "https://api", None)
    await store.save_wechat_login("a", "bot-a", "tok2", "https://api", None)
    assert await store.wechat_binding("a") == "bot-a"
    await store.close()


@pytest.mark.asyncio
async def test_duplicate_platform_id_on_another_bot_is_rejected(tmp_path):
    store = await _store(tmp_path)
    await store.save_wechat_login("a", "bot-a", "tok", "https://api", None)
    with pytest.raises(WeChatBindingConflict):
        await store.save_wechat_login("b", "bot-a", "tok", "https://api", None)
    await store.close()


@pytest.mark.asyncio
async def test_different_bound_id_requires_an_explicit_clear(tmp_path):
    store = await _store(tmp_path)
    await store.save_wechat_login("a", "bot-a", "tok", "https://api", None)
    with pytest.raises(WeChatRebindRequired):
        await store.save_wechat_login("a", "bot-b", "tok", "https://api", None)
    await store.close()


@pytest.mark.asyncio
async def test_confirmed_persists_credential_and_binding(tmp_path):
    store = await _store(tmp_path)
    service = WeChatLoginService(store=store, channel_enabled=True)
    spec = _spec()
    credential = await service._confirmed(
        spec,
        {
            "ilink_bot_id": "bot-x",
            "bot_token": "token-x",
            "baseurl": "https://api.example",
            "ilink_user_id": "user-x",
        },
    )
    assert credential.bot_id == "bot-x"
    account = await store.wechat_account("a")
    assert account is not None
    assert account["ilink_bot_id"] == "bot-x"
    assert account["token"] == "token-x"
    assert account["user_id"] == "user-x"
    await store.close()


@pytest.mark.asyncio
async def test_confirmed_rejection_is_mapped(tmp_path):
    store = await _store(tmp_path)
    await store.save_wechat_login("a", "bot-a", "tok", "https://api", None)
    service = WeChatLoginService(store=store, channel_enabled=True)
    with pytest.raises(WeChatLoginRejected) as info:
        await service._confirmed(
            _spec(),
            {
                "ilink_bot_id": "bot-b",
                "bot_token": "token-b",
                "baseurl": "https://api.example",
            },
        )
    assert "already bound" in info.value.reason
    await store.close()


@pytest.mark.asyncio
async def test_channel_must_be_enabled(tmp_path):
    store = await _store(tmp_path)
    service = WeChatLoginService(store=store, channel_enabled=False)
    with pytest.raises(WeChatLoginError):
        service._ensure_channel_enabled()
    await store.close()


class FakeLoginClient:
    def __init__(self, statuses, *, refresh=None):
        self.statuses = list(statuses)
        self.refresh = refresh or {"qrcode": "q2", "qrcode_img_content": "content-2"}
        self.closed = False

    async def poll_qr(self, qrcode, *, verify_code=None, base_url=None):
        return self.statuses.pop(0)

    async def get_qr(self):
        return self.refresh

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_wait_confirms_and_persists(tmp_path):
    store = await _store(tmp_path)
    service = WeChatLoginService(store=store, channel_enabled=True)
    spec = _spec()
    client = FakeLoginClient(
        [
            {"status": "wait"},
            {
                "status": "confirmed",
                "ilink_bot_id": "bot-1",
                "bot_token": "token-1",
                "baseurl": "https://api.example",
            },
        ]
    )
    session = LoginSession(client=client, bot=spec, qrcode="q1", content="content-1")
    credential = await service.wait(session, timeout_s=3)
    assert credential.bot_id == "bot-1"
    assert client.closed
    assert await store.wechat_binding("a") == "bot-1"
    await store.close()


@pytest.mark.asyncio
async def test_wait_stops_when_the_qr_expires(tmp_path):
    store = await _store(tmp_path)
    service = WeChatLoginService(store=store, channel_enabled=True)
    spec = _spec()
    client = FakeLoginClient(
        [
            {"status": "wait"},
            {"status": "expired"},
            {
                "status": "confirmed",
                "ilink_bot_id": "bot-2",
                "bot_token": "token-2",
                "baseurl": "https://api.example",
            },
        ]
    )
    session = LoginSession(client=client, bot=spec, qrcode="q1", content="content-1")

    with pytest.raises(WeChatQRExpired):
        await service.wait(session, timeout_s=3)
    assert client.closed
    assert client.statuses
    await store.close()
