"""HTTP and SSE client for the agent service.

Only the endpoints the bridge uses are exposed. Successful responses are wrapped
in ``{"data": ...}`` and errors as ``{"error": code, "message": ...}``; both are
unwrapped here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from .errors import AgentError
from .events import (
    AgentInfo,
    Event,
    ModelInfo,
    PendingPermission,
    PendingQuestion,
    SessionInfo,
    ToolInfo,
)


class HttpAgentClient:
    """Talk to one agent service instance over HTTP, plus its SSE event stream."""

    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._own_client = client is None
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers
        )

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    # -- low level ---------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._client.request(
                method, self._url(path), headers=self._headers(), **kwargs
            )
        except httpx.HTTPError as exc:
            raise AgentError("unavailable", str(exc)) from exc
        if resp.status_code >= 400:
            raise _error_from_response(resp)
        return _data_from_response(resp)

    # -- discovery ---------------------------------------------------------
    async def health(self) -> bool:
        data = await self._request("GET", "/api/health")
        return bool(data.get("healthy")) if isinstance(data, dict) else False

    async def get_config(
        self, *, section: str | None = None, server: str | None = None
    ) -> dict[str, Any]:
        """agentd's redacted effective configuration (`GET /api/config`)."""
        params = {k: v for k, v in (("section", section), ("server", server)) if v}
        data = await self._request("GET", "/api/config", params=params)
        return data if isinstance(data, dict) else {}

    async def get_info(self) -> dict[str, Any]:
        """agentd's server info (`GET /api/info`): version, pid, addresses."""
        data = await self._request("GET", "/api/info")
        return data if isinstance(data, dict) else {}

    async def list_agents(self) -> list[AgentInfo]:
        data = await self._request("GET", "/api/agent") or []
        return [
            AgentInfo(
                id=str(a.get("id", "")),
                description=a.get("description"),
                mode=a.get("mode"),
                hidden=bool(a.get("hidden")),
                model=a.get("model"),
                backend=a.get("backend"),
            )
            for a in data
        ]

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/api/model") or []
        out: list[ModelInfo] = []
        for m in data:
            raw_input = m.get("input")
            if isinstance(raw_input, list):
                inputs = [str(x) for x in raw_input]
            elif isinstance(raw_input, str):
                inputs = [raw_input]
            else:
                inputs = []
            out.append(
                ModelInfo(
                    id=str(m.get("id", "")),
                    protocol=m.get("protocol"),
                    inputs=inputs,
                    sources=[str(s) for s in (m.get("sources") or [])],
                    context_limit=_as_int(m.get("contextLimit")),
                    output_limit=_as_int(m.get("outputLimit")),
                )
            )
        return out

    async def agent_tools(self, agent: str) -> list[ToolInfo]:
        data = await self._request("GET", "/api/tool", params={"agent": agent}) or []
        return [
            ToolInfo(name=str(t.get("name", "")), description=t.get("description")) for t in data
        ]

    async def active_sessions(self) -> dict[str, dict[str, Any]]:
        data = await self._request("GET", "/api/session/active") or {}
        return dict(data) if isinstance(data, dict) else {}

    # -- session -----------------------------------------------------------
    async def create_session(
        self, *, agent: str, model: str | None = None, title: str | None = None
    ) -> SessionInfo:
        payload: dict[str, Any] = {"agent": agent}
        if model:
            payload["model"] = model
        if title:
            payload["title"] = title
        data = await self._request("POST", "/api/session", json=payload) or {}
        return _session_info(data)

    async def get_session(self, sid: str) -> SessionInfo:
        data = await self._request("GET", f"/api/session/{sid}") or {}
        return _session_info(data)

    async def set_agent(self, sid: str, agent: str) -> None:
        await self._request("POST", f"/api/session/{sid}/agent", json={"agent": agent})

    async def set_model(self, sid: str, model_ref: dict[str, Any]) -> None:
        await self._request("POST", f"/api/session/{sid}/model", json=model_ref)

    async def set_title(self, sid: str, title: str) -> None:
        await self._request("POST", f"/api/session/{sid}/title", json={"title": title})

    async def delete_session(self, sid: str) -> None:
        await self._request("DELETE", f"/api/session/{sid}")

    # -- execution ---------------------------------------------------------
    async def prompt(
        self,
        sid: str,
        *,
        prompt: str,
        files: list[dict[str, Any]] | None = None,
        id: str | None = None,
        delivery: str = "queue",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": prompt, "delivery": delivery}
        if id:
            payload["id"] = id
        if files:
            payload["files"] = files
        data = await self._request("POST", f"/api/session/{sid}/prompt", json=payload)
        return data if isinstance(data, dict) else {}

    async def interrupt(self, sid: str) -> None:
        await self._request("POST", f"/api/session/{sid}/interrupt")

    async def compact(self, sid: str) -> bool:
        data = await self._request("POST", f"/api/session/{sid}/compact") or {}
        return bool(data.get("compacted")) if isinstance(data, dict) else False

    async def wait(self, sid: str, timeout_s: float) -> bool:
        data = (
            await self._request(
                "POST", f"/api/session/{sid}/wait", params={"timeout": f"{int(timeout_s)}s"}
            )
            or {}
        )
        return bool(data.get("idle")) if isinstance(data, dict) else False

    # -- read --------------------------------------------------------------
    async def messages(self, sid: str, *, limit: int = 200) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/api/session/{sid}/message", params={"limit": limit})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("messages") or data.get("data") or [])
        return []

    async def history(self, sid: str, *, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"/api/session/{sid}/history", params={"after": after, "limit": limit}
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.get("events") or data.get("data") or [])
        return []

    # -- interaction -------------------------------------------------------
    async def reply_permission(
        self, sid: str, rid: str, *, reply: str, message: str | None = None
    ) -> None:
        payload: dict[str, Any] = {"reply": reply}
        if message:
            payload["message"] = message
        await self._request("POST", f"/api/session/{sid}/permission/{rid}/reply", json=payload)

    async def reply_question(self, sid: str, rid: str, answers: list[list[str]]) -> None:
        await self._request(
            "POST", f"/api/session/{sid}/question/{rid}/reply", json={"answers": answers}
        )

    async def reject_question(self, sid: str, rid: str) -> None:
        await self._request("POST", f"/api/session/{sid}/question/{rid}/reject")

    async def list_permissions(self) -> list[PendingPermission]:
        data = await self._request("GET", "/api/permission") or []
        return [PendingPermission.from_json(p) for p in data]

    async def session_permissions(self, sid: str) -> list[PendingPermission]:
        data = await self._request("GET", f"/api/session/{sid}/permission") or []
        return [PendingPermission.from_json(p) for p in data]

    async def list_questions(self) -> list[PendingQuestion]:
        data = await self._request("GET", "/api/question") or []
        return [PendingQuestion.from_json(q) for q in data]

    async def session_questions(self, sid: str) -> list[PendingQuestion]:
        data = await self._request("GET", f"/api/session/{sid}/question") or []
        return [PendingQuestion.from_json(q) for q in data]

    # -- events ------------------------------------------------------------
    async def events(self) -> AsyncIterator[Event]:
        """Yield events from the global ``/api/event`` stream.

        Live-only deltas and interaction events are included. The generator
        raises on disconnect; the caller reconnects and reconciles.
        """
        try:
            async with aconnect_sse(
                self._client,
                "GET",
                self._url("/api/event"),
                headers={**self._headers(), "Accept": "text/event-stream"},
                timeout=None,
            ) as source:
                if source.response.status_code >= 400:
                    raise AgentError("unavailable", status=source.response.status_code)
                async for sse in source.aiter_sse():
                    if sse.event == "error":
                        raise AgentError("unavailable", sse.data)
                    event = _event_from_sse(sse.data)
                    if event is not None:
                        yield event
        except httpx.HTTPError as exc:
            raise AgentError("unavailable", str(exc)) from exc


def _event_from_sse(payload: str | None) -> Event | None:
    data = _parse_json(payload)
    if data is None:
        return None
    return Event(
        id=str(data.get("id", "")),
        type=str(data.get("type", "")),
        data=dict(data.get("data") or {}),
        durable=data.get("durable"),
    )


def _error_from_response(resp: httpx.Response) -> AgentError:
    code, message, ref = "internal", "", None
    body = _json_or_empty(resp)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            code = str(error.get("code", code))
            message = str(error.get("message", ""))
            ref = error.get("ref")
        elif isinstance(error, str):
            code = error
            message = str(body.get("message", ""))
        ref = ref or body.get("ref")
    return AgentError(code, message, status=resp.status_code, ref=ref)


def _data_from_response(resp: httpx.Response) -> Any:
    if resp.status_code == 204 or not resp.content:
        return {}
    body = _json_or_empty(resp)
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


def _json_or_empty(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {}


def _session_info(data: dict[str, Any]) -> SessionInfo:
    return SessionInfo(
        id=str(data.get("id", "")),
        agent=data.get("agent"),
        model=_model_id(data.get("model")),
        title=data.get("title"),
    )


def _model_id(model: Any) -> str | None:
    """agentd reports a session's model as a reference object; take its id."""
    if isinstance(model, dict):
        value = model.get("id")
        return str(value) if value is not None else None
    if model is None:
        return None
    return str(model)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


AgentClient = HttpAgentClient
