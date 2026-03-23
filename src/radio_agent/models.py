from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ContentBand(str, Enum):
    """High-level freshness groups used by the scheduler."""

    TODAY = "today"
    WEEK = "week"
    ARCHIVE = "archive"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class ContentItem:
    """Single playable source item discovered in the content library."""

    content_id: str
    title: str
    audio_path: Path
    published_at: datetime
    section: str = "General"
    summary: str = ""
    tags: tuple[str, ...] = ()
    interesting_score: float = 0.0
    evergreen: bool = False
    source_url: str | None = None
    metadata_path: Path | None = None
    announcer_intro: str | None = None
    duration_seconds: float | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def band(self, now: datetime, minimum_archive_score: float) -> ContentBand:
        """Classify the item by recency and editorial interest."""
        age = now - self.published_at
        if age.total_seconds() < 0:
            return ContentBand.TODAY
        if age.days < 1:
            return ContentBand.TODAY
        if age.days < 7:
            return ContentBand.WEEK
        if self.evergreen or self.interesting_score >= minimum_archive_score:
            return ContentBand.ARCHIVE
        return ContentBand.STALE

    def age_hours(self, now: datetime) -> float:
        return max((now - self.published_at).total_seconds() / 3600.0, 0.0)


@dataclass(frozen=True, slots=True)
class PlayEvent:
    """A single completed programme block."""

    content_id: str
    title: str
    band: ContentBand
    played_at: datetime
    duration_seconds: float
    program_id: str
    script_text: str


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    """Compressed playback history used by the selector."""

    recent_events: tuple[PlayEvent, ...]
    play_counts: dict[str, int]
    last_played_at: dict[str, datetime]

    def recent_bands(self) -> list[ContentBand]:
        return [event.band for event in self.recent_events]


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Chosen item and the reasoning score behind the choice."""

    item: ContentItem
    band: ContentBand
    score: float
    reason: str


@dataclass(frozen=True, slots=True)
class HostLinkScript:
    """Final host-link text passed to the synthesiser."""

    text: str
    teaser_title: str
    word_count: int


@dataclass(frozen=True, slots=True)
class SegmentArtifact:
    """Single media segment published into the live stream."""

    local_path: Path
    uri: str
    duration_seconds: float


@dataclass(slots=True)
class EngineSnapshot:
    """Operational status returned by the API."""

    running: bool
    stream_url: str
    playlist_path: str
    buffer_seconds: float
    content_items: int
    last_program_id: str | None = None
    last_title: str | None = None
    last_error: str | None = None
