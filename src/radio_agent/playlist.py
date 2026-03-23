from __future__ import annotations

from collections import deque
from math import ceil

from radio_agent.config import RadioSettings
from radio_agent.models import SegmentArtifact
from radio_agent.publisher import OutputPublisher


class LivePlaylistWriter:
    """Maintains a rolling HLS media playlist for the generated stream."""

    def __init__(self, settings: RadioSettings, publisher: OutputPublisher) -> None:
        self._settings = settings
        self._publisher = publisher
        self._segments: deque[tuple[int, bool, SegmentArtifact]] = deque()
        self._next_sequence = 0

    def append_block(self, segments: list[SegmentArtifact]) -> float:
        if not segments:
            return 0.0

        for index, segment in enumerate(segments):
            discontinuity = bool(self._segments) and index == 0
            self._segments.append((self._next_sequence, discontinuity, segment))
            self._next_sequence += 1
            self._publisher.publish_file(segment.local_path, segment.uri, "video/mp2t")

        self._prune_segments()
        self._write_playlist()
        return sum(segment.duration_seconds for segment in segments)

    def _prune_segments(self) -> None:
        while len(self._segments) > self._settings.output.retention_segments:
            _, _, segment = self._segments.popleft()
            segment.local_path.unlink(missing_ok=True)

    def _write_playlist(self) -> None:
        playlist_path = self._settings.playlist_path
        playlist_path.parent.mkdir(parents=True, exist_ok=True)

        # Only the newest window stays in the live playlist, while older files remain briefly for safety.
        visible = list(self._segments)[-self._settings.output.playlist_window_segments :]
        media_sequence = visible[0][0] if visible else 0
        target_duration = max(
            1,
            ceil(max((segment.duration_seconds for _, _, segment in visible), default=1.0)),
        )

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{target_duration}",
            f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
        ]
        for _, discontinuity, segment in visible:
            if discontinuity:
                lines.append("#EXT-X-DISCONTINUITY")
            lines.append(f"#EXTINF:{segment.duration_seconds:.3f},")
            lines.append(segment.uri)

        temp_path = playlist_path.with_suffix(".tmp")
        temp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temp_path.replace(playlist_path)
        self._publisher.publish_file(
            playlist_path,
            self._settings.output.playlist_name,
            "application/vnd.apple.mpegurl",
        )
