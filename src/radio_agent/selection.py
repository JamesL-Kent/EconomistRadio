from __future__ import annotations

from datetime import datetime, timedelta
from math import inf

from radio_agent.config import RadioSettings
from radio_agent.models import ContentBand, ContentItem, HistorySnapshot, SelectionResult


class PlaylistSelector:
    """Chooses the next feature while balancing freshness and variety."""

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings

    def choose_next(
        self,
        items: list[ContentItem],
        history: HistorySnapshot,
        now: datetime,
    ) -> SelectionResult | None:
        candidates = self._build_candidates(items, history, now)
        if not candidates:
            return None

        target_band = self._target_band(candidates, history.recent_bands())
        filtered = [candidate for candidate in candidates if candidate.band == target_band]
        if not filtered:
            filtered = candidates
        return max(filtered, key=lambda candidate: candidate.score)

    def _build_candidates(
        self,
        items: list[ContentItem],
        history: HistorySnapshot,
        now: datetime,
    ) -> list[SelectionResult]:
        candidates: list[SelectionResult] = []
        cooldown = timedelta(hours=self._settings.scheduling.repeat_cooldown_hours)
        for item in items:
            band = item.band(now, self._settings.scheduling.minimum_archive_score)
            if band is ContentBand.STALE:
                continue

            last_played_at = history.last_played_at.get(item.content_id)
            if last_played_at and now - last_played_at < cooldown:
                continue

            score = self._score_item(item, band, history, now)
            reason = f"{band.value} score {score:.2f}"
            candidates.append(SelectionResult(item=item, band=band, score=score, reason=reason))
        return candidates

    def _target_band(
        self,
        candidates: list[SelectionResult],
        recent_bands: list[ContentBand],
    ) -> ContentBand:
        available = {candidate.band for candidate in candidates}
        since_week = self._distance_since(recent_bands, ContentBand.WEEK)
        since_archive = self._distance_since(recent_bands, ContentBand.ARCHIVE)
        has_history = bool(recent_bands)

        # Archive and weekly pieces are deliberate editorial inserts, not the default first choice.
        if (
            has_history
            and ContentBand.ARCHIVE in available
            and since_archive >= self._settings.scheduling.archive_injection_interval
        ):
            return ContentBand.ARCHIVE
        if ContentBand.TODAY in available:
            if (
                has_history
                and ContentBand.WEEK in available
                and since_week >= self._settings.scheduling.week_injection_interval
            ):
                return ContentBand.WEEK
            return ContentBand.TODAY
        if (
            has_history
            and ContentBand.WEEK in available
            and since_week >= self._settings.scheduling.week_injection_interval
        ):
            return ContentBand.WEEK
        if ContentBand.WEEK in available:
            return ContentBand.WEEK
        return ContentBand.ARCHIVE

    def _distance_since(self, recent_bands: list[ContentBand], target: ContentBand) -> int:
        for index, band in enumerate(recent_bands, start=1):
            if band is target:
                return index
        return inf

    def _score_item(
        self,
        item: ContentItem,
        band: ContentBand,
        history: HistorySnapshot,
        now: datetime,
    ) -> float:
        schedule = self._settings.scheduling
        if band is ContentBand.TODAY:
            base = schedule.today_priority_weight
            freshness = max(0.1, 1.5 - (item.age_hours(now) / 24.0))
        elif band is ContentBand.WEEK:
            base = schedule.week_priority_weight
            freshness = max(0.2, 1.2 - (item.age_hours(now) / 168.0))
        else:
            base = schedule.archive_priority_weight
            freshness = 1.0

        play_count = history.play_counts.get(item.content_id, 0)
        penalty = schedule.history_penalty * play_count
        score = base * freshness
        score += item.interesting_score * schedule.interesting_bonus
        if item.evergreen:
            score += schedule.evergreen_bonus
        return score - penalty
