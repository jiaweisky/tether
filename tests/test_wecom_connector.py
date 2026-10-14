from __future__ import annotations

import json

import pytest

from tether.connector import Unsupported
from tether.connectors.wecom.connector import WeComConnector
from tether.models import (
    Attachment,
    Button,
    Card,
    CardQuestion,
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
async def test_send_card_is_a_standalone_passive_reply():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    await connector.send_card(
        conv, Card(title="t", body="b", buttons=[Button(text="Go", value="v")])
    )
    assert sdk.cards, "card should be sent as a standalone passive reply"
    payload = sdk.cards[0]
    assert payload["card_type"] == "button_interaction"
    assert payload["button_list"][0]["key"] == "v"
    # WeCom drops the buttons without a task_id.
    assert payload["task_id"]


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


@pytest.mark.asyncio
async def test_outbound_media_falls_back_to_proactive_when_reply_fails():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation

    async def boom(*args, **kwargs):
        raise RuntimeError("reply slot taken by the text stream")

    sdk.reply_media = boom
    plan = OutboundPlan(
        segments=[
            MediaSegment(media=RichMedia(kind="image", data=b"png", mime="image/png", name="a.png"))
        ]
    )
    await connector.send(conv, plan)
    assert sdk.sent_media == [("u1", "image", "media-1")]


def voice_frame(*, content: str | None, url: str | None = "https://x/v") -> dict:
    voice: dict = {}
    if content is not None:
        voice["content"] = content
    if url is not None:
        voice["url"] = url
        voice["aeskey"] = "k"
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r1"},
        "body": {
            "msgtype": "voice",
            "msgid": "v1",
            "chatid": "u1",
            "chattype": "single",
            "from": {"userid": "u1"},
            "voice": voice,
        },
    }


@pytest.mark.asyncio
async def test_voice_with_recognized_text_skips_audio():
    _, sdk, items = await start_connector()
    await sdk.emit("message.voice", voice_frame(content="你好"))
    message = items[0]
    assert message.text == "你好"
    assert message.attachments == []


@pytest.mark.asyncio
async def test_voice_without_text_attaches_audio():
    _, sdk, items = await start_connector()
    await sdk.emit("message.voice", voice_frame(content=None))
    message = items[0]
    assert message.text == ""
    assert message.attachments and message.attachments[0].kind == "voice"


@pytest.mark.asyncio
async def test_outbound_media_derives_filename_from_mime():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    plan = OutboundPlan(
        segments=[MediaSegment(media=RichMedia(kind="image", data=b"png", mime="image/png"))]
    )
    await connector.send(conv, plan)
    assert sdk.uploads == [("image", "image.png", 3)]


@pytest.mark.asyncio
async def test_single_multi_choice_question_becomes_vote_card():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    card = Card(
        title="Pick",
        body="",
        questions=[CardQuestion(header="H", body="q", options=["A", "B"], multiple=True)],
        submit_value='{"specs":[{"multiple":true,"options":["A","B"]}]}',
    )
    await connector.send_card(conv, card)
    payload = sdk.cards[-1]  # form cards use the standalone passive reply
    assert payload["card_type"] == "vote_interaction"
    assert payload["checkbox"]["mode"] == 1
    assert payload["task_id"]  # WeCom drops interaction cards without a task_id
    assert [o["text"] for o in payload["checkbox"]["option_list"]] == ["A", "B"]


@pytest.mark.asyncio
async def test_multiple_single_choice_questions_become_multiple_card():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    card = Card(
        title="Q",
        body="",
        questions=[
            CardQuestion(header="A", body="a", options=["1", "2"]),
            CardQuestion(header="B", body="b", options=["x", "y"]),
        ],
        submit_value="{}",
    )
    await connector.send_card(conv, card)
    payload = sdk.cards[-1]
    assert payload["card_type"] == "multiple_interaction"
    assert payload["task_id"]
    assert [q["question_key"] for q in payload["select_list"]] == ["q0", "q1"]


