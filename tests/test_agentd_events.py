from __future__ import annotations

import pytest

from tether.agent.agentd.events import AGENTD_EVENT_MAP, from_agentd_event
from tether.agent.events import (
    COMPACTION_DELTA,
    COMPACTION_ENDED,
    COMPACTION_STARTED,
    PERMISSION_ASKED,
    PERMISSION_REPLIED,
    QUESTION_ASKED,
    QUESTION_REJECTED,
    QUESTION_REPLIED,
    REASONING_DELTA,
    REASONING_ENDED,
    REASONING_STARTED,
    STEP_ENDED,
    STEP_FAILED,
    STEP_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    TEXT_STARTED,
    TITLE_UPDATED,
    TOOL_CALLED,
    TOOL_FAILED,
    TOOL_PROGRESS,
    TOOL_SUCCESS,
    TURN_STATUS,
    TextData,
    TurnStatusData,
)


@pytest.mark.parametrize(
    ("native", "neutral"),
    [
        ("session.status", TURN_STATUS),
        ("session.next.text.started", TEXT_STARTED),
        ("session.next.text.delta", TEXT_DELTA),
        ("session.next.text.ended", TEXT_ENDED),
        ("session.next.reasoning.started", REASONING_STARTED),
        ("session.next.reasoning.delta", REASONING_DELTA),
        ("session.next.reasoning.ended", REASONING_ENDED),
        ("session.next.tool.called", TOOL_CALLED),
        ("session.next.tool.progress", TOOL_PROGRESS),
        ("session.next.tool.success", TOOL_SUCCESS),
        ("session.next.tool.failed", TOOL_FAILED),
        ("session.next.step.started", STEP_STARTED),
        ("session.next.step.ended", STEP_ENDED),
        ("session.next.step.failed", STEP_FAILED),
        ("session.next.compaction.started", COMPACTION_STARTED),
        ("session.next.compaction.delta", COMPACTION_DELTA),
        ("session.next.compaction.ended", COMPACTION_ENDED),
        ("session.next.title.updated", TITLE_UPDATED),
        ("permission.v2.asked", PERMISSION_ASKED),
        ("permission.v2.replied", PERMISSION_REPLIED),
        ("question.v2.asked", QUESTION_ASKED),
        ("question.v2.replied", QUESTION_REPLIED),
        ("question.v2.rejected", QUESTION_REJECTED),
    ],
)
def test_agentd_event_mapping(native: str, neutral: str):
    event = from_agentd_event(
        {
            "id": "e1",
            "type": native,
            "data": {"sessionID": "ses_1"},
        }
    )
    assert event is not None
    assert AGENTD_EVENT_MAP[native] == neutral
    assert event.type == neutral
    assert event.session_id == "ses_1"


def test_agentd_event_keeps_unknown_type_and_durable_session():
    event = from_agentd_event(
        {
            "id": "e1",
            "type": "session.created",
            "data": {},
            "durable": {"aggregateID": "ses_durable", "seq": 3},
        }
    )
    assert event is not None
    assert event.type == "session.created"
    assert event.session_id == "ses_durable"


def test_agentd_event_payload_is_typed():
    delta = from_agentd_event(
        {
            "id": "e1",
            "type": "session.next.text.delta",
            "data": {"sessionID": "ses_1", "delta": "hi"},
        }
    )
    assert delta is not None
    assert isinstance(delta.data, TextData)
    assert delta.data.delta == "hi"

    status = from_agentd_event(
        {
            "id": "e2",
            "type": "session.status",
            "data": {"sessionID": "ses_1", "status": {"type": "retry", "attempt": 2}},
        }
    )
    assert status is not None
    assert isinstance(status.data, TurnStatusData)
    assert status.data.status.type == "retry"
    assert status.data.status.attempt == 2
