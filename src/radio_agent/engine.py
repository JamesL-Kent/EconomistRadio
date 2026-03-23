from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from radio_agent.audio import AudioAssembler
from radio_agent.config import RadioSettings
from radio_agent.content import ContentLibrary
from radio_agent.models import ContentBand, ContentItem, EngineSnapshot, PlayEvent
from radio_agent.playlist import LivePlaylistWriter
from radio_agent.publisher import build_publisher
from radio_agent.script_writer import HostScriptWriter
from radio_agent.selection import PlaylistSelector
from radio_agent.state import RadioStateStore
from radio_agent.timezones import load_timezone
from radio_agent.tts import build_cache_key, build_synthesizer

LOGGER = logging.getLogger(__name__)


class RadioEngine:
    """Long-running loop that keeps the stream buffered ahead of real time."""

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings
        self._timezone = load_timezone(settings.station.timezone)
        self._library = ContentLibrary(settings)
        self._selector = PlaylistSelector(settings)
        self._script_writer = HostScriptWriter(settings)
        self._state = RadioStateStore(settings.runtime.state_db_path)
        self._tts = build_synthesizer(settings)
        self._audio = AudioAssembler(settings)
        self._publisher = build_publisher(settings)
        self._playlist = LivePlaylistWriter(settings, self._publisher)

        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._last_item: ContentItem | None = None
        self._last_program_id: str | None = None
        self._last_error: str | None = None
        self._content_items = 0
        self._stream_end_at = datetime.now(self._timezone)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task

    def snapshot(self) -> EngineSnapshot:
        return EngineSnapshot(
            running=bool(self._task and not self._task.done()),
            stream_url=self._settings.stream_url,
            playlist_path=str(self._settings.playlist_path),
            buffer_seconds=self.buffer_seconds(),
            content_items=self._content_items,
            last_program_id=self._last_program_id,
            last_title=self._last_item.title if self._last_item else None,
            last_error=self._last_error,
        )

    def buffer_seconds(self) -> float:
        remaining = (self._stream_end_at - datetime.now(self._timezone)).total_seconds()
        return max(0.0, remaining)

    async def _run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._maintain_buffer()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # pragma: no cover - defensive for service stability
                message = str(error)
                if message != self._last_error:
                    LOGGER.exception("Radio engine loop failed: %s", error)
                else:
                    LOGGER.warning("Radio engine loop still failing: %s", error)
                self._last_error = message
                await asyncio.sleep(self._settings.station.scan_interval_seconds)

    async def _maintain_buffer(self) -> None:
        buffer_seconds = self.buffer_seconds()
        # Keep the stream only a few minutes ahead of wall clock so it behaves like live radio.
        if buffer_seconds >= self._settings.output.target_buffer_seconds:
            pause = min(
                self._settings.station.scan_interval_seconds,
                max(2.0, buffer_seconds - self._settings.output.target_buffer_seconds),
            )
            await asyncio.sleep(pause)
            return

        # Re-scan on every cycle so newly arrived audio can enter the stream without a restart.
        items = await asyncio.to_thread(self._library.scan)
        self._content_items = len(items)
        if not items:
            await asyncio.sleep(self._settings.station.scan_interval_seconds)
            return

        history = await asyncio.to_thread(self._state.history_snapshot)
        now = datetime.now(self._timezone)
        selection = self._selector.choose_next(items, history, now)
        if not selection:
            await asyncio.sleep(self._settings.station.scan_interval_seconds)
            return

        await asyncio.to_thread(self._render_programme_block, selection.item, selection.band, now)

    def _render_programme_block(self, item: ContentItem, band: ContentBand, now: datetime) -> None:
        script = self._script_writer.build_script(item, now, previous_item=self._last_item)
        link_audio = self._render_link_audio(script.text)
        program_id = f"{now:%Y%m%d%H%M%S}_{item.content_id}"
        scratch_programme = self._settings.runtime.scratch_root / f"{program_id}.aac"
        self._audio.concat_programme([link_audio, item.audio_path], scratch_programme)
        segments = self._audio.segment_programme(scratch_programme, prefix=program_id)
        total_duration = self._playlist.append_block(segments)
        played_at = self._stream_end_at if self.buffer_seconds() > 0 else now
        # Advance the wall-clock stream horizon by the exact duration that was just rendered.
        self._stream_end_at = max(self._stream_end_at, now) + timedelta(seconds=total_duration)

        self._state.record_play(
            PlayEvent(
                content_id=item.content_id,
                title=item.title,
                band=band,
                played_at=played_at,
                duration_seconds=total_duration,
                program_id=program_id,
                script_text=script.text,
            )
        )

        scratch_programme.unlink(missing_ok=True)
        self._last_item = item
        self._last_program_id = program_id
        self._last_error = None

    def _render_link_audio(self, text: str) -> Path:
        cache_key = build_cache_key(
            text=text,
            backend=self._settings.host.tts_backend,
            voice_id=self._settings.host.voice_id,
            engine=self._settings.host.polly_engine,
        )
        cached = self._state.get_cached_synth_path(cache_key)
        if cached:
            return cached

        destination = self._settings.runtime.synth_cache_root / f"{cache_key}.mp3"
        rendered = self._tts.synthesize_to_file(text, destination)
        self._state.remember_synth_path(cache_key, rendered, self._settings.host.voice_id)
        return rendered
