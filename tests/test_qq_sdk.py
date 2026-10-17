from __future__ import annotations

import json

import pytest

from tether.connectors.qq.sdk import QQClient, _FatalGatewayError


def client(session: str | None = "s") -> QQClient:
    conn = QQClient("app", "secret")
    conn._session_id = session
    return conn


@pytest.mark.parametrize("code", [4006, 4007, 4008, 4900, 4913])
def test_identify_codes(code):
    assert client()._close_action(code) == "identify"


def test_expired_session_resumes_or_identifies():
    # 4009 asks for a resume; without a session only a fresh Identify can work.
    assert client("s")._close_action(4009) == "resume"
    assert client(None)._close_action(4009) == "identify"


def test_normal_drop_resumes_when_a_session_exists():
    assert client("s")._close_action(1006) == "resume"
    assert client(None)._close_action(1006) == "identify"
    assert client("s")._close_action(None) == "resume"


@pytest.mark.parametrize("code", [4001, 4002, 4010, 4011, 4012, 4013, 4014, 4914, 4915])
def test_fatal_codes_give_up(code):
    with pytest.raises(_FatalGatewayError):
        client()._close_action(code)


@pytest.mark.asyncio
async def test_invalid_session_drops_the_session_and_closes():
    class FakeWS:
        closed = False

        async def close(self):
            self.closed = True

    conn = client("s")
    ws = FakeWS()
    conn._ws = ws
    await conn._dispatch(json.dumps({"op": 9}), lambda _e, _d: None)
    assert conn._session_id is None
    assert ws.closed


@pytest.mark.asyncio
async def test_any_frame_clears_the_missed_ack_count():
    conn = client()
    conn._missed_acks = 5
    await conn._dispatch(json.dumps({"op": 11}), lambda _e, _d: None)
    assert conn._missed_acks == 0
