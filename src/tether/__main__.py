"""Command-line entry point: ``tether --config config.yaml``."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal

from dotenv import load_dotenv

from tether.app import TetherApp
from tether.config import default_db_path, load_config
from tether.store.sqlite import DatabaseInUseError
from tether.util.logging import configure_logging, get_logger

# How long a graceful shutdown may take before the process is force-exited.
SHUTDOWN_TIMEOUT_S = 15.0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tether", description="IM bridge for go-agent-sdk")

    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="path to config.yaml (default: %(default)s)",
    )

    parser.add_argument(
        "--db",
        default=None,
        help="state SQLite path (routes + WeChat tokens); default: "
        "<config dir>/.tether/<config name>/state.sqlite3",
    )

    return parser.parse_args(argv)


async def _run(config_path: str, db_path: str | None) -> None:
    # Load secrets from .env (does not override already-set environment).
    load_dotenv()

    config = load_config(config_path)
    if db_path is None:
        db_path = str(default_db_path(config_path))

    configure_logging(config.logging.level, config.logging.json_logs)
    log = get_logger("tether")

    app = TetherApp(config, db_path=db_path, config_path=config_path)

    stop_event = asyncio.Event()
    presses = 0
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        nonlocal presses
        presses += 1
        if presses >= 2:  # a second interrupt forces exit even if shutdown is stuck
            log.warning("force_exit")
            os._exit(1)
        log.info("shutdown_requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    log.info("starting", config=config_path, db=db_path)

    try:
        await app.start()
    except (ValueError, DatabaseInUseError) as exc:  # report cleanly, not a traceback
        log.error("startup_failed", error=str(exc))
        return

    try:
        await stop_event.wait()
    finally:
        try:
            await asyncio.wait_for(app.stop(), timeout=SHUTDOWN_TIMEOUT_S)
        except TimeoutError:
            log.error("shutdown_timed_out", timeout_s=SHUTDOWN_TIMEOUT_S)
            os._exit(1)
        except Exception:  # noqa: BLE001 - shutdown must always finish
            log.exception("shutdown_failed")
            os._exit(1)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    try:
        asyncio.run(_run(args.config, args.db))
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":
    main()
