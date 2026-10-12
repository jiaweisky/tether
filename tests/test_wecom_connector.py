from __future__ import annotations

import pytest

from tether.connectors.wecom.connector import WeComConnector
from tether.models import (
    Attachment,
    Button,
    Card,
    Conversation,
    InboundMessage,
    IncomingInteraction,
    MediaSegment,
    OutboundPlan,
    RichMedia,
    TextSegment,
)


class FakeWeComSDK:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.connected = False
        self.streams: list[tuple[str, str, bool]] = []
        self.cards: list[dict] = []
        self.stream_cards: list[tuple[str, str, dict]] = []
        self.card_updates: list[dict] = []
        self.sent: list[tuple[str, dict]] = []
        self.welcome: list[dict] = []
        self.uploads: list[tuple[str, str, int]] = []
        self.reply_media_calls: list[tuple[str, str]] = []
        self.sent_media: list[tuple[str, str, str]] = []
        self._files: dict[str, bytes] = {}

    def register_file(self, url: str, data: bytes) -> None:
        self._files[url] = data

    def on(self, event, handler):
        self.handlers[event] = handler

    async def connect(self):
        self.connected = True
        return self

    def disconnect(self):
        self.connected = False

    async def reply_stream(self, frame, stream_id, content, finish, msg_item=None):
        self.streams.append((stream_id, content, finish))

    async def reply_welcome(self, frame, body):
        self.welcome.append(body)

    async def reply_template_card(self, frame, card):
        self.cards.append(card)

    async def reply_stream_with_card(self, frame, stream_id, content, finish, template_card=None):
        self.stream_cards.append((stream_id, content, template_card))

    async def send_message(self, chatid, body):
        self.sent.append((chatid, body))

    async def download_file(self, url, aes_key):
        return self._files[url], "report.pdf"

    async def upload_media(self, data, media_type, filename):
        self.uploads.append((media_type, filename, len(data)))
        return "media-1"

    async def reply_media(self, frame, media_type, media_id):
        self.reply_media_calls.append((media_type, media_id))

    async def send_media_message(self, chatid, media_type, media_id):
        self.sent_media.append((chatid, media_type, media_id))

    async def update_template_card(self, frame, card):
        self.card_updates.append(card)

    def generate_stream_id(self):
        return f"stream-{len(self.streams)}"

    async def emit(self, event: str, frame: dict) -> None:
        await self.handlers[event](frame)  # type: ignore[operator]


async def start_connector(*, welcome_text: str | None = None):
    sdk = FakeWeComSDK()
    connector = WeComConnector(bot_id="bot", secret="sec", sdk=sdk, welcome_text=welcome_text)
    items: list = []

    async def emit(item):
        items.append(item)

    await connector.start(emit)
    return connector, sdk, items


def text_frame(text: str = "hi", *, chatid: str = "u1", chattype: str = "single") -> dict:
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgtype": "text",
            "msgid": "m1",
            "chatid": chatid,
            "chattype": chattype,
            "from": {"userid": "u1", "name": "Alice"},
            "text": {"content": text},
        },
    }


@pytest.mark.asyncio
async def test_handlers_registered_and_text_inbound():
    _, sdk, items = await start_connector()
    assert sdk.connected
    for event in ("message.text", "message.image", "message.mixed", "event.template_card_event"):
        assert event in sdk.handlers

    await sdk.emit("message.text", text_frame("hello"))
    assert len(items) == 1
    message = items[0]
    assert isinstance(message, InboundMessage)
    assert message.text == "hello"
    assert message.sender.id == "u1"
    assert message.conversation.kind == "direct"


@pytest.mark.asyncio
async def test_group_conversation_and_speaker():
    _, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi all", chatid="g1", chattype="group"))
    conv = items[0].conversation
    assert conv.kind == "group"
    assert conv.id == "g1"


@pytest.mark.asyncio
async def test_missing_msgid_falls_back_to_request_id():
    _, sdk, items = await start_connector()
    first = text_frame("a")
    first["body"].pop("msgid")
    second = text_frame("b")
    second["body"].pop("msgid")
    second["headers"]["req_id"] = "r2"
    await sdk.emit("message.text", first)
    await sdk.emit("message.text", second)
    assert [m.message_id for m in items] == ["r1", "r2"]


@pytest.mark.asyncio
async def test_streaming_requires_an_inbound_frame():
    connector, sdk, items = await start_connector()
    proactive = Conversation(channel="wecom", kind="direct", id="u9")
    # No inbound frame yet: WeCom cannot stream, so the engine sends one-shot.
    assert connector.supports_streaming(proactive) is False
    await sdk.emit("message.text", text_frame("hi"))
    assert connector.supports_streaming(items[0].conversation) is True


@pytest.mark.asyncio
async def test_text_reply_streams_via_frame():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    await connector.send(conv, OutboundPlan(segments=[TextSegment(text="answer")], final=True))
    assert sdk.streams == [("stream-0", "answer", True)]


