from __future__ import annotations

import json

import pytest

import tether.connectors.feishu.connector as feishu_module
from tether.connectors.feishu.connector import (
    FeishuConnector,
    _interactive_card,
)
from tether.models import (
    Button,
    Card,
    CardQuestion,
    Conversation,
    IncomingInteraction,
    OutboundPlan,
    Sender,
    TextSegment,
)


class FakeFeishuSDK:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, on_message, on_card, on_recall):
        self.handlers = (on_message, on_card, on_recall)

    def stop(self):
        pass

    @property
    def connected(self) -> bool:
        return True

    def reply(self, message_id, msg_type, content):
        self.calls.append(("reply", message_id, msg_type, content))
        return "om_reply"

    def send(self, chat_id, msg_type, content):
        self.calls.append(("send", chat_id, msg_type, content))
        return "om_send"

    def patch(self, message_id, content):
        self.calls.append(("patch", message_id, content))

    def upload_image(self, data, filename):
        return "img_key"

    def upload_file(self, data, filename, kind):
        return "file_key"

    def download(self, message_id, file_key, kind):
        return b"bytes"

    def bot_info(self):
        return "MyBot", "An assistant"


def connector(sdk: FakeFeishuSDK) -> FeishuConnector:
    return FeishuConnector(app_id="a", app_secret="b", sdk=sdk)


def _event(message: dict, sender_id: str = "ou_1") -> dict:
    return {"event": {"sender": {"sender_id": {"open_id": sender_id}}, "message": message}}


def test_inbound_text_message():
    msg = {
        "message_id": "om_1",
        "chat_id": "oc_1",
        "chat_type": "p2p",
        "message_type": "text",
        "content": json.dumps({"text": "hello"}),
    }
    item = connector(FakeFeishuSDK())._inbound_message(_event(msg))
    assert item is not None
    assert item.text == "hello"
    assert item.sender.id == "ou_1"
    assert item.conversation.kind == "direct"
    assert item.conversation.id == "oc_1"


def test_inbound_group_image_becomes_attachment():
    msg = {
        "message_id": "om_2",
        "chat_id": "oc_g",
        "chat_type": "group",
        "message_type": "image",
        "content": json.dumps({"image_key": "ik_1"}),
    }
    item = connector(FakeFeishuSDK())._inbound_message(_event(msg))
    assert item is not None
    assert item.conversation.kind == "group"
    assert item.attachments[0].kind == "image"
    assert item.attachments[0].handle == {"message_id": "om_2", "file_key": "ik_1"}


def test_inbound_post_is_flattened():
    post = {
        "title": "T",
        "content": [[{"tag": "text", "text": "hi "}, {"tag": "at", "user_id": "ou_9"}]],
    }
    msg = {
        "message_id": "om_3",
        "chat_type": "p2p",
        "message_type": "post",
        "content": json.dumps(post),
    }
    item = connector(FakeFeishuSDK())._inbound_message(_event(msg))
    assert item is not None
    assert item.text == "Thi @ou_9"


def test_card_action_becomes_interaction():
    event = {
        "event": {
            "operator": {"open_id": "ou_2"},
            "action": {"value": {"key": '{"kind":"permission","reply":"once"}'}},
            "context": {"open_message_id": "om_1", "chat_id": "oc_1", "chat_type": "group"},
        }
    }
    item = connector(FakeFeishuSDK())._inbound_card(event)
    assert item is not None
    assert item.value == '{"kind":"permission","reply":"once"}'
    assert item.sender.id == "ou_2"
    assert item.conversation.kind == "group"


@pytest.mark.asyncio
async def test_send_then_edit_streams():
    sdk = FakeFeishuSDK()
    conn = connector(sdk)
    conv = Conversation(channel="feishu", kind="direct", id="oc_1")
    ref = await conn.send(conv, OutboundPlan(segments=[TextSegment(text="hi")], final=False))
    sent = [c for c in sdk.calls if c[0] == "send"][0]
    assert sent[2] == "interactive"
    assert sent[3]["elements"][0]["content"] == "hi"
    await conn.update(ref, OutboundPlan(segments=[TextSegment(text="hi there")], final=True))
    patched = [c for c in sdk.calls if c[0] == "patch"][0]
    assert patched[1] == "om_send"
    assert patched[2]["elements"][0]["content"] == "hi there"


@pytest.mark.asyncio
async def test_acknowledge_patches_clicked_card():
    sdk = FakeFeishuSDK()
    conn = connector(sdk)
    interaction = IncomingInteraction(
        conversation=Conversation(channel="feishu", kind="group", id="oc_1"),
        message_id="om_card",
        sender=Sender(id="ou_2"),
        value="{}",
    )
    await conn.acknowledge(interaction, "✅ Allowed")
    patched = [c for c in sdk.calls if c[0] == "patch"][0]
    assert patched[1] == "om_card"
    assert patched[2]["body"]["elements"][0]["content"] == "✅ Allowed"


@pytest.mark.asyncio
async def test_send_card_is_interactive_with_buttons():
    sdk = FakeFeishuSDK()
    conn = connector(sdk)
    conv = Conversation(channel="feishu", kind="direct", id="oc_1")
    await conn.send_card(conv, Card(title="t", body="b", buttons=[Button(text="Go", value="v")]))
    kind_call = [c for c in sdk.calls if c[0] == "send"][0]
    assert kind_call[2] == "interactive"
    button = kind_call[3]["body"]["elements"][-1]["columns"][0]["elements"][0]
    assert button["behaviors"][0]["value"] == {"key": "v"}


