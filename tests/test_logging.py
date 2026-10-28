from __future__ import annotations

import pytest

from tether.util import logging as logging_util

_CONFIGURE = logging_util.configure_logging


@pytest.fixture(autouse=True)
def _reset_logging():
    logging_util._configured = False
    yield
    logging_util._configured = False
    _CONFIGURE("INFO", json=False)


def test_get_logger_does_not_configure_logging(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        logging_util, "configure_logging", lambda *args, **kwargs: calls.append((args, kwargs))
    )

    logging_util.get_logger("tether.test.side_effect")

    assert calls == []


def test_configuration_applies_to_a_logger_created_earlier(capsys):
    log = logging_util.get_logger("tether.test.early")
    logging_util.configure_logging("INFO", json=False)

    log.debug("hidden-debug")
    log.info("visible-info", key="value")

    out = capsys.readouterr().out
    assert "visible-info" in out
    assert "hidden-debug" not in out
    assert not out.lstrip().startswith("{")


def test_configuration_honors_json(capsys):
    logging_util.configure_logging("WARNING", json=True)
    log = logging_util.get_logger("tether.test.json")

    log.info("hidden-info")
    log.warning("visible-warning", key="value")

    out = capsys.readouterr().out
    assert '"event": "visible-warning"' in out
    assert "hidden-info" not in out
