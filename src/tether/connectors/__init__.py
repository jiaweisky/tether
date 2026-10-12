"""Registration of the built-in connectors and construction of the enabled set."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from ..connector import IMConnector, register_connector
from .fake import FakeConnector

if TYPE_CHECKING:
    from ..config import Config

__all__ = ["FakeConnector", "build_enabled", "register_builtins"]


def register_builtins() -> None:
    register_connector("wecom", _make_wecom)
    register_connector("feishu", _make_feishu)
    register_connector("qq", _make_qq)
    register_connector("wechat", _make_wechat)
    register_connector("fake", lambda **_: FakeConnector())


def _make_wecom(*, bot_id: str, secret: str, welcome_text: str | None = None, **_):
    from .wecom.connector import WeComConnector

    return WeComConnector(bot_id=bot_id, secret=secret, welcome_text=welcome_text)


def _make_feishu(*, app_id: str, app_secret: str, **_):
    from .feishu.connector import FeishuConnector

    return FeishuConnector(app_id=app_id, app_secret=app_secret)


def _make_qq(*, appid: str, secret: str, **_):
    from .qq.connector import QQConnector

    return QQConnector(appid=appid, secret=secret)


def _make_wechat(*, cred_path: str, **_):
    from .wechat.connector import WeChatConnector

    return WeChatConnector(cred_path=cred_path)


def _require(value: str | None, field: str, channel: str) -> str:
    if not value:
        raise ValueError(f"channel {channel!r} is enabled but {field} is empty")
    return value


def _build_wecom(channel: Any) -> IMConnector:
    return _make_wecom(
        bot_id=_require(channel.bot_id, "bot_id", "wecom"),
        secret=_require(channel.secret, "secret", "wecom"),
        welcome_text=channel.welcome_text,
    )


def _build_feishu(channel: Any) -> IMConnector:
    return _make_feishu(
        app_id=_require(channel.app_id, "app_id", "feishu"),
        app_secret=_require(channel.app_secret, "app_secret", "feishu"),
    )


def _build_qq(channel: Any) -> IMConnector:
    return _make_qq(
        appid=_require(channel.appid, "appid", "qq"),
        secret=_require(channel.secret, "secret", "qq"),
    )


def _build_wechat(channel: Any) -> IMConnector:
    return _make_wechat(cred_path=os.path.expanduser(channel.cred_path))


def build_enabled(config: Config) -> list[IMConnector]:
    """Construct every connector whose channel is enabled in the config."""
    register_builtins()
    channels = config.channels
    specs = (
        (channels.wecom, _build_wecom),
        (channels.feishu, _build_feishu),
        (channels.qq, _build_qq),
        (channels.wechat, _build_wechat),
    )
    return [builder(channel) for channel, builder in specs if channel.enabled]
