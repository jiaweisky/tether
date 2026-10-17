from __future__ import annotations

import base64
import json
import os

import httpx
import pytest
import respx

from tether.connectors.wechat.client import (
    STALE_TOKEN_ERRCODE,
    WeChatAuthError,
    WeChatClient,
    decrypt_ecb,
    encrypt_ecb,
    padded_size,
    parse_aes_key,
)


def test_aes_ecb_round_trip_and_padding():
    key = os.urandom(16)
    data = b"hello wechat" * 10
    encrypted = encrypt_ecb(data, key)
    assert len(encrypted) == padded_size(len(data))
    assert decrypt_ecb(encrypted, key) == data


def test_parse_aes_key_accepts_raw_and_hex_base64():
    raw = os.urandom(16)
    assert parse_aes_key(base64.b64encode(raw).decode()) == raw
    assert (
        parse_aes_key(base64.b64encode(raw.hex().encode()).decode())
        == raw
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_updates_sends_headers_and_parses_messages():
    route = respx.post("https://api.example/ilink/bot/getupdates").mock(
        return_value=httpx.Response(
            200,
            json={"ret": 0, "msgs": [{"message_id": "1", "item_list": []}],
                  "get_updates_buf": "next"},
        )
    )
    client = WeChatClient(base_url="https://api.example", token="tok")
    response = await client.get_updates("cursor")
    assert response["get_updates_buf"] == "next"
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer tok"
    assert request.headers["AuthorizationType"] == "ilink_bot_token"
    assert request.headers["iLink-App-Id"] == "bot"
    assert request.headers["X-WECHAT-UIN"]
    body = json.loads(request.content)
    assert body["get_updates_buf"] == "cursor"
    assert body["base_info"]["bot_agent"].startswith("Tether/")


@pytest.mark.asyncio
@respx.mock
async def test_stale_token_raises_auth_error():
    respx.post("https://api.example/ilink/bot/getupdates").mock(
        return_value=httpx.Response(
            200, json={"ret": STALE_TOKEN_ERRCODE, "errmsg": "expired"}
        )
    )
    client = WeChatClient(base_url="https://api.example", token="tok")
    with pytest.raises(WeChatAuthError):
        await client.get_updates()


@pytest.mark.asyncio
@respx.mock
async def test_send_message_carries_context_and_item():
    route = respx.post("https://api.example/ilink/bot/sendmessage").mock(
        return_value=httpx.Response(200, json={"ret": 0, "message_id": "srv-1"})
    )
    client = WeChatClient(base_url="https://api.example", token="tok")
    response = await client.send_message(
        {
            "to_user_id": "u1",
            "client_id": "c1",
            "message_type": 2,
            "message_state": 2,
            "context_token": "ctx",
            "item_list": [{"type": 1, "text_item": {"text": "hi"}}],
        }
    )
    assert response["message_id"] == "srv-1"
    body = json.loads(route.calls[0].request.content)
    assert body["msg"]["context_token"] == "ctx"
    assert body["msg"]["item_list"][0]["text_item"]["text"] == "hi"


@pytest.mark.asyncio
@respx.mock
async def test_get_qr_uses_unauthenticated_headers():
    route = respx.post("https://api.example/ilink/bot/get_bot_qrcode?bot_type=3").mock(
        return_value=httpx.Response(
            200, json={"qrcode": "q1", "qrcode_img_content": "https://qr"}
        )
    )
    client = WeChatClient(base_url="https://api.example")
    payload = await client.get_qr()
    assert payload["qrcode"] == "q1"
    request = route.calls[0].request
    assert "Authorization" not in request.headers
    assert request.headers["AuthorizationType"] == "ilink_bot_token"


@pytest.mark.asyncio
@respx.mock
async def test_poll_qr_redirects_base_url():
    redirect = respx.get("https://redirect.example/ilink/bot/get_qrcode_status").mock(
        return_value=httpx.Response(200, json={"status": "wait"})
    )
    client = WeChatClient(base_url="https://api.example")
    status = await client.poll_qr("q1", base_url="https://redirect.example")
    assert status["status"] == "wait"
    assert redirect.called
    assert client.base_url == "https://api.example"
