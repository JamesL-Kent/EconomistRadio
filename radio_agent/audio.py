from __future__ import annotations

import subprocess
from pathlib import Path

from radio_agent.config import RadioSettings
from radio_agent.models import SegmentArtifact


class AudioProcessingError(RuntimeError):
    """Raised when ffmpeg or ffprobe fails."""


class AudioAssembler:
    """Wraps ffmpeg so the rest of the application stays easy to test."""

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings

    def concat_programme(self, inputs: list[Path], output_path: Path) -> None:
        if not inputs:
            raise AudioProcessingError("At least one input is required to build a programme")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._settings.audio.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
        ]
        for item in inputs:
            command.extend(["-i", str(item)])

        if len(inputs) == 1:
            command.extend(["-map", "0:a:0"])
        else:
            audio_inputs = "".join(f"[{index}:a:0]" for index in range(len(inputs)))
            command.extend(
                [
                    "-filter_complex",
                    f"{audio_inputs}concat=n={len(inputs)}:v=0:a=1[aout]",
                    "-map",
                    "[aout]",
                ]
            )

        command.extend(
            [
                "-ar",
                str(self._settings.audio.sample_rate_hz),
                "-c:a",
                self._settings.audio.output_codec,
                "-b:a",
                self._settings.audio.audio_bitrate,
                str(output_path),
            ]
        )
        self._run(command)

    def segment_programme(self, input_path: Path, prefix: str) -> list[SegmentArtifact]:
        segments_root = self._settings.segments_root
        segments_root.mkdir(parents=True, exist_ok=True)
        pattern = segments_root / f"{prefix}_%05d.ts"
        existing = set(segments_root.glob(f"{prefix}_*.ts"))
        command = [
            self._settings.audio.ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-c:a",
            self._settings.audio.output_codec,
            "-b:a",
            self._settings.audio.audio_bitrate,
            "-ar",
            str(self._settings.audio.sample_rate_hz),
            "-f",
            "segment",
            "-segment_time",
            str(self._settings.output.segment_duration_seconds),
            "-segment_format",
            "mpegts",
            "-reset_timestamps",
            "1",
            str(pattern),
        ]
        self._run(command)

        created = sorted(path for path in segments_root.glob(f"{prefix}_*.ts") if path not in existing)
        if not created:
            raise AudioProcessingError(f"No segments were generated for {input_path}")
        return [
            SegmentArtifact(
                local_path=path,
                uri=f"{self._settings.output.segments_subdirectory}/{path.name}",
                duration_seconds=self.probe_duration(path),
            )
            for path in created
        ]

    def probe_duration(self, audio_path: Path) -> float:
        command = [
            self._settings.audio.ffprobe_binary,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            str(audio_path),
        ]
        result = self._run(command, capture_output=True)
        try:
            return float(result.stdout.strip())
        except ValueError as error:
            raise AudioProcessingError(f"Could not read duration for {audio_path}") from error

    def _run(self, command: list[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=True,
                capture_output=capture_output,
                text=True,
            )
        except FileNotFoundError as error:
            raise AudioProcessingError(f"Missing binary in command: {' '.join(command)}") from error
        except subprocess.CalledProcessError as error:
            stderr = error.stderr.strip() if error.stderr else "no stderr"
            raise AudioProcessingError(stderr) from error
