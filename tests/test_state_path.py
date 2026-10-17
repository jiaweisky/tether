from __future__ import annotations

import asyncio
import os

import pytest

from tether.config import default_db_path
from tether.store.sqlite import DatabaseInUseError, RouteStore


def test_default_db_path_is_config_relative(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("{}")
    assert default_db_path(config) == tmp_path / ".tether" / "config" / "state.sqlite3"


def test_default_db_path_uses_the_config_name(tmp_path):
    config = tmp_path / "prod.yaml"
    config.write_text("{}")
    assert default_db_path(config) == tmp_path / ".tether" / "prod" / "state.sqlite3"


def test_cli_leaves_the_db_unset_for_the_config_relative_default():
    from tether.__main__ import _parse_args

    assert _parse_args(["--config", "prod.yaml"]).db is None


def test_default_db_path_sanitizes_the_instance_name(tmp_path):
    config = tmp_path / "my config.yaml"
    config.write_text("{}")
    assert default_db_path(config) == tmp_path / ".tether" / "my_config" / "state.sqlite3"


@pytest.mark.asyncio
async def test_a_state_db_can_only_be_opened_by_one_process(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = RouteStore(path)
    await first.connect()
    second = RouteStore(path)
    with pytest.raises(DatabaseInUseError):
        await second.connect()
    await first.close()
    await second.connect()
    await second.close()


@pytest.mark.asyncio
async def test_memory_store_does_not_create_a_lock_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = RouteStore(":memory:")
    await store.connect()
    await store.close()
    assert not await asyncio.to_thread(os.path.exists, "state.sqlite3.lock")
