"""Shared test fixtures."""

import asyncio

import pytest

from tether.store.sqlite import _open_stores
from tether.util.logging import configure_logging


def pytest_configure(config: pytest.Config) -> None:
    """Use deterministic, non-JSON logging during tests."""
    configure_logging("INFO", json=False)


@pytest.fixture(autouse=True)
def _close_leaked_stores():
    """Close any RouteStore a test left connected.

    A store whose connection is never closed keeps its aiosqlite worker
    thread alive; once the test's event loop shuts down, the thread crashes
    with "Event loop is closed" (PytestUnhandledThreadExceptionWarning).
    Closing here drains the queue before the loop goes away. Uses a fresh
    loop so it also covers stores created outside the test's own loop.
    """
    yield
    for store in list(_open_stores):
        asyncio.run(store.close())
