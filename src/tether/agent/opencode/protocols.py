"""OpenCode HTTP protocol variants (v1.19.x and v2/master)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tether.agent.base import FormSpec, PromptFile, QuestionAnswer
from tether.agent.events import PendingQuestion
from tether.agent.opencode.events import (
    OpenCodeEventMapper,
    OpenCodeV1EventMapper,
    OpenCodeV2EventMapper,
)
from tether.agent.opencode.forms import (
    answer_payload,
    form_to_question,
    form_to_spec,
)


class OpenCodeProtocol:
    version: str
    supports_forms: bool
    questions_path: str

    def event_mapper(self) -> OpenCodeEventMapper:
        raise NotImplementedError

    def prompt_payload(
        self,
        prompt: str,
        files: Sequence[PromptFile | dict[str, Any]] | None,
        id: str | None,
        delivery: str,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def permission_payload(self, reply: str, message: str | None) -> dict[str, Any]:
        raise NotImplementedError

    def parse_questions(self, data: Any) -> list[PendingQuestion]:
        raise NotImplementedError

    def parse_forms(self, data: Any) -> list[FormSpec]:
        raise NotImplementedError

    def question_reply_payload(
        self,
        answer: QuestionAnswer | list[list[str]],
        *,
        fields: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def reject_question_request(
        self, sid: str, rid: str, message: str | None
    ) -> tuple[str, str, dict[str, str] | None]:
        raise NotImplementedError


class OpenCodeV1Protocol(OpenCodeProtocol):
    version = "v1"
    supports_forms = False
    questions_path = "/api/question/request"

    def event_mapper(self) -> OpenCodeEventMapper:
        return OpenCodeV1EventMapper()

    def prompt_payload(
        self,
        prompt: str,
        files: Sequence[PromptFile | dict[str, Any]] | None,
        id: str | None,
        delivery: str,
    ) -> dict[str, Any]:
        prompt_input: dict[str, Any] = {"text": prompt}
        if files:
            prompt_input["files"] = [prompt_file(item) for item in files]

        payload: dict[str, Any] = {"prompt": prompt_input, "delivery": delivery}
        if id and id.startswith("msg_"):
            payload["id"] = id

        return payload

    def permission_payload(self, reply: str, message: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"reply": reply}
        if message:
            payload["message"] = message

        return payload

    def parse_questions(self, data: Any) -> list[PendingQuestion]:
        return [
            PendingQuestion.from_json(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]

    def parse_forms(self, data: Any) -> list[FormSpec]:
        return []

    def question_reply_payload(
        self,
        answer: QuestionAnswer | list[list[str]],
        *,
        fields: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        answers = (
            list(answer.values.values())
            if isinstance(answer, QuestionAnswer)
            else answer
        )
        return {"answers": answers}

    def reject_question_request(
        self, sid: str, rid: str, message: str | None
    ) -> tuple[str, str, dict[str, str] | None]:
        return "POST", f"/api/session/{sid}/question/{rid}/reject", None


class OpenCodeV2Protocol(OpenCodeProtocol):
    version = "v2"
    supports_forms = True
    questions_path = "/api/form"

    def event_mapper(self) -> OpenCodeEventMapper:
        return OpenCodeV2EventMapper()

    def prompt_payload(
        self,
        prompt: str,
        files: Sequence[PromptFile | dict[str, Any]] | None,
        id: str | None,
        delivery: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": prompt, "delivery": delivery}
        if files:
            payload["files"] = [prompt_file(item) for item in files]

        if id and id.startswith("msg_"):
            payload["id"] = id

        return payload

    def permission_payload(self, reply: str, message: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"decision": reply}
        if message:
            payload["message"] = message

        return payload

    def parse_questions(self, data: Any) -> list[PendingQuestion]:
        out: list[PendingQuestion] = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict):
                question = form_to_question(item)
                if question is not None:
                    out.append(question)

        return out

    def parse_forms(self, data: Any) -> list[FormSpec]:
        return [
            form_to_spec(item)
            for item in (data if isinstance(data, list) else [])
            if isinstance(item, dict)
        ]

    def question_reply_payload(
        self,
        answer: QuestionAnswer | list[list[str]],
        *,
        fields: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fields = fields or {}

        if isinstance(answer, QuestionAnswer):
            values = answer_payload(answer, fields)
        else:
            keys = list(fields) or [f"q{index}" for index in range(len(answer))]
            values = {}

            for index, answers in enumerate(answer):
                key = keys[index] if index < len(keys) else f"q{index}"
                field = fields.get(key) or {}
                mapped = _option_values(field, answers)
                values[key] = (
                    list(mapped)
                    if field.get("type") == "multiselect"
                    else (mapped[0] if mapped else "")
                )

        return {"answer": values}

    def reject_question_request(
        self, sid: str, rid: str, message: str | None
    ) -> tuple[str, str, dict[str, str] | None]:
        return (
            "DELETE",
            f"/api/session/{sid}/form/{rid}",
            {"message": message or "The user dismissed this question"},
        )


def prompt_file(item: PromptFile | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, PromptFile):
        payload: dict[str, Any] = {"uri": item.uri}

        if item.name is not None:
            payload["name"] = item.name

        if item.description is not None:
            payload["description"] = item.description

        return payload
    return {
        key: value
        for key, value in item.items()
        if key in ("uri", "name", "description")
    }


def _option_values(field: dict[str, Any], values: list[str]) -> list[str]:
    lookup = {
        str(option.get("label")): str(option.get("value"))
        for option in (field.get("options") or [])
        if isinstance(option, dict)
    }
    return [lookup.get(str(value), str(value)) for value in values]


__all__ = ["OpenCodeProtocol", "OpenCodeV1Protocol", "OpenCodeV2Protocol"]
