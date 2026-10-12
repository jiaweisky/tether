from __future__ import annotations

from tether.capabilities import Capabilities, MarkdownLevel
from tether.models import RichDoc, RichMedia, TextSegment, Usage
from tether.render.renderer import DefaultRenderer


def caps(max_chars: int = 4000) -> Capabilities:
    return Capabilities(markdown=MarkdownLevel.RICH, max_text_chars=max_chars)


def test_plain_text_single_segment():
    plan = DefaultRenderer().render(RichDoc(markdown="hello"), caps())
    assert len(plan.segments) == 1
    assert isinstance(plan.segments[0], TextSegment)
    assert plan.segments[0].text == "hello"


def test_images_become_media_segments():
    doc = RichDoc(markdown="see ![x](http://i/x.png)")
    plan = DefaultRenderer().render(doc, caps())
    assert any(getattr(s, "kind", "") == "media" for s in plan.segments)


def test_long_text_chunked_with_sequence_numbers():
    doc = RichDoc(markdown=("word " * 300).strip())
    plan = DefaultRenderer().render(doc, caps(max_chars=200))
    texts = [s.text for s in plan.segments if isinstance(s, TextSegment)]
    assert len(texts) > 1
    assert texts[0].endswith(f"(1/{len(texts)})")


def test_usage_line_appended():
    doc = RichDoc(
        markdown="done",
        usage=Usage(
            input_tokens=1200,
            output_tokens=456,
            cost=0.003,
            context_tokens=12000,
            context_limit=128000,
        ),
    )
    plan = DefaultRenderer(show_usage=True).render(doc, caps())
    text = plan.segments[-1].text
    assert "context 12.0k/128.0k (9%)" in text
    assert "$0.0030" in text


def test_no_usage_when_disabled():
    doc = RichDoc(markdown="done", usage=Usage(input_tokens=10))
    plan = DefaultRenderer(show_usage=False).render(doc, caps())
    assert "📊" not in plan.segments[-1].text


def test_media_segment_carries_richmedia():
    from tether.models import MediaSegment

    doc = RichDoc(markdown="", media=[RichMedia(kind="image", data=b"x", mime="image/png")])
    plan = DefaultRenderer().render(doc, caps())
    assert isinstance(plan.segments[0], MediaSegment)
