from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from radio_agent.models import ContentBand, HistorySnapshot, PlayEvent


class RadioStateStore:
    """SQLite-backed state for playback history and TTS cache lookups."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS play_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    band TEXT NOT NULL,
                    played_at TEXT NOT NULL,
                    duration_seconds REAL NOT NULL,
                    program_id TEXT NOT NULL UNIQUE,
                    script_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS synth_cache (
                    cache_key TEXT PRIMARY KEY,
                    audio_path TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_play_history_content_id
                ON play_history (content_id);

                CREATE INDEX IF NOT EXISTS idx_play_history_played_at
                ON play_history (played_at DESC);
                """
            )

    def history_snapshot(self, limit: int = 32) -> HistorySnapshot:
        with self._connect() as connection:
            recent_rows = connection.execute(
                """
                SELECT content_id, title, band, played_at, duration_seconds, program_id, script_text
                FROM play_history
                ORDER BY played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            count_rows = connection.execute(
                """
                SELECT content_id, COUNT(*) AS total_plays, MAX(played_at) AS last_played_at
                FROM play_history
                GROUP BY content_id
                """
            ).fetchall()

        recent_events = tuple(
            PlayEvent(
                content_id=row["content_id"],
                title=row["title"],
                band=ContentBand(row["band"]),
                played_at=datetime.fromisoformat(row["played_at"]),
                duration_seconds=float(row["duration_seconds"]),
                program_id=row["program_id"],
                script_text=row["script_text"],
            )
            for row in recent_rows
        )
        play_counts = {row["content_id"]: int(row["total_plays"]) for row in count_rows}
        last_played_at = {
            row["content_id"]: datetime.fromisoformat(row["last_played_at"])
            for row in count_rows
            if row["last_played_at"]
        }
        return HistorySnapshot(
            recent_events=recent_events,
            play_counts=play_counts,
            last_played_at=last_played_at,
        )

    def record_play(self, event: PlayEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO play_history (
                    content_id,
                    title,
                    band,
                    played_at,
                    duration_seconds,
                    program_id,
                    script_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.content_id,
                    event.title,
                    event.band.value,
                    event.played_at.isoformat(),
                    event.duration_seconds,
                    event.program_id,
                    event.script_text,
                ),
            )

    def get_cached_synth_path(self, cache_key: str) -> Path | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT audio_path FROM synth_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        path = Path(row["audio_path"])
        return path if path.exists() else None

    def remember_synth_path(self, cache_key: str, audio_path: Path, voice_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO synth_cache (cache_key, audio_path, voice_id, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    audio_path = excluded.audio_path,
                    voice_id = excluded.voice_id,
                    created_at = excluded.created_at
                """,
                (cache_key, str(audio_path), voice_id, datetime.utcnow().isoformat()),
            )
