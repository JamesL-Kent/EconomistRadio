from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from radio_agent.config import HostSettings, RadioSettings
from radio_agent.models import ContentItem
from radio_agent.script_writer import HostScriptWriter


def test_script_writer_removes_banned_phrases_and_respects_word_limit() -> None:
    settings = RadioSettings(
        host=HostSettings(
            opener_templates=["Don't go anywhere on {station_name}."],
            teaser_templates=["{title}: {summary}."],
            max_link_words=8,
        )
    )
    writer = HostScriptWriter(settings)
    item = ContentItem(
        content_id="feature-1",
        title="The Budget Debate",
        audio_path=Path("/tmp/feature-1.mp3"),
        published_at=datetime(2026, 3, 20, 6, 0, tzinfo=ZoneInfo("Europe/London")),
        section="Politics",
        summary="A longer explanation of the fiscal arguments dominating Westminster",
    )

    script = writer.build_script(
        item,
        now=datetime(2026, 3, 20, 9, 0, tzinfo=ZoneInfo("Europe/London")),
    )

    assert "don't go anywhere" not in script.text.lower()
    assert script.word_count <= 8
    assert script.text.endswith(".")