@pytest.mark.asyncio
async def test_mixed_multi_question_is_unsupported():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    card = Card(
        title="Q",
        body="",
        questions=[
            CardQuestion(header="A", body="a", options=["1"]),
            CardQuestion(header="B", body="b", options=["x", "y"], multiple=True),
        ],
        submit_value="{}",
    )
    with pytest.raises(Unsupported):
        await connector.send_card(conv, card)


@pytest.mark.asyncio
async def test_vote_submit_decodes_selected_items():
    _, sdk, items = await start_connector()
    value = json.dumps(
        {
            "kind": "question",
            "sid": "s",
            "rid": "r",
            "specs": [{"multiple": True, "options": ["A", "B"]}],
        }
    )
    frame = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "r3"},
        "body": {
            "msgid": "card2",
            "chattype": "single",
            "from": {"userid": "u1"},
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {
                    "card_type": "vote_interaction",
                    "event_key": value,
                    "task_id": "tether-x",
                    "selected_items": {
                        "selected_item": [
                            {"question_key": "q0", "option_ids": {"option_id": ["1"]}}
                        ]
                    },
                },
            },
        },
    }
    await sdk.emit("event.template_card_event", frame)
    interaction = items[0]
    assert interaction.value == value
    assert interaction.form == {"q0_1": True}


@pytest.mark.asyncio
async def test_multiple_submit_decodes_selected_labels():
    _, sdk, items = await start_connector()
    value = json.dumps(
        {
            "kind": "question",
            "sid": "s",
            "rid": "r",
            "specs": [
                {"multiple": False, "options": ["A", "B"]},
                {"multiple": False, "options": ["X", "Y"]},
            ],
        }
    )
    frame = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "r4"},
        "body": {
            "msgid": "card3",
            "chattype": "single",
            "from": {"userid": "u1"},
            "event": {
                "eventtype": "template_card_event",
                "template_card_event": {
                    "card_type": "multiple_interaction",
                    "event_key": value,
                    "task_id": "tether-x",
                    "selected_items": {
                        "selected_item": [
                            {"question_key": "q0", "option_ids": {"option_id": ["1"]}},
                            {"question_key": "q1", "option_ids": {"option_id": ["0"]}},
                        ]
                    },
                },
            },
        },
    }
    await sdk.emit("event.template_card_event", frame)
    assert items[0].form == {"q0": "B", "q1": "X"}


@pytest.mark.asyncio
async def test_more_than_three_questions_is_unsupported():
    connector, sdk, items = await start_connector()
    await sdk.emit("message.text", text_frame("hi"))
    conv = items[0].conversation
    card = Card(
        title="Q",
        body="",
        questions=[CardQuestion(header=f"Q{i}", body="q", options=["a", "b"]) for i in range(4)],
        submit_value="{}",
    )
    with pytest.raises(Unsupported):
        await connector.send_card(conv, card)


@pytest.mark.asyncio
async def test_text_reply_quoting_a_file_becomes_an_attachment():
    _, sdk, items = await start_connector()
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r9"},
        "body": {
            "msgtype": "text",
            "msgid": "m9",
            "chatid": "g1",
            "chattype": "group",
            "from": {"userid": "u1"},
            "text": {"content": "@Bot "},
            "quote": {"msgtype": "file", "file": {"url": "https://x/f", "aeskey": "k"}},
        },
    }
    await sdk.emit("message.text", frame)
    message = items[0]
    assert message.attachments and message.attachments[0].kind == "file"
    assert message.attachments[0].handle == {"url": "https://x/f", "aeskey": "k"}


@pytest.mark.asyncio
async def test_text_reply_quoting_text_prefixes_the_quote():
    _, sdk, items = await start_connector()
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "r10"},
        "body": {
            "msgtype": "text",
            "msgid": "m10",
            "chatid": "u1",
            "chattype": "single",
            "from": {"userid": "u1"},
            "text": {"content": "yes do it"},
            "quote": {"msgtype": "text", "text": {"content": "should I?"}},
        },
    }
    await sdk.emit("message.text", frame)
    assert items[0].text == "[quoting] should I?\nyes do it"