@pytest.mark.asyncio
async def test_streaming_interim_then_final():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    ref = await connector.send(
        conv, OutboundPlan(segments=[TextSegment(text="partial")], final=False)
    )
    await connector.update(
        ref, OutboundPlan(segments=[TextSegment(text="full answer")], final=True)
    )
    assert sdk.streams == [("stream-0", "partial", False), ("stream-0", "full answer", True)]


@pytest.mark.asyncio
async def test_proactive_send_without_frame():
    connector, sdk, _ = await start_connector()
    conv = Conversation(channel="wecom", kind="direct", id="u9")
    await connector.send(conv, OutboundPlan(segments=[TextSegment(text="push")]))
    assert sdk.sent and sdk.sent[0][0] == "u9"
    assert sdk.sent[0][1]["msgtype"] == "markdown"


@pytest.mark.asyncio
async def test_card_event_becomes_interaction():
    _, sdk, items = await start_connector()
    # Real WeCom shape: the key is nested under event.template_card_event.
    frame = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "r2"},
        "body": {
            "msgid": "card1",
            "chattype": "single",
            "from": {"userid": "u1"},
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {
                    "card_type": "button_interaction",
                    "event_key": '{"kind":"permission","reply":"once"}',
                    "task_id": "tether-x",
                },
            },
        },
    }
    await sdk.emit("event.template_card_event", frame)
    interaction = items[0]
    assert isinstance(interaction, IncomingInteraction)
    assert interaction.value == '{"kind":"permission","reply":"once"}'
    assert interaction.sender.id == "u1"


@pytest.mark.asyncio
async def test_send_card_embeds_in_stream():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    ref = await connector.send_card(
        conv, Card(title="t", body="b", buttons=[Button(text="Go", value="v")])
    )
    assert sdk.stream_cards, "card should ride the streaming message"
    stream_id, _content, payload = sdk.stream_cards[0]
    assert payload["card_type"] == "button_interaction"
    assert payload["button_list"][0]["key"] == "v"
    # WeCom drops the buttons without a task_id.
    assert payload["task_id"]
    assert ref.id == stream_id


@pytest.mark.asyncio
async def test_download_uses_aeskey_handle():
    connector, sdk, _ = await start_connector()
    sdk.register_file("https://x/f", b"bytes")
    att = Attachment(kind="image", handle={"url": "https://x/f", "aeskey": "k"})
    media = await connector.download(att)
    assert media.data == b"bytes"
    assert media.name == "report.pdf"


@pytest.mark.asyncio
async def test_outbound_media_uploads_and_replies():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    plan = OutboundPlan(
        segments=[
            MediaSegment(media=RichMedia(kind="image", data=b"png", mime="image/png", name="a.png"))
        ]
    )
    await connector.send(conv, plan)
    assert sdk.uploads == [("image", "a.png", 3)]
    assert sdk.reply_media_calls == [("image", "media-1")]


@pytest.mark.asyncio
async def test_outbound_media_proactive_without_frame():
    connector, sdk, _ = await start_connector()
    conv = Conversation(channel="wecom", kind="direct", id="u9")
    plan = OutboundPlan(
        segments=[
            MediaSegment(media=RichMedia(kind="audio", data=b"wav", mime="audio/wav", name="v.wav"))
        ]
    )
    await connector.send(conv, plan)
    assert sdk.uploads == [("voice", "v.wav", 3)]
    assert sdk.sent_media == [("u9", "voice", "media-1")]


@pytest.mark.asyncio
async def test_enter_chat_sends_welcome():
    _, sdk, items = await start_connector(welcome_text="welcome!")
    frame = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "r3"},
        "body": {"chatid": "u1", "from": {"userid": "u1"}, "event": {"eventtype": "enter_chat"}},
    }
    await sdk.emit("event.enter_chat", frame)
    assert sdk.welcome and sdk.welcome[0]["text"]["content"] == "welcome!"
    assert items and items[0].kind == "enter_chat"


@pytest.mark.asyncio
async def test_card_event_does_not_replace_reply_frame():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    card_frame = {
        "headers": {"req_id": "event-req"},
        "body": {
            "chattype": "single",
            "from": {"userid": "u1"},
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {"event_key": "{}"},
            },
        },
    }
    await sdk.emit("event.template_card_event", card_frame)
    # The reply frame is still the message callback (its req_id is valid for reply_stream).
    assert connector._frames[conv.key]["body"]["msgtype"] == "text"


@pytest.mark.asyncio
async def test_acknowledge_updates_the_clicked_card():
    connector, sdk, _ = await start_connector()
    frame = {
        "headers": {"req_id": "ev"},
        "body": {
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {"event_key": "{}", "task_id": "tether-x"},
            }
        },
    }
    from tether.models import Sender

    interaction = IncomingInteraction(
        conversation=Conversation(channel="wecom", kind="direct", id="u1"),
        message_id="m",
        sender=Sender(id="u1"),
        value="{}",
        raw=frame,
    )
    await connector.acknowledge(interaction, "✅ Allow once")
    assert sdk.card_updates and sdk.card_updates[0]["main_title"]["title"] == "✅ Allow once"
    assert sdk.card_updates[0]["task_id"] == "tether-x"
