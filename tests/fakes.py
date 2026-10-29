"""An in-memory stand-in for the agent client, used by the offline tests."""

from __future__ import annotations

import asyncio
from typing import Any

from tether.agent.agentd.messages import snapshot_messages
from tether.agent.base import BackendDescription, ConfigSummary, TurnSnapshot
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


class FakeAgentClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8787", token: str | None = None) -> None:
        self.base_url = base_url
        self.endpoint_id = base_url
        self.token = token
        self.sessions: dict[str, SessionInfo] = {}
        self.prompts: list[dict[str, Any]] = []
        self.interrupted: list[str] = []
        self.deleted: list[str] = []
        self.permission_replies: list[tuple[str, str, str]] = []
        self.question_replies: list[tuple[str, str, list[list[str]]]] = []
        self.form_replies: list[tuple[str, str, dict]] = []
        self.created_permissions: list[list] = []
        self.rejected_questions: list[tuple[str, str]] = []
        self._counter = 0
        self._permissions: list[PendingPermission] = []
        self._questions: list[PendingQuestion] = []
        self._events: asyncio.Queue[Any] = asyncio.Queue()
        self.tools: list[ToolInfo] = [ToolInfo("read"), ToolInfo("glob"), ToolInfo("grep")]
        self.models: list[ModelInfo] = [ModelInfo("m", "openai", ["text", "image"], [])]
        self.active: set[str] = set()
        self.message_store: dict[str, list[dict[str, Any]]] = {}
        self.replay_events: dict[str, list[Event]] = {}
        self.replay_requests: list[tuple[str, int]] = []
        self.agents: list[AgentInfo] = [AgentInfo("build", description="Build agent")]
        self.fail_next_prompt_with: str | tuple[str, str, int | None] | None = None
        self.permission_reply_error: str | None = None

    async def aclose(self) -> None:
        return None

    # discovery
    async def health(self):
        return True

    async def list_agents(self, *, location=None):
        return list(self.agents)

    async def list_models(self, *, location=None):
        return self.models

    async def agent_tools(self, agent: str, *, location=None):
        return self.tools

    async def get_config(self, *, section=None, server=None):
        return {"schemaVersion": 1, "sources": [], "config": {"models": [], "servers": []}}

    async def describe(self):
        return BackendDescription(
            backend_id="agentd",
            endpoint_id=self.base_url,
            version="test",
            pid=1,
            urls=["fake"],
        )

    async def config_summary(self, *, location=None):
        return ConfigSummary(
            default_agent="build",
            default_model="m",
            providers=[],
            agents=len(self.agents),
            models=len(self.models),
            locations=[self.base_url],
        )

    async def active_sessions(self):
        return set(self.active)

    # sessions
    async def create_session(
        self, *, agent, model=None, title=None, location=None, permissions=None
    ):
        self._counter += 1
        self.created_permissions.append(list(permissions or []))
        info = SessionInfo(
            id=f"ses_{self._counter}",
            agent=agent,
            model=model,
            title=title,
            location=location,
        )
        self.sessions[info.id] = info
        return info

    async def get_session(self, sid):
        info = self.sessions.get(sid)
        if info is None:
            raise AgentError("not_found")
        return info

    async def set_agent(self, sid, agent): ...
    async def set_model(self, sid, model_ref): ...
    async def set_title(self, sid, title): ...
    async def delete_session(self, sid):
        self.deleted.append(sid)

    # execution
    async def prompt(self, sid, *, prompt, files=None, id=None, delivery="queue"):
        if self.fail_next_prompt_with is not None:
            failure = self.fail_next_prompt_with
            self.fail_next_prompt_with = None
            if isinstance(failure, tuple):
                code, message, status = failure
                raise AgentError(code, message, status=status)
            raise AgentError(failure)
        self.prompts.append(
            {"sid": sid, "prompt": prompt, "files": files or [], "id": id, "delivery": delivery}
        )
        return {"queued": True}

    async def interrupt(self, sid):
        self.interrupted.append(sid)

    async def compact(self, sid):
        return True

    async def wait(self, sid, timeout_s):
        return True

    # read
    async def messages(self, sid, *, limit=200):
        return self.message_store.get(sid, [])

    async def history(self, sid, *, after=0, limit=200):
        return []

    async def turn_snapshot(self, sid, *, after_message_id=None):
        text, media = snapshot_messages(
            self.message_store.get(sid, []), after_message_id=after_message_id
        )
        return TurnSnapshot(text=text, media=media)

    async def session_replay(self, sid, *, after_seq=-1, limit=100):
        self.replay_requests.append((sid, after_seq))
        events = self.replay_events.get(sid, [])
        out = []
        for event in events:
            durable = event.durable if isinstance(event.durable, dict) else {}
            try:
                seq = int(durable.get("seq"))
            except (TypeError, ValueError):
                seq = None
            if seq is None or seq > after_seq:
                out.append(event)
        return out

    # interaction
    async def reply_permission(self, sid, rid, *, reply, message=None):
        if self.permission_reply_error is not None:
            code = self.permission_reply_error
            self.permission_reply_error = None
            raise AgentError(code)
        self.permission_replies.append((sid, rid, reply))
        self._permissions = [p for p in self._permissions if p.id != rid]

    async def reply_question(self, sid, rid, answers):
        self.question_replies.append((sid, rid, answers))
        self._questions = [q for q in self._questions if q.id != rid]

    async def reply_form(self, sid, rid, answer):
        self.form_replies.append((sid, rid, answer.values))

    async def reject_question(self, sid, rid):
        self.rejected_questions.append((sid, rid))
        self._questions = [q for q in self._questions if q.id != rid]

    async def list_permissions(self, *, locations=None):
        return list(self._permissions)

    async def session_permissions(self, sid):
        return [p for p in self._permissions if p.session_id == sid]

    async def list_questions(self, *, locations=None):
        return list(self._questions)

    async def session_questions(self, sid):
        return [q for q in self._questions if q.session_id == sid]

    def add_permission(self, perm: PendingPermission) -> None:
        self._permissions.append(perm)

    def add_question(self, question: PendingQuestion) -> None:
        self._questions.append(question)

    def push_event(self, event: Any) -> None:
        self._events.put_nowait(event)

    async def events(self):
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event
