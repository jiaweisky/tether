from __future__ import annotations

import asyncio

import pytest

from tether.app import TetherApp
from tether.config import Config
from tether.connectors.fake import FakeConnector
from tether.connectors.wechat.login import WeChatLoginRejected
from tether.connectors.wechat.storage import WeChatCredential
from tether.models import Conversation, InboundMessage, Sender


class DummyWeChat:
    name = "wechat"

    def __init__(self, account: str, result) -> None:
        self.account = account
        self.instance_id = f"wechat@{account}"
        self.result = result

    async def login(self, *, on_qr):
        await on_qr(b"png-bytes", "qr-content")
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _app(tmp_path) -> TetherApp:
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
                        },
                        {
                            "id": "ops",
                            "identity": {"display_name": "运维号"},
                            "login_via": [{"channel": "wecom", "user": "ops-admin"}],
                        },
                    ],
                }
            }
        }
    )
    return TetherApp(config, db_path=str(tmp_path / "t.db"))


def _msg(text: str, *, sender="admin", kind="direct") -> tuple[Conversation, Sender]:
    return (
        Conversation(channel="wecom", kind=kind, id="d1"),
        Sender(id=sender),
    )


@pytest.mark.asyncio
async def test_run_wechat_login_sends_qr_and_receipt(tmp_path):
    app = _app(tmp_path)
    initiator = FakeConnector()
    conv, _ = _msg("")
    credential = WeChatCredential(token="t", base_url="https://api", bot_id="bot-a")
    target = DummyWeChat("assistant", credential)
    await app._run_wechat_login(target, target.login, initiator, conv)

    kinds = [message["kind"] for message in initiator.messages]
    assert "media" in kinds
    assert "bot-a" in initiator.messages[-1]["text"]
    assert "assistant" in initiator.messages[-1]["text"]


@pytest.mark.asyncio
async def test_run_wechat_login_reports_rejection_with_platform_id(tmp_path):
    app = _app(tmp_path)
    initiator = FakeConnector()
    conv, _ = _msg("")
    target = DummyWeChat(
        "assistant", WeChatLoginRejected("bot-x", "already bound")
    )
    await app._run_wechat_login(target, target.login, initiator, conv)
    text = initiator.last_text()
    assert "already bound" in text
    assert "bot-x" in text


@pytest.mark.asyncio
async def test_login_command_is_direct_and_resolved_by_login_via(tmp_path):
    app = _app(tmp_path)
    initiator = FakeConnector()
    app.connectors["wechat@assistant"] = DummyWeChat(
        "assistant",
        WeChatCredential(token="t", base_url="https://api", bot_id="bot-a"),
    )

    group, sender = _msg("/login wechat", kind="group")
    await app._handle_login(
        _inbound(group, sender, "wechat"), initiator, "wechat"
    )
    assert "direct chat only" in initiator.last_text()

    other, sender = _msg("/login wechat", sender="stranger")
    await app._handle_login(
        _inbound(other, sender, "wechat"), initiator, "wechat"
    )
    assert "not allowed" in initiator.last_text()

    mapped, sender = _msg("/login wechat", sender="admin")
    await app._handle_login(
        _inbound(mapped, sender, "wechat"), initiator, "wechat"
    )
    tasks = list(app._login_tasks)
    await asyncio.gather(*tasks)
    assert "bot-a" in initiator.last_text()


@pytest.mark.asyncio
async def test_login_command_usage(tmp_path):
    app = _app(tmp_path)
    initiator = FakeConnector()
    conv, sender = _msg("/login")
    await app._handle_login(_inbound(conv, sender, ""), initiator, "")
    assert "Usage:" in initiator.last_text()

    await app._handle_login(
        _inbound(conv, sender, "wechat assistant"), initiator, "wechat assistant"
    )
    assert "Usage:" in initiator.last_text()


def _inbound(conv: Conversation, sender: Sender, text: str) -> InboundMessage:
    return InboundMessage(
        channel="wecom",
        message_id="m1",
        conversation=conv,
        sender=sender,
        text=text,
    )


@pytest.mark.asyncio
async def test_reload_applies_bot_identity_and_login_via(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        """
channels:
  wechat:
    enabled: true
    bots:
      - id: assistant
        identity: {display_name: A}
        login_via: [{channel: wecom, user: admin}]
"""
    )
    config = Config.model_validate(
        {
            "channels": {
                "wechat": {
                    "enabled": True,
                    "bots": [
                        {
                            "id": "assistant",
                            "identity": {"display_name": "A"},
                            "login_via": [{"channel": "wecom", "user": "admin"}],
                        }
                    ],
                }
            }
        }
    )
    app = TetherApp(config, db_path=str(tmp_path / "t.db"), config_path=str(path))

    class DummyPolicy:
        name = "wechat"
        account = "assistant"

        def __init__(self):
            self.spec = None

        def apply_bot_policy(self, spec):
            self.spec = spec

    dummy = DummyPolicy()
    app.connectors["wechat@assistant"] = dummy
    path.write_text(
        """
channels:
  wechat:
    enabled: true
    bots:
      - id: assistant
        identity: {display_name: B, description: new}
        login_via: [{channel: wecom, user: newadmin}]
"""
    )
    app._reload_config()
    assert app.config.channels.wechat.account_identity("assistant").display_name == "B"
    assert app.config.channels.wechat.bot_for_login("wecom", "newadmin") is not None
    assert dummy.spec is not None and dummy.spec.identity.display_name == "B"
