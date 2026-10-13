from __future__ import annotations

import httpx
import pytest
from fakes import FakeAgentClient

from tether.app import TetherApp
from tether.config import Config
from tether.connectors.fake import FakeConnector


async def _app(tmp_path) -> TetherApp:
    config = Config()
    config.metrics.listen = "127.0.0.1:0"
    config.metrics.log_interval_s = 0
    conn = FakeConnector()
    app = TetherApp(
        config,
        db_path=str(tmp_path / "t.db"),
        connectors=[conn],
        client_factory=lambda base, token: FakeAgentClient(),
    )
    await app.store.connect()
    app.connectors[conn.name] = conn
    return app


@pytest.mark.asyncio
async def test_metrics_endpoint_serves_health_and_metrics(tmp_path):
    app = await _app(tmp_path)
    await app._start_metrics()
    assert app.metrics_port
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get(f"http://127.0.0.1:{app.metrics_port}/healthz")
            assert health.status_code in (200, 503)
            body = health.json()
            assert "connectors" in body and "uptime_s" in body and "agentd" in body

            metrics = await client.get(f"http://127.0.0.1:{app.metrics_port}/metrics")
            assert metrics.status_code == 200
            assert "tether_uptime_seconds" in metrics.text
    finally:
        await app._stop_metrics()
