"""Command-line entry point: ``tether --config config.yaml``."""

from __future__ import annotations

import argparse
import asyncio
import signal

from .app import TetherApp
from .config import load_config
from .util.logging import configure_logging, get_logger


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tether", description="IM bridge for go-agent-sdk")
    parser.add_argument("--config", "-c", default="config.yaml", help="path to config.yaml")
    parser.add_argument("--db", default="tether.sqlite3", help="route store SQLite path")
    return parser.parse_args(argv)


async def _run(config_path: str, db_path: str) -> None:
    config = load_config(config_path)
    configure_logging(config.logging.level, config.logging.json_logs)
    log = get_logger("tether")
    app = TetherApp(config, db_path=db_path)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - Windows
            pass

    log.info("starting", config=config_path)
    await app.start()
    try:
        await stop_event.wait()
    finally:
        await app.stop()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    try:
        asyncio.run(_run(args.config, args.db))
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":
    main()
