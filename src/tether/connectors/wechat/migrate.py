"""One-time import of the old per-bot JSON credentials into SQLite."""

from __future__ import annotations

import json
from pathlib import Path

from tether.config import Config, WeChatBotConfig
from tether.connectors.wechat.storage import WeChatCredential, WeChatState
from tether.store.sqlite import (
    RouteStore,
    WeChatBindingConflict,
    WeChatRebindRequired,
)
from tether.util.logging import get_logger

log = get_logger("tether.wechat.migrate")

_LEGACY_DIR = "~/.tether/wechat"


async def migrate_legacy_wechat_files(config: Config, store: RouteStore) -> None:
    """Import ``~/.tether/wechat/<id>.json`` (+state) into the DB, then delete.

    A file is removed only after its credential/state rows are committed. A
    conflict or malformed file is left in place and logged.
    """
    for bot in config.channels.wechat.bots:
        await _migrate_one(bot, store)


async def _migrate_one(bot: WeChatBotConfig, store: RouteStore) -> None:
    path = Path(_LEGACY_DIR).expanduser() / f"{bot.id}.json"  # noqa: ASYNC240
    if not path.is_file():
        return

    state_path = Path(str(path) + ".state.json")
    existing = await store.wechat_account(bot.id)
    if existing is not None and existing.get("token"):
        # The DB already has a token (possibly newer); never overwrite it with
        # a stale legacy file.
        _remove_legacy_files(bot.id, path, state_path)
        log.info("wechat_legacy_skipped_existing", bot=bot.id, path=str(path))
        return

    credential = _read_credential(bot, path)
    if credential is None:
        return

    try:
        await _save_credential(store, bot.id, credential)
        await _import_state(store, bot.id, state_path)
    except (WeChatBindingConflict, WeChatRebindRequired) as exc:
        log.warning(
            "wechat_legacy_import_conflict",
            bot=bot.id,
            error=str(exc),
            path=str(path),
        )
        return
    except Exception:  # noqa: BLE001 - never block startup on a migration
        log.exception("wechat_legacy_import_failed", bot=bot.id, path=str(path))
        return

    _remove_legacy_files(bot.id, path, state_path)
    log.info("wechat_legacy_imported", bot=bot.id, path=str(path))


def _read_credential(bot: WeChatBotConfig, path: Path) -> WeChatCredential | None:
    try:
        raw = json.loads(path.read_text())
        credential = (
            WeChatCredential.from_dict(raw) if isinstance(raw, dict) else None
        )
    except (OSError, ValueError):
        log.warning("wechat_legacy_import_failed", bot=bot.id, path=str(path))
        return None

    if credential is None:
        log.warning("wechat_legacy_import_invalid", bot=bot.id, path=str(path))

    return credential


async def _save_credential(
    store: RouteStore, slot: str, credential: WeChatCredential
) -> None:
    if credential.bot_id:
        await store.save_wechat_login(
            slot,
            credential.bot_id,
            credential.token,
            credential.base_url,
            credential.user_id,
        )
    else:
        await store.save_wechat_token(
            slot,
            credential.token,
            credential.base_url,
            credential.user_id,
        )


async def _import_state(store: RouteStore, slot: str, state_path: Path) -> None:
    if not state_path.is_file():  # noqa: ASYNC240
        return
    try:
        raw = json.loads(state_path.read_text())  # noqa: ASYNC240
        state = WeChatState.from_dict(raw) if isinstance(raw, dict) else WeChatState()
    except (OSError, ValueError):
        return

    if state.cursor:
        await store.save_wechat_cursor(slot, state.cursor)

    for peer, token in state.context_tokens.items():
        await store.save_wechat_context_token(slot, peer, token)


def _remove_legacy_files(bot_id: str, path: Path, state_path: Path) -> None:
    try:
        path.unlink()  # noqa: ASYNC240
        state_path.unlink(missing_ok=True)  # noqa: ASYNC240
    except OSError:
        log.warning("wechat_legacy_cleanup_failed", bot=bot_id, path=str(path))
