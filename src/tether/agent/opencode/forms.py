"""Map OpenCode Forms to the neutral pending-question model."""

from __future__ import annotations

from typing import Any

from tether.agent.base import (
    FormAnswer,
    FormField,
    FormOption,
    FormSpec,
    QuestionAnswer,
)
from tether.agent.events import PendingQuestion, QuestionItem, QuestionOption


def form_to_spec(form: dict[str, Any]) -> FormSpec:
    fields: list[FormField] = []
    for field in form.get("fields") or []:
        if not isinstance(field, dict):
            continue
        fields.append(
            FormField(
                key=str(field.get("key") or f"field{len(fields)}"),
                type=str(field.get("type") or ""),
                title=_optional_str(field.get("title")),
                description=_optional_str(field.get("description")),
                required=bool(field.get("required")),
                hidden=bool(field.get("hidden")),
                custom=bool(field.get("custom")),
                default=field.get("default"),
                options=[
                    FormOption(
                        value=str(option.get("value") or option.get("label") or ""),
                        label=str(option.get("label") or option.get("value") or ""),
                        description=_optional_str(option.get("description")),
                    )
                    for option in (field.get("options") or [])
                    if isinstance(option, dict)
                ],
                when=[
                    dict(condition)
                    for condition in (field.get("when") or [])
                    if isinstance(condition, dict)
                ],
            )
        )

    return FormSpec(
        id=str(form.get("id") or ""),
        session_id=str(form.get("sessionID") or ""),
        title=str(form.get("title") or ""),
        fields=fields,
        metadata=dict(form.get("metadata") or {}),
    )


def form_to_question(form: dict[str, Any]) -> PendingQuestion | None:
    metadata = form.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("kind") != "question":
        return None

    questions: list[QuestionItem] = []
    for field in form.get("fields") or []:
        if not isinstance(field, dict):
            continue
        field_type = str(field.get("type") or "")
        if field_type not in ("string", "multiselect"):
            continue

        options = [
            QuestionOption(
                label=str(option.get("label") or option.get("value") or ""),
                value=str(option.get("value") or option.get("label") or ""),
                description=str(option.get("description") or ""),
            )
            for option in (field.get("options") or [])
            if isinstance(option, dict)
        ]
        questions.append(
            QuestionItem(
                key=str(field.get("key") or f"q{len(questions)}"),
                question=str(
                    field.get("description") or field.get("title") or field.get("key") or ""
                ),
                header=str(field.get("title") or field.get("key") or ""),
                options=options,
                multiple=field_type == "multiselect",
                custom=bool(field.get("custom")),
            )
        )

    if not questions:
        return None

    return PendingQuestion(
        id=str(form.get("id") or ""),
        session_id=str(form.get("sessionID") or ""),
        questions=questions,
    )


def form_answer_payload(answer: FormAnswer) -> dict[str, Any]:
    return dict(answer.values)


def answer_payload(
    answer: QuestionAnswer, fields_by_key: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, values in answer.values.items():
        field = fields_by_key.get(key) or {}
        if field.get("type") == "multiselect":
            payload[key] = list(values)
        else:
            payload[key] = values[0] if values else ""
    return payload


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


__all__ = [
    "answer_payload",
    "form_answer_payload",
    "form_to_question",
    "form_to_spec",
]
