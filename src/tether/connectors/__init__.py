"""Registration of the built-in connectors and construction of the enabled set."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tether.connector import IMConnector, register_connector
from tether.connectors.fake import FakeConnector

if TYPE_CHECKING:
    from tether.config import Config

__all__ = ["FakeConnector", "build_enabled", "register_builtins"]


def register_builtins() -> None:
    register_connector("wecom", _make_wecom)
    register_connector("feishu", _make_feishu)
    register_connector("qq", _make_qq)
    register_connector("wechat", _make_wechat)
    register_connector("fake", lambda **_: FakeConnector())


def _make_wecom(
    *,
    bot_id: str,
    secret: str,
    welcome_text: str | None = None,
    reconnect_max_ms: int | None = None,
    **_,
):
    from tether.connectors.wecom.connector import WeComConnector

    return WeComConnector(
        bot_id=bot_id,
        secret=secret,
        welcome_text=welcome_text,
        reconnect_max_ms=reconnect_max_ms,
    )


def _make_feishu(*, app_id: str, app_secret: str, **_):
    from tether.connectors.feishu.connector import FeishuConnector

    return FeishuConnector(app_id=app_id, app_secret=app_secret)


def _make_qq(*, appid: str, secret: str, **_):
    from tether.connectors.qq.connector import QQConnector

    return QQConnector(appid=appid, secret=secret)


def _make_wechat(
    *,
    spec: Any,
    channel_enabled: bool,
    qr_timeout_s: int,
    store: Any = None,
    **_,
):
    from tether.connectors.wechat.connector import WeChatConnector

    return WeChatConnector(
        spec=spec,
        channel_enabled=channel_enabled,
        qr_timeout_s=qr_timeout_s,
        store=store,
    )


def _require(value: str | None, field: str, channel: str) -> str:
    if not value:
        raise ValueError(f"channel {channel!r} is enabled but {field} is empty")
    return value


def _build_wecom(channel: Any) -> IMConnector:
    return _make_wecom(
        bot_id=_require(channel.bot_id, "bot_id", "wecom"),
        secret=_require(channel.secret, "secret", "wecom"),
        welcome_text=channel.welcome_text,
        reconnect_max_ms=channel.reconnect_max_ms,
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


def _build_wechat(channel: Any, store: Any = None) -> list[IMConnector]:
    """One connector instance per enabled account slot (legacy = one slot)."""
    return [
        _make_wechat(
            spec=spec,
            channel_enabled=channel.enabled,
            qr_timeout_s=channel.qr_timeout_s,
            store=store,
        )
        for spec in channel.bot_specs()
    ]


def build_enabled(config: Config, store: Any = None) -> list[IMConnector]:
    """Construct every connector whose channel is enabled in the config."""
    register_builtins()
    channels = config.channels
    specs = (
        (channels.wecom, _build_wecom),
        (channels.feishu, _build_feishu),
        (channels.qq, _build_qq),
    )
    connectors = [builder(channel) for channel, builder in specs if channel.enabled]
    if channels.wechat.enabled:
        connectors.extend(_build_wechat(channels.wechat, store=store))
    return connectors
