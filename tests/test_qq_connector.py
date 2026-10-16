from __future__ import annotations

import asyncio

import pytest

from tether.connectors.qq.connector import QQConnector
from tether.connectors.qq.sdk import QQAPIError
from tether.models import (
    Attachment,
    Button,
    Card,
    CardSegment,
    Conversation,
    MediaSegment,
    OutboundPlan,
    RichMedia,
    TextSegment,
)


class FakeQQSDK:
    """A synchronous stand-in for :class:`QQClient` (no network, no thread)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.handlers = None
        self._connected = True

    def start(self, on_event):
        self.handlers = on_event

    def stop(self):
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def post_c2c_message(self, openid, **fields):
        self.calls.append(("c2c", openid, fields))
        return "msg_1"

    def post_group_message(self, group_openid, **fields):
        self.calls.append(("group", group_openid, fields))
        return "msg_1"

    def upload_file(self, *, scope, target_id, file_type, filename=None, data=None, url=None):
        self.calls.append(("upload", scope, target_id, file_type, filename))
        return "file_info_1"

    def put_interaction(self, interaction_id, code=0):
        self.calls.append(("interaction", interaction_id, code))

    def download(self, url):
        return b"bytes"


def connector(sdk: FakeQQSDK) -> QQConnector:
    return QQConnector(appid="app", secret="sec", sdk=sdk)


def _c2c_event(**overrides) -> dict:
    event = {
        "id": "ROBOT1.0_x",
        "author": {"user_openid": "U1", "username": "Alice", "bot": False},
        "content": "hello",
        "message_type": 0,
        "timestamp": "2026-07-21T10:00:00+08:00",
    }
    event.update(overrides)
    return event


def test_inbound_c2c_mapping():
    item = connector(FakeQQSDK())._inbound_message(_c2c_event(), "direct")
    assert item is not None
    assert item.text == "hello"
    assert item.conversation.kind == "direct"
    assert item.conversation.id == "U1"
    assert item.sender.id == "U1"
    assert item.sender.name == "Alice"
    assert item.timestamp > 0


def test_inbound_group_mapping():
    event = {
        "id": "ROBOT1.0_g",
        "author": {"member_openid": "M1", "member_role": "admin", "username": "Bob"},
        "content": "hi there",
        "group_openid": "G1",
        "message_type": 0,
        "mentions": [{"member_openid": "M2", "username": "Carol"}],
    }
    item = connector(FakeQQSDK())._inbound_message(event, "group")
    assert item is not None
    assert item.conversation.kind == "group"
    assert item.conversation.id == "G1"
    assert item.sender.id == "M1"
    assert [m.id for m in item.mentions] == ["M2"]


def test_inbound_voice_uses_transcript():
    event = _c2c_event(
        id="v1",
        content="",
        attachments=[
            {
                "content_type": "voice",
                "url": "https://x/v",
                "voice_wav_url": "https://x/wav",
                "asr_refer_text": "你好",
            }
        ],
    )
    item = connector(FakeQQSDK())._inbound_message(event, "direct")
    assert item is not None
    assert item.text == "你好"
    assert item.attachments == []


def test_inbound_voice_without_transcript_attaches_audio():
    event = _c2c_event(
        id="v2",
        content="",
        attachments=[{"content_type": "voice", "url": "https://x/v"}],
    )
    item = connector(FakeQQSDK())._inbound_message(event, "direct")
    assert item is not None
    assert item.text == ""
    assert item.attachments and item.attachments[0].kind == "voice"
    assert item.attachments[0].handle["url"] == "https://x/v"


def test_inbound_image_attachment_maps_content_type():
    event = _c2c_event(
        id="i1",
        content="look",
        attachments=[
            {
                "content_type": "image/jpeg",
                "url": "https://x/i",
                "filename": "photo.jpg",
                "width": 10,
                "height": 20,
                "size": 123,
            }
        ],
    )
    item = connector(FakeQQSDK())._inbound_message(event, "direct")
    assert item is not None
    att = item.attachments[0]
    assert att.kind == "image"
    assert att.mime == "image/jpeg"
    assert att.name == "photo.jpg"
    assert att.width == 10 and att.height == 20


def test_quoted_message_flattens_elements():
    event = _c2c_event(id="q1", content="", message_type=103)
    event["msg_elements"] = [{"content": "quoted text"}]
    item = connector(FakeQQSDK())._inbound_message(event, "direct")
    assert item is not None
    assert item.text == "quoted text"


def test_interaction_mapping():
    event = {
        "id": "int1",
        "type": 11,
        "scene": "group",
        "chat_type": 1,
        "group_openid": "G1",
        "group_member_openid": "M1",
        "data": {"resolved": {"button_data": '{"kind":"permission","reply":"once"}'}},
    }
    item, interaction_id = connector(FakeQQSDK())._inbound_interaction(event)
    assert item is not None
    assert interaction_id == "int1"
    assert item.value == '{"kind":"permission","reply":"once"}'
    assert item.conversation.kind == "group"
    assert item.conversation.id == "G1"
    assert item.sender.id == "M1"


@pytest.mark.asyncio
async def test_reply_carries_msg_id_and_incrementing_seq():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="group", id="G1")

    await conn.send(conv, OutboundPlan(segments=[TextSegment(text="hi")], reply_to="m1"))
    first = sdk.calls[0]
    assert first[0] == "group"
    assert first[2]["msg_id"] == "m1"
    assert first[2]["msg_seq"] == 1

    await conn.send(conv, OutboundPlan(segments=[TextSegment(text="more")], reply_to="m1"))
    assert sdk.calls[-1][2]["msg_seq"] == 2


@pytest.mark.asyncio
async def test_reply_without_target_is_proactive():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="group", id="G1")
    await conn.send(conv, OutboundPlan(segments=[TextSegment(text="push")]))
    call = sdk.calls[0]
    assert call[0] == "group"
    assert "msg_id" not in call[2] and "msg_seq" not in call[2]


@pytest.mark.asyncio
async def test_markdown_falls_back_to_plain_text():
    sdk = FakeQQSDK()

    def post(group_openid, **fields):
        sdk.calls.append(("group", group_openid, fields))
        if fields.get("msg_type") == 2:
            raise QQAPIError(50056, "不允许发送 markdown content")
        return "msg_1"

    sdk.post_group_message = post  # type: ignore[method-assign]
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="group", id="G1")
    await conn.send(conv, OutboundPlan(segments=[TextSegment(text="# hi")], reply_to="m1"))

    assert sdk.calls[0][2]["msg_type"] == 2
    assert sdk.calls[-1][2]["msg_type"] == 0
    assert sdk.calls[-1][2]["content"] == "# hi"


@pytest.mark.asyncio
async def test_media_send_uploads_then_msg_type_7():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="direct", id="U1")
    plan = OutboundPlan(
        segments=[MediaSegment(media=RichMedia(kind="image", data=b"png", name="a.png"))]
    )
    await conn.send(conv, plan)

    upload = sdk.calls[0]
    assert upload == ("upload", "c2c", "U1", 1, "a.png")
    send = sdk.calls[-1]
    assert send[0] == "c2c"
    assert send[2]["msg_type"] == 7
    assert send[2]["media"]["file_info"] == "file_info_1"


@pytest.mark.asyncio
async def test_media_send_in_group_uses_group_scope():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="group", id="G1")
    plan = OutboundPlan(
        segments=[MediaSegment(media=RichMedia(kind="file", data=b"pdf", name="r.pdf"))]
    )
    await conn.send(conv, plan)
    assert sdk.calls[0] == ("upload", "group", "G1", 4, "r.pdf")
    assert sdk.calls[-1][0] == "group"
    assert sdk.calls[-1][2]["msg_type"] == 7


@pytest.mark.asyncio
async def test_identity_uses_ready_name():
    conn = connector(FakeQQSDK())
    conn._on_dispatch("READY", {"user": {"username": "MyBot", "id": "1"}})
    identity = await conn.identity(Conversation(channel="qq", kind="direct", id="U1"))
    assert identity.name == "MyBot"
    assert identity.aliases == ("MyBot",)


@pytest.mark.asyncio
async def test_download_prefers_voice_wav_url():
    conn = connector(FakeQQSDK())
    att = Attachment(
        kind="voice",
        handle={"url": "https://x/silk", "voice_wav_url": "https://x/wav"},
    )
    media = await conn.download(att)
    assert media.data == b"bytes"


@pytest.mark.asyncio
async def test_dedup_drops_a_repeated_message():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    items = []

    async def emit(item):
        items.append(item)

    await conn.start(emit)
    assert sdk.handlers is not None
    event = _c2c_event(id="dup1")
    sdk.handlers("C2C_MESSAGE_CREATE", event)
    await asyncio.sleep(0.05)
    sdk.handlers("C2C_MESSAGE_CREATE", event)
    await asyncio.sleep(0.05)

    assert len(items) == 1


@pytest.mark.asyncio
async def test_interaction_is_acknowledged_and_emitted():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    items = []

    async def emit(item):
        items.append(item)

    await conn.start(emit)
    assert sdk.handlers is not None
    event = {
        "id": "int1",
        "type": 11,
        "scene": "c2c",
        "chat_type": 2,
        "user_openid": "U1",
        "data": {"resolved": {"button_data": "v"}},
    }
    sdk.handlers("INTERACTION_CREATE", event)
    await asyncio.sleep(0.05)

    assert ("interaction", "int1", 0) in sdk.calls
    assert len(items) == 1
    assert items[0].value == "v"


def test_capabilities_match_the_protocol():
    caps = QQConnector(appid="a", secret="b", sdk=FakeQQSDK()).capabilities
    assert caps.buttons and caps.proactive
    assert not caps.typing and not caps.progress_placeholder
    assert caps.direct_delivery == "always"
    assert caps.group_delivery == "mention_only"
    assert caps.callback_actor_identity and not caps.member_roles
    assert not caps.edit_message and not caps.native_stream
    assert caps.supports_media_out("audio")
    assert caps.supports_media_in("image")


@pytest.mark.asyncio
async def test_card_send_builds_inline_keyboard():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="direct", id="U1")
    card = Card(
        title="Permission",
        body="Run a shell command?",
        buttons=[
            Button(text="Once", value='{"reply":"once"}'),
            Button(text="Reject", value='{"reply":"reject"}'),
        ],
    )

    conn._last_inbound[conv.key] = "m1"
    await conn.send(conv, OutboundPlan(segments=[CardSegment(card=card)]))

    call = sdk.calls[-1]
    assert call[0] == "c2c" and call[2]["msg_id"] == "m1"
    assert "Run a shell command?" in call[2]["content"]
    row = call[2]["keyboard"]["content"]["rows"][0]["buttons"]
    assert row[0]["render_data"]["label"] == "Once"
    assert row[0]["action"] == {
        "type": 1,
        "data": '{"reply":"once"}',
        "permission": {"type": 0},
    }


@pytest.mark.asyncio
async def test_send_without_target_replies_to_the_latest_inbound():
    sdk = FakeQQSDK()
    conn = connector(sdk)
    conv = Conversation(channel="qq", kind="group", id="G1")
    conn._last_inbound[conv.key] = "gm1"

    await conn.send(conv, OutboundPlan(segments=[TextSegment(text="hi")]))

    call = sdk.calls[-1]
    assert call[0] == "group"
    assert call[2]["msg_id"] == "gm1" and call[2]["msg_seq"] == 1


@pytest.mark.asyncio
async def test_markdown_failure_is_per_conversation():
    sdk = FakeQQSDK()

    def post(openid, **fields):
        sdk.calls.append(("c2c", openid, fields))
        if fields.get("msg_type") == 2 and openid == "U1":
            raise QQAPIError(400, "no markdown here")
        return "m"

    sdk.post_c2c_message = post  # type: ignore[method-assign]
    conn = connector(sdk)
    rejected = Conversation(channel="qq", kind="direct", id="U1")
    other = Conversation(channel="qq", kind="direct", id="U2")

    await conn.send(rejected, OutboundPlan(segments=[TextSegment(text="# a")]))
    await conn.send(other, OutboundPlan(segments=[TextSegment(text="# b")]))

    assert sdk.calls[0][2]["msg_type"] == 2  # rejected tried markdown
    assert sdk.calls[1][2]["msg_type"] == 0  # rejected fell back to text
    assert sdk.calls[-1][2]["msg_type"] == 2  # the other conversation keeps markdown


def test_new_inbound_evicts_the_previous_message_seq():
    conn = connector(FakeQQSDK())
    conn._queue_message(_c2c_event(id="m1"), "direct")
    conn._msg_seq["m1"] = 1  # a reply consumed the first message's sequence
    conn._queue_message(_c2c_event(id="m2"), "direct")
    assert "m1" not in conn._msg_seq  # the stale entry is dropped
    assert conn._last_inbound[next(iter(conn._last_inbound))] == "m2"
