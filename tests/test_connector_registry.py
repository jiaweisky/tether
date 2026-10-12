from __future__ import annotations

from tether.connector import IMConnector, known_connectors, register_connector


class _Dummy:
    name = "dummy"
    capabilities = None


def test_registering_a_connector_makes_it_known():
    assert "dummy" not in known_connectors()
    register_connector("dummy", lambda **_: _Dummy())
    assert "dummy" in known_connectors()


def test_runtime_checkable_protocol_accepts_a_connector():
    from tether.connectors.fake import FakeConnector

    assert isinstance(FakeConnector(), IMConnector)
