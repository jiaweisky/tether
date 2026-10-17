from __future__ import annotations

import asyncio
import base64
import os

import pytest

from tether.config import ChannelIdentity, Config, WeChatBotSpec
from tether.connector import build_connectors
from tether.connectors.wechat.client import encrypt_ecb
from tether.connectors.wechat.connector import WeChatConnector
from tether.connectors.wechat.storage import WeChatCredential
from tether.models import (
    Conversation,
    MediaSegment,
    OutboundPlan,
    RichMedia,
    TextSegment,
)
from tether.store.sqlite import RouteStore


class FakeAPI:
    def __init__(self, credential: WeChatCredential) -> None:
        self.credential = credential
        self.updates: list[dict] = []
        self.sent: list[dict] = []
        self.upload_url_requests: list[dict] = []
        self.uploaded: bytes | None = None
        self.download_payload: bytes | None = None
        self.typing: list[tuple[str, str, int]] = []
        self.started = False
        self.stopped = False

    async def get_qr(self, *, local_tokens=None):
        return {"qrcode": "q", "qrcode_img_content": "content"}

    async def poll_qr(self, *args, **kwargs):
        return {"status": "wait"}

    async def get_updates(self, cursor="", *, timeout_s=35.0):
        if self.updates:
            return self.updates.pop(0)
        await asyncio.sleep(0.02)
        return {"ret": 0, "msgs": [], "get_updates_buf": cursor or "cursor"}

    async def send_message(self, msg):
        self.sent.append(msg)
        return {"ret": 0, "message_id": f"srv-{len(self.sent)}"}

    async def get_upload_url(self, payload):
        self.upload_url_requests.append(payload)
        return {"upload_full_url": "https://cdn.example/upload"}

    async def upload_cdn(self, url, ciphertext):
        self.uploaded = ciphertext
        return "download-param"

    async def download_cdn(self, url):
        if self.download_payload is None:
            raise AssertionError("no download payload")
        return self.download_payload

    async def get_config(self, user_id, context_token):
        return {"typing_ticket": "ticket"}

    async def send_typing(self, user_id, typing_ticket, *, status=1):
        self.typing.append((user_id, typing_ticket, status))

    async def notify_start(self):
        self.started = True

    async def notify_stop(self):
        self.stopped = True

    async def close(self):
        return None


async def _store(tmp_path) -> RouteStore:
    store = RouteStore(tmp_path / "routes.sqlite3")
    await store.connect()
    return store


async def _bound_store(tmp_path, *, bot_id="bot-a") -> RouteStore:
    store = await _store(tmp_path)
    await store.save_wechat_login("assistant", bot_id, "tok", "https://api.example", None)
    return store


def _emitter(queue: asyncio.Queue):
    async def emit(item):
        queue.put_nowait(item)

    return emit


def _connector(tmp_path, store, *, account="assistant", api_factory=None, enabled=True):
    spec = WeChatBotSpec(
        id=account,
        enabled=enabled,
        identity=ChannelIdentity(display_name=f"Bot {account}"),
    )
    return WeChatConnector(
        spec=spec,
        channel_enabled=True,
        store=store,
        api_factory=api_factory,
    )


@pytest.mark.asyncio
async def test_inbound_text_and_account_scoped_conversation(tmp_path):
    store = await _bound_store(tmp_path)
    apis: list[FakeAPI] = []

    def factory(cred):
        api = FakeAPI(cred)
        api.updates.append(
            {
                "ret": 0,
                "get_updates_buf": "c1",
                "msgs": [
                    {
                        "message_id": "m1",
                        "from_user_id": "u1",
                        "message_type": 1,
                        "context_token": "ctx",
                        "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
                    }
                ],
            }
        )
        apis.append(api)
        return api

    connector = _connector(tmp_path, store, api_factory=factory)
    items = asyncio.Queue()
    await connector.start(_emitter(items))
    item = await asyncio.wait_for(items.get(), timeout=2)
    assert item.text == "hello"
    assert item.conversation.key == "wechat@assistant:direct:None:u1:None"
    assert item.conversation.account == "assistant"
    await connector.stop()

    await connector.start(_emitter(items))
    conv = Conversation(channel="wechat", kind="direct", id="u1", account="assistant")
    await connector.send(conv, OutboundPlan(segments=[TextSegment(text="hi")]))
    sent = apis[-1].sent[-1]
    assert sent["to_user_id"] == "u1"
    assert sent["context_token"] == "ctx"
    assert sent["item_list"][0]["text_item"]["text"] == "hi"
    await connector.stop()
    await store.close()


