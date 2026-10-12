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


def _make_wecom(*, bot_id: str, secret: str, **_):
    from .wecom.connector import WeComConnector

    return WeComConnector(bot_id=bot_id, secret=secret)


def _make_feishu(*, app_id: str, app_secret: str, **_):
    from .feishu.connector import FeishuConnector

    return FeishuConnector(app_id=app_id, app_secret=app_secret)


def _make_qq(*, appid: str, secret: str, **_):
    from .qq.connector import QQConnector

    return QQConnector(appid=appid, secret=secret)


def _make_wechat(*, cred_path: str, **_):
    from .wechat.connector import WeChatConnector

    return WeChatConnector(cred_path=cred_path)


def _require_env(name: str, channel: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"channel {channel!r} is enabled but env {name!r} is not set")
    return value


def _build_wecom(channel: Any) -> IMConnector:
    return _make_wecom(
        bot_id=_require_env(channel.bot_id_env, "wecom"),
        secret=_require_env(channel.secret_env, "wecom"),
    )


def _build_feishu(channel: Any) -> IMConnector:
    return _make_feishu(
        app_id=_require_env(channel.app_id_env, "feishu"),
        app_secret=_require_env(channel.app_secret_env, "feishu"),
    )


def _build_qq(channel: Any) -> IMConnector:
    return _make_qq(
        appid=_require_env(channel.appid_env, "qq"),
        secret=_require_env(channel.secret_env, "qq"),
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