@pytest.mark.asyncio
async def test_identity_uses_bot_info():
    conn = connector(FakeFeishuSDK())
    await conn._connect()
    identity = await conn.identity(Conversation(channel="feishu", kind="direct", id="oc_1"))
    assert identity.name == "MyBot"
    assert identity.description == "An assistant"


def test_mention_placeholders_are_replaced():
    msg = {
        "message_id": "om_4",
        "chat_id": "oc_g",
        "chat_type": "group",
        "message_type": "text",
        "content": json.dumps({"text": "@_user_1 hi"}),
        "mentions": [{"key": "@_user_1", "name": "Bot", "id": {"open_id": "ou_bot"}}],
    }
    item = connector(FakeFeishuSDK())._inbound_message(_event(msg))
    assert item is not None
    assert item.text == "@Bot hi"
    assert item.mentions[0].name == "Bot"


def test_model_object_event_is_parsed():
    from types import SimpleNamespace as NS

    mention = NS(key="@_user_1", name="Bot", id=NS(open_id="ou_bot"))
    message = NS(
        message_id="om_5",
        chat_id="oc_p2p",
        chat_type="p2p",
        message_type="text",
        content=json.dumps({"text": "@_user_1 hi"}),
        mentions=[mention],
    )
    event = NS(event=NS(message=message, sender=NS(sender_id=NS(open_id="ou_user"))))

    item = connector(FakeFeishuSDK())._inbound_message(event)

    assert item is not None
    assert item.message_id == "om_5"
    assert item.text == "@Bot hi"
    assert item.conversation.id == "oc_p2p"
    assert item.sender.id == "ou_user"


def test_inbound_video_uses_file_key_not_cover():
    msg = {
        "message_id": "om_v",
        "chat_id": "oc_1",
        "chat_type": "p2p",
        "message_type": "media",
        "content": json.dumps({"file_key": "fk_video", "image_key": "ik_cover", "duration": 1000}),
    }
    item = connector(FakeFeishuSDK())._inbound_message(_event(msg))
    assert item is not None
    assert item.attachments[0].kind == "video"
    assert item.attachments[0].handle == {"message_id": "om_v", "file_key": "fk_video"}


@pytest.mark.asyncio
async def test_send_text_falls_back_to_send_when_reply_fails():
    sdk = FakeFeishuSDK()

    def boom(*_args, **_kwargs):
        raise RuntimeError("stale reply target")

    sdk.reply = boom
    conn = connector(sdk)
    conv = Conversation(channel="feishu", kind="group", id="oc_1")

    await conn.send(
        conv, OutboundPlan(segments=[TextSegment(text="hi")], reply_to="om_x", final=True)
    )

    assert any(call[0] == "send" for call in sdk.calls)


def test_question_form_card_renders_controls():
    card = Card(
        title="Pick",
        body="",
        questions=[
            CardQuestion(header="When", body="when?", options=["A", "B"]),
            CardQuestion(header="More", body="more?", options=["X", "Y"], multiple=True),
        ],
        submit_value='{"k":1}',
    )
    payload = _interactive_card(card)
    form = next(e for e in payload["body"]["elements"] if e["tag"] == "form")
    select = next(e for e in form["elements"] if e["tag"] == "select_static")
    assert select["name"] == "q0"
    assert [o["value"] for o in select["options"]] == ["A", "B"]
    checkers = [e for e in form["elements"] if e["tag"] == "checker"]
    assert [c["name"] for c in checkers] == ["q1_0", "q1_1"]
    submit = form["elements"][-1]
    assert submit["form_action_type"] == "submit"
    assert submit["behaviors"][0]["value"] == {"key": '{"k":1}'}


def test_card_form_submit_carries_form_value():
    event = {
        "event": {
            "operator": {"open_id": "ou_2"},
            "action": {
                "value": {"key": '{"kind":"question"}'},
                "form_value": {"opt0": True, "opt1": False},
            },
            "context": {"open_message_id": "om_1", "chat_id": "oc_1", "chat_type": "group"},
        }
    }
    item = connector(FakeFeishuSDK())._inbound_card(event)
    assert item is not None
    assert item.form == {"opt0": True, "opt1": False}


def test_interactive_card_honors_button_style():
    card = Card(
        title="t",
        body="b",
        buttons=[
            Button(text="Allow once", value="a"),
            Button(text="Always allow", value="b", style="primary"),
            Button(text="Deny", value="c", style="danger"),
        ],
    )
    columns = _interactive_card(card)["body"]["elements"][-1]["columns"]
    types = [c["elements"][0]["type"] for c in columns]
    assert types == ["primary", "primary", "danger"]


def test_lark_sdk_supervises_the_stream_thread(monkeypatch):
    import time

    monkeypatch.setattr(feishu_module, "_STREAM_BACKOFF_S", 0.01)
    monkeypatch.setattr(feishu_module, "_STREAM_BACKOFF_MAX_S", 0.02)

    builds: list[int] = []
    starts: list[int] = []

    class _WS:
        def start(self) -> None:
            starts.append(1)
            if len(starts) == 1:
                raise RuntimeError("socket died on the first start")
            while not sdk._stopped.is_set():
                time.sleep(0.01)

    sdk = feishu_module.LarkSDK("id", "sec")

    def fake_build(on_message, on_card, on_recall):
        builds.append(1)
        sdk._ws = _WS()

    monkeypatch.setattr(sdk, "_build", fake_build)
    sdk.start(lambda *a: None, lambda *a: None, lambda *a: None)
    for _ in range(200):
        time.sleep(0.01)
        if len(builds) >= 2 and len(starts) >= 2:
            break
    sdk.stop()
    assert len(builds) >= 2, "the supervisor must rebuild the client"
    assert len(starts) >= 2, "the supervisor must restart the stream"