@pytest.mark.asyncio
async def test_inbound_image_is_decrypted_on_download(tmp_path):
    key = os.urandom(16)
    store = await _bound_store(tmp_path)
    apis: list[FakeAPI] = []

    def factory(cred):
        api = FakeAPI(cred)
        api.download_payload = encrypt_ecb(b"image-bytes", key)
        api.updates.append(
            {
                "ret": 0,
                "msgs": [
                    {
                        "message_id": "m2",
                        "from_user_id": "u2",
                        "message_type": 1,
                        "item_list": [
                            {
                                "type": 2,
                                "image_item": {
                                    "media": {
                                        "encrypt_query_param": "param",
                                        "aes_key": base64.b64encode(key).decode(),
                                    },
                                    "mid_size": 11,
                                },
                            }
                        ],
                    }
                ],
            }
        )
        apis.append(api)
        return api

    connector = _connector(tmp_path, store, api_factory=factory)
    items = asyncio.Queue()
    await connector.start(_emitter(items))
    item = await asyncio.wait_for(items.get(), timeout=2)
    assert len(item.attachments) == 1
    media = await connector.download(item.attachments[0])
    assert media.data == b"image-bytes"
    await connector.stop()
    await store.close()


@pytest.mark.asyncio
async def test_outbound_media_uploads_and_sends_image_item(tmp_path):
    store = await _bound_store(tmp_path)
    apis: list[FakeAPI] = []

    def factory(cred):
        api = FakeAPI(cred)
        apis.append(api)
        return api

    connector = _connector(tmp_path, store, api_factory=factory)
    await connector.start(_emitter(asyncio.Queue()))
    conv = Conversation(channel="wechat", kind="direct", id="u1", account="assistant")
    await connector.send(
        conv,
        OutboundPlan(
            segments=[
                MediaSegment(
                    media=RichMedia(
                        kind="image", data=b"raw", mime="image/png", name="x.png"
                    )
                )
            ]
        ),
    )
    api = apis[-1]
    assert api.upload_url_requests[0]["media_type"] == 1
    assert api.uploaded is not None and api.uploaded != b"raw"
    item = api.sent[-1]["item_list"][0]
    assert item["type"] == 2
    assert item["image_item"]["media"]["encrypt_query_param"] == "download-param"
    assert item["image_item"]["media"]["aes_key"]
    await connector.stop()
    await store.close()


@pytest.mark.asyncio
async def test_build_connectors_creates_one_instance_per_bot(tmp_path):
    config = Config.model_validate(
        {
            "channels": {
                "wechat": {
                    "enabled": True,
                    "bots": [
                        {"id": "a", "identity": {"display_name": "A"}},
                        {"id": "b", "identity": {"display_name": "B"}},
                    ],
                }
            }
        }
    )
    store = await _store(tmp_path)
    connectors = build_connectors(config, store=store)
    assert [c.instance_id for c in connectors] == ["wechat@a", "wechat@b"]
    await store.close()


@pytest.mark.asyncio
async def test_disabled_bot_does_not_start_polling(tmp_path):
    store = await _bound_store(tmp_path)
    apis: list[FakeAPI] = []

    def factory(cred):
        api = FakeAPI(cred)
        apis.append(api)
        return api

    connector = _connector(tmp_path, store, api_factory=factory, enabled=False)
    await connector.start(_emitter(asyncio.Queue()))
    assert connector.state == "disabled"
    assert connector.connected is None
    assert not apis
    await connector.stop()
    await store.close()


@pytest.mark.asyncio
async def test_concurrent_login_for_same_bot_is_refused(tmp_path):
    from tether.connectors.wechat.login import WeChatLoginError

    store = await _bound_store(tmp_path)
    connector = _connector(tmp_path, store, api_factory=lambda cred: FakeAPI(cred))
    await connector._login_lock.acquire()
    try:
        with pytest.raises(WeChatLoginError):
            await connector.login()
    finally:
        connector._login_lock.release()
    await store.close()
