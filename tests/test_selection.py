from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from radio_agent.config import RadioSettings
from radio_agent.models import ContentBand, ContentItem, HistorySnapshot, PlayEvent
from radio_agent.selection import PlaylistSelector


def make_item(
    content_id: str,
    published_at: datetime,
    *,
    interesting_score: float = 0.0,
    evergreen: bool = False,
) -> ContentItem:
    return ContentItem(
        content_id=content_id,
        title=content_id,
        audio_path=Path(f"/tmp/{content_id}.mp3"),
        published_at=published_at,
        section="Finance",
        summary="A concise update",
        interesting_score=interesting_score,
        evergreen=evergreen,
    )


def make_history(bands: list[ContentBand], now: datetime) -> HistorySnapshot:
    events = tuple(
        PlayEvent(
            content_id=f"played-{index}",
            title=f"played-{index}",
            band=band,
            played_at=now - timedelta(hours=index + 1),
            duration_seconds=1200,
            program_id=f"programme-{index}",
            script_text="link text",
        )
        for index, band in enumerate(bands)
    )
    return HistorySnapshot(recent_events=events, play_counts={}, last_played_at={})


def test_selector_prefers_today_when_station_has_no_history() -> None:
    timezone = ZoneInfo("Europe/London")
    now = datetime(2026, 3, 20, 9, 0, tzinfo=timezone)
    selector = PlaylistSelector(RadioSettings())

    today_item = make_item("today", now - timedelta(hours=2))
    archive_item = make_item(
        "archive",
        now - timedelta(days=30),
        interesting_score=0.95,
        evergreen=True,
    )

    selection = selector.choose_next(
        [archive_item, today_item],
        HistorySnapshot(recent_events=(), play_counts={}, last_played_at={}),
        now,
    )

    assert selection is not None
    assert selection.item.content_id == "today"
    assert selection.band is ContentBand.TODAY


def test_selector_injects_weekly_piece_after_run_of_today_items() -> None:
    timezone = ZoneInfo("Europe/London")
    now = datetime(2026, 3, 20, 9, 0, tzinfo=timezone)
    selector = PlaylistSelector(RadioSettings())

    today_item = make_item("today", now - timedelta(hours=1))
    week_item = make_item("week", now - timedelta(days=3), interesting_score=0.4)

    history = make_history(
        [ContentBand.TODAY, ContentBand.TODAY, ContentBand.TODAY, ContentBand.TODAY],
        now,
    )
    selection = selector.choose_next([today_item, week_item], history, now)

    assert selection is not None
    assert selection.item.content_id == "week"
    assert selection.band is ContentBand.WEEK
