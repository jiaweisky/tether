"""HTTP/SSE adapter for the OpenCode v2 server API."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from tether.agent.base import (
    BackendDescription,
    BackendProfile,
    ConfigSummary,
    FormAnswer,
    FormSpec,
    PermissionRule,
    PromptFile,
    QuestionAnswer,
    TurnSnapshot,
)
from tether.agent.errors import AgentError
from tether.agent.events import (
    AgentInfo,
    Event,
    ModelInfo,
    PendingPermission,
    PendingQuestion,
    SessionInfo,
    ToolInfo,
)
from tether.agent.opencode import config as config_module
from tether.agent.opencode.events import OpenCodeEventMapper
from tether.agent.opencode.forms import form_answer_payload
from tether.agent.opencode.messages import snapshot_messages
from tether.agent.opencode.models import format_model_ref, parse_model_ref
from tether.agent.opencode.protocols import (
    OpenCodeProtocol,
    OpenCodeV1Protocol,
    OpenCodeV2Protocol,
)
from tether.util.logging import get_logger

log = get_logger("tether.opencode")


class OpenCodeBackend:
    """Talk to one ``opencode serve`` instance over its v2 HTTP/SSE API."""

    profile = BackendProfile(
        backend_id="opencode",
        display_name="OpenCode",
        supports_tool_discovery=False,
        supports_session_replay=False,
        supports_cross_session_permissions=True,
        supports_cross_session_questions=True,
        supports_rich_forms=True,
        supports_session_wait=True,
        supports_session_title=True,
        supports_isolated_projects=True,
        supports_multi_location=True,
        supports_changed_files=True,
        supports_pending_interaction_recovery=False,
        event_protocol="opencode.v2",
    )

    def __init__(
        self,
        base_url: str,
        *,
        username: str = "opencode",
        password: str | None = None,
        endpoint_id: str | None = None,
        location: str | None = None,
        timeout: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint_id = endpoint_id or self.base_url
        self.location = location
        self.username = username
        self.password = password
        self._own_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)
        self._protocol: OpenCodeProtocol | None = None
        self._events: OpenCodeEventMapper | None = None

    async def aclose(self) -> None:
        if self._own_client:
            await self._client.aclose()

    # -- low level ---------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        if not self.password:
            return {}
        value = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return {"Authorization": f"Basic {value}"}

    async def _ensure_protocol(self) -> OpenCodeProtocol:
        if self._protocol is not None:
            return self._protocol

        protocol: OpenCodeProtocol = OpenCodeV2Protocol()
        try:
            doc = await self._request_body("GET", "/doc")
            props = (
                doc.get("paths", {})
                .get("/api/session/{sessionID}/prompt", {})
                .get("post", {})
                .get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
                .get("properties", {})
                if isinstance(doc, dict)
                else {}
            )
            if isinstance(props, dict) and "prompt" in props:
                protocol = OpenCodeV1Protocol()
        except (AgentError, AttributeError, TypeError) as exc:
            log.warning("opencode_protocol_detection_failed", error=str(exc))

        self._protocol = protocol
        self._events = protocol.event_mapper()
        self.profile = replace(
            self.profile,
            supports_rich_forms=protocol.supports_forms,
            event_protocol=f"opencode.{protocol.version}",
        )
        log.info(
            "opencode_protocol_detected",
            endpoint=self.endpoint_id,
            version=protocol.version,
        )
        return protocol

    def _location_params(self, location: str | None) -> dict[str, str]:
        selected = location or self.location
        return {"location[directory]": selected} if selected else {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        location: str | None = None,
        **kwargs: Any,
    ) -> Any:
        body = await self._request_body(method, path, location=location, **kwargs)
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    async def _request_body(
        self,
        method: str,
        path: str,
        *,
        location: str | None = None,
        **kwargs: Any,
    ) -> Any:
        params = dict(kwargs.pop("params", {}) or {})
        params.update(self._location_params(location))
        try:
            resp = await self._client.request(
                method,
                self._url(path),
                headers={**self._headers(), **dict(kwargs.pop("headers", {}) or {})},
                params=params or None,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            raise AgentError("unavailable", str(exc)) from exc
        except httpx.HTTPError as exc:
            raise AgentError("unavailable", str(exc)) from exc

        if resp.status_code >= 400:
            raise _error_from_response(resp)

        if resp.status_code == 204 or not resp.content:
            return {}
        return _json_or_empty(resp)

    # -- discovery ---------------------------------------------------------
    async def health(self) -> bool:
        try:
            health = await self._request("GET", "/api/health", location=self.location)
        except AgentError:
            health = None
        if isinstance(health, dict) and health.get("healthy") is not None:
            return bool(health["healthy"])

        try:
            info = await self._request("GET", "/api/info", location=self.location)
        except AgentError:
            info = None
        if isinstance(info, dict) and (info.get("version") or info.get("pid") is not None):
            return True

        try:
            models = await self._request("GET", "/api/model", location=self.location)
        except AgentError:
            return False
        return isinstance(models, list)

    async def describe(self) -> BackendDescription:
        info = await self._request("GET", "/api/info", location=self.location)
        return config_module.describe(
            info if isinstance(info, dict) else {},
            endpoint_id=self.endpoint_id,
            locations=[self.location] if self.location else [],
        )

    async def config_summary(self, *, location: str | None = None) -> ConfigSummary:
        entries = await self._request("GET", "/api/config", location=location or self.location)
        return config_module.summary(entries)

    async def list_agents(self, *, location: str | None = None) -> list[AgentInfo]:
        data = await self._request("GET", "/api/agent", location=location)
        agents: list[AgentInfo] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            agents.append(
                AgentInfo(
                    id=str(item.get("id") or ""),
                    description=_string_or_none(item.get("description")),
                    mode=_string_or_none(item.get("mode")),
                    hidden=bool(item.get("hidden")),
                    model=format_model_ref(item.get("model")),
                    backend="opencode",
                )
            )

        if not agents:
            agents.append(
                AgentInfo(
                    id="build",
                    description="OpenCode default agent",
                    mode="primary",
                    hidden=False,
                    backend="opencode",
                )
            )
        return agents

    async def list_models(self, *, location: str | None = None) -> list[ModelInfo]:
        data = await self._request("GET", "/api/model", location=location)
        models: list[ModelInfo] = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("providerID") or "")
            model_id = str(item.get("modelID") or item.get("id") or "")
            if not provider or not model_id:
                continue
            capabilities = item.get("capabilities")
            capabilities = capabilities if isinstance(capabilities, dict) else {}
            limit = item.get("limit")
            limit = limit if isinstance(limit, dict) else {}
            inputs = [str(value) for value in (capabilities.get("input") or [])]
            context_limit = _int_or_none(limit.get("context"))
            output_limit = _int_or_none(limit.get("output"))
            models.append(
                ModelInfo(
                    id=f"{provider}/{model_id}",
                    protocol=provider,
                    inputs=inputs,
                    sources=[],
                    context_limit=context_limit,
                    output_limit=output_limit,
                )
            )
            for variant in item.get("variants") or []:
                if not isinstance(variant, dict) or not variant.get("id"):
                    continue
                models.append(
                    ModelInfo(
                        id=f"{provider}/{model_id}#{variant['id']}",
                        protocol=provider,
                        inputs=inputs,
                        sources=[],
                        context_limit=context_limit,
                        output_limit=output_limit,
                    )
                )
        return models

    async def agent_tools(
        self, agent: str, *, location: str | None = None
    ) -> list[ToolInfo]:
        return []

    async def active_sessions(self) -> set[str]:
        data = await self._request("GET", "/api/session/active")
        if isinstance(data, dict):
            return {str(key) for key in data}
        if isinstance(data, list):
            return {str(item.get("id")) for item in data if isinstance(item, dict)}
        return set()

    # -- session -----------------------------------------------------------
    async def create_session(
        self,
        *,
        agent: str,
        model: str | None = None,
        title: str | None = None,
        location: str | None = None,
        permissions: list[PermissionRule] | None = None,
    ) -> SessionInfo:
        payload: dict[str, Any] = {}
        if agent:
            payload["agent"] = agent
        if title:
            payload["title"] = title
        if model:
            payload["model"] = await self._model_ref(model, location)

        directory = location or self.location
        if directory:
            payload["location"] = {"directory": directory}
        if permissions is not None:
            payload["permissions"] = [
                {"action": item.action, "resource": item.resource, "effect": item.effect}
                for item in permissions
            ]

        data = await self._request("POST", "/api/session", json=payload)
        return _session_info(data if isinstance(data, dict) else {})

    async def get_session(self, sid: str) -> SessionInfo:
        data = await self._request("GET", f"/api/session/{sid}")
        return _session_info(data if isinstance(data, dict) else {})

    async def set_agent(self, sid: str, agent: str) -> None:
        await self._request("POST", f"/api/session/{sid}/agent", json={"agent": agent})

    async def set_model(self, sid: str, model: str) -> None:
        await self._request(
            "POST",
            f"/api/session/{sid}/model",
            json={"model": await self._model_ref(model, self.location)},
        )

    async def set_title(self, sid: str, title: str) -> None:
        await self._request("PATCH", f"/api/session/{sid}", json={"title": title})

    async def delete_session(self, sid: str) -> None:
        await self._request("DELETE", f"/api/session/{sid}")

    # -- execution ---------------------------------------------------------
    async def prompt(
        self,
        sid: str,
        *,
        prompt: str,
        files: Sequence[PromptFile | dict[str, Any]] | None = None,
        id: str | None = None,
        delivery: str = "queue",
    ) -> None:
        protocol = await self._ensure_protocol()
        await self._request(
            "POST",
            f"/api/session/{sid}/prompt",
            json=protocol.prompt_payload(prompt, files, id, delivery),
        )

    async def interrupt(self, sid: str) -> None:
        await self._request("POST", f"/api/session/{sid}/interrupt")

    async def run_command(self, sid: str, name: str, text: str = "") -> None:
        await self._request(
            "POST",
            f"/api/session/{sid}/command",
            json={"name": name, "text": text},
        )

    async def activate_skill(
        self, sid: str, skill_id: str, *, resume: bool = True
    ) -> None:
        await self._request(
            "POST",
            f"/api/experimental/session/{sid}/skill",
            json={"id": skill_id, "resume": resume},
        )

    async def compact(self, sid: str) -> bool:
        data = await self._request("POST", f"/api/session/{sid}/compact")
        return bool(data)

    async def wait(self, sid: str, timeout_s: float) -> bool:
        try:
            await asyncio.wait_for(
                self._request("POST", f"/api/experimental/session/{sid}/wait"),
                timeout=timeout_s,
            )
        except TimeoutError:
            return False
        return True

    # -- read / recovery ---------------------------------------------------
    async def messages(self, sid: str, *, limit: int = 200) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(messages) < 4000:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            else:
                params["order"] = "asc"
            body = await self._request_body(
                "GET", f"/api/session/{sid}/message", params=params
            )
            if not isinstance(body, dict):
                break
            page = body.get("data")
            if isinstance(page, list):
                messages.extend(item for item in page if isinstance(item, dict))
            cursor_data = body.get("cursor")
            cursor = cursor_data.get("next") if isinstance(cursor_data, dict) else None
            if not cursor:
                break
        return messages

    async def turn_snapshot(
        self, sid: str, *, after_message_id: str | None = None
    ) -> TurnSnapshot:
        return snapshot_messages(
            await self.messages(sid), after_message_id=after_message_id
        )

    async def session_replay(
        self, sid: str, *, after_seq: int = -1
    ) -> list[Event]:
        return []

    # -- interaction -------------------------------------------------------
    async def reply_permission(
        self, sid: str, rid: str, *, reply: str, message: str | None = None
    ) -> None:
        protocol = await self._ensure_protocol()
        await self._request(
            "POST",
            f"/api/session/{sid}/permission/{rid}/reply",
            json=protocol.permission_payload(reply, message),
        )

    async def reply_question(
        self, sid: str, rid: str, answer: QuestionAnswer | list[list[str]]
    ) -> None:
        protocol = await self._ensure_protocol()
        fields = await self._form_fields(sid, rid) if protocol.supports_forms else None
        path = (
            f"/api/session/{sid}/form/{rid}/reply"
            if protocol.supports_forms
            else f"/api/session/{sid}/question/{rid}/reply"
        )
        await self._request(
            "POST",
            path,
            json=protocol.question_reply_payload(answer, fields=fields),
        )

    async def reply_form(self, sid: str, rid: str, answer: FormAnswer) -> None:
        protocol = await self._ensure_protocol()
        if not protocol.supports_forms:
            raise AgentError("bad_request", "this OpenCode version does not support forms")
        await self._request(
            "POST",
            f"/api/session/{sid}/form/{rid}/reply",
            json={"answer": form_answer_payload(answer)},
        )

    async def reject_question(
        self, sid: str, rid: str, *, message: str | None = None
    ) -> None:
        protocol = await self._ensure_protocol()
        method, path, params = protocol.reject_question_request(sid, rid, message)
        await self._request(method, path, params=params)

    def _selected_locations(
        self, locations: Sequence[str] | None
    ) -> list[str | None]:
        if locations:
            return list(locations)
        return [self.location] if self.location else [None]

    async def list_permissions(
        self, *, locations: Sequence[str] | None = None
    ) -> list[PendingPermission]:
        selected = self._selected_locations(locations)
        out: dict[str, PendingPermission] = {}
        for location in selected:
            data = await self._request(
                "GET", "/api/permission/request", location=location
            )
            for item in data if isinstance(data, list) else []:
                if not isinstance(item, dict):
                    continue
                request = PendingPermission.from_json(item)
                out[request.id] = request
        return list(out.values())

    async def list_questions(
        self, *, locations: Sequence[str] | None = None
    ) -> list[PendingQuestion]:
        protocol = await self._ensure_protocol()
        selected = self._selected_locations(locations)
        out: dict[str, PendingQuestion] = {}
        for location in selected:
            data = await self._request(
                "GET", protocol.questions_path, location=location
            )
            for question in protocol.parse_questions(data):
                out[question.id] = question
        return list(out.values())

    async def session_permissions(self, sid: str) -> list[PendingPermission]:
        data = await self._request("GET", f"/api/session/{sid}/permission")
        return [
            PendingPermission.from_json(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]

    async def list_forms(
        self, *, locations: Sequence[str] | None = None
    ) -> list[FormSpec]:
        protocol = await self._ensure_protocol()
        if not protocol.supports_forms:
            return []
        selected = self._selected_locations(locations)
        out: dict[str, FormSpec] = {}
        for location in selected:
            data = await self._request("GET", "/api/form", location=location)
            for spec in protocol.parse_forms(data):
                if spec.id:
                    out[spec.id] = spec
        return list(out.values())

    async def session_forms(self, sid: str) -> list[FormSpec]:
        protocol = await self._ensure_protocol()
        if not protocol.supports_forms:
            return []
        data = await self._request("GET", f"/api/session/{sid}/form")
        return protocol.parse_forms(data)

    async def session_questions(self, sid: str) -> list[PendingQuestion]:
        protocol = await self._ensure_protocol()
        path = (
            f"/api/session/{sid}/form"
            if protocol.supports_forms
            else f"/api/session/{sid}/question"
        )
        return protocol.parse_questions(await self._request("GET", path))

    async def _model_ref(self, value: str, location: str | None) -> dict[str, Any]:
        try:
            return parse_model_ref(value)
        except ValueError:
            pass

        matches = [
            model.id
            for model in await self.list_models(location=location)
            if model.id == value or model.id.split("#", 1)[0].split("/", 1)[-1] == value
        ]
        if len(matches) != 1:
            raise AgentError("bad_request", f"unknown or ambiguous model: {value!r}")
        return parse_model_ref(matches[0])

    async def _form_fields(self, sid: str, rid: str) -> dict[str, dict[str, Any]]:
        try:
            data = await self._request("GET", f"/api/session/{sid}/form/{rid}")
        except AgentError:
            return {}
        form = data if isinstance(data, dict) else {}
        return {
            str(field.get("key")): field
            for field in (form.get("fields") or [])
            if isinstance(field, dict) and field.get("key")
        }

    # -- events ------------------------------------------------------------
    async def events(self) -> AsyncIterator[Event]:
        await self._ensure_protocol()
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
                    raw = _parse_json(sse.data)
                    if raw is None:
                        continue
                    if self._events is not None:
                        for event in self._events.map_many(raw):
                            yield event
        except httpx.HTTPError as exc:
            raise AgentError("unavailable", str(exc)) from exc


def _session_info(data: dict[str, Any]) -> SessionInfo:
    location = data.get("location")
    return SessionInfo(
        id=str(data.get("id") or ""),
        agent=_string_or_none(data.get("agent")),
        model=format_model_ref(data.get("model")),
        title=_string_or_none(data.get("title")),
        location=str(location.get("directory")) if isinstance(location, dict) else None,
    )


def _error_from_response(resp: httpx.Response) -> AgentError:
    body = _json_or_empty(resp)
    tag = str(body.get("_tag") or "") if isinstance(body, dict) else ""
    message = str(body.get("message") or "") if isinstance(body, dict) else ""
    code = {
        "SessionNotFoundError": "not_found",
        "PermissionNotFoundError": "not_found",
        "FormNotFoundError": "not_found",
        "MessageNotFoundError": "not_found",
        "UnauthorizedError": "unauthorized",
        "ConflictError": "conflict",
        "SessionBusyError": "conflict",
        "FormAlreadySettledError": "conflict",
        "InvalidRequestError": "bad_request",
        "SchemaError": "bad_request",
        "ServiceUnavailableError": "unavailable",
    }.get(tag, "internal")
    return AgentError(code, message or tag, status=resp.status_code)


def _json_or_empty(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {}


def _parse_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["OpenCodeBackend"]
