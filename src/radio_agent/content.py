from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from pathlib import Path

import yaml

from radio_agent.config import RadioSettings
from radio_agent.models import ContentItem
from radio_agent.timezones import load_timezone


class ContentLibrary:
    """Scans the configured content tree and turns files into playable items."""

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings
        self._timezone = load_timezone(settings.station.timezone)

    def scan(self) -> list[ContentItem]:
        root = self._settings.content.root_path
        if not root.exists():
            return []

        items: list[ContentItem] = []
        for audio_path in sorted(root.rglob("*")):
            if not audio_path.is_file():
                continue
            if audio_path.suffix.lower() not in self._settings.content.audio_extensions:
                continue
            metadata_path = self._find_metadata(audio_path)
            metadata = self._load_metadata(metadata_path) if metadata_path else {}
            items.append(self._build_item(audio_path, metadata_path, metadata))

        items.sort(key=lambda item: item.published_at, reverse=True)
        return items

    def _find_metadata(self, audio_path: Path) -> Path | None:
        for extension in self._settings.content.metadata_extensions:
            candidate = audio_path.with_suffix(extension)
            if candidate.exists():
                return candidate
        return None

    def _load_metadata(self, metadata_path: Path) -> dict:
        if metadata_path.suffix.lower() == ".json":
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        return yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}

    def _build_item(self, audio_path: Path, metadata_path: Path | None, metadata: dict) -> ContentItem:
        relative_path = audio_path.relative_to(self._settings.content.root_path)
        published_at = self._resolve_published_at(audio_path, metadata)
        interesting_score = self._parse_score(metadata.get("interesting_score"))
        raw_tags = metadata.get("tags", [])
        if isinstance(raw_tags, str):
            tags = (raw_tags,)
        else:
            tags = tuple(str(tag) for tag in raw_tags)
        title = str(metadata.get("title") or audio_path.stem.replace("-", " ").replace("_", " ").title())
        section = str(metadata.get("section") or relative_path.parent.name or "General")
        content_id = str(metadata.get("content_id") or self._hash_path(relative_path))
        return ContentItem(
            content_id=content_id,
            title=title,
            audio_path=audio_path.resolve(),
            published_at=published_at,
            section=section,
            summary=str(metadata.get("summary") or metadata.get("dek") or "").strip(),
            tags=tags,
            interesting_score=max(0.0, min(interesting_score, 1.0)),
            evergreen=bool(metadata.get("evergreen", False)),
            source_url=metadata.get("source_url"),
            metadata_path=metadata_path.resolve() if metadata_path else None,
            announcer_intro=metadata.get("announcer_intro"),
            duration_seconds=self._parse_duration(metadata.get("duration_seconds")),
            raw_metadata=metadata,
        )

    def _resolve_published_at(self, audio_path: Path, metadata: dict) -> datetime:
        value = metadata.get("published_at")
        if isinstance(value, str) and value:
            parsed = self._parse_datetime(value)
            if parsed:
                return parsed

        parent_name = audio_path.parent.name
        try:
            published_date = date.fromisoformat(parent_name)
            return datetime.combine(published_date, time(hour=6), tzinfo=self._timezone)
        except ValueError:
            pass

        modified = datetime.fromtimestamp(audio_path.stat().st_mtime, tz=self._timezone)
        return modified

    def _parse_datetime(self, raw: str) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(raw), time(hour=6), tzinfo=self._timezone)
            except ValueError:
                return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self._timezone)
        return parsed.astimezone(self._timezone)

    def _parse_duration(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _parse_score(self, value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _hash_path(self, relative_path: Path) -> str:
        digest = hashlib.sha1(str(relative_path).encode("utf-8")).hexdigest()
        return digest[:16]
