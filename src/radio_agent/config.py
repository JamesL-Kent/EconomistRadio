from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StationSettings(BaseModel):
    """Top-level station identity shown in scripts and logs."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Economist Radio"
    timezone: str = "Europe/London"
    scan_interval_seconds: int = 20


class ContentSettings(BaseModel):
    """Where the source material lives and how it is interpreted."""

    model_config = ConfigDict(extra="forbid")

    root_path: Path = Path("./content")
    audio_extensions: tuple[str, ...] = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
    metadata_extensions: tuple[str, ...] = (".json", ".yaml", ".yml")


class SchedulingSettings(BaseModel):
    """Editorial weighting that keeps the station current without becoming repetitive."""

    model_config = ConfigDict(extra="forbid")

    repeat_cooldown_hours: int = 18
    today_priority_weight: float = 6.0
    week_priority_weight: float = 2.5
    archive_priority_weight: float = 0.8
    interesting_bonus: float = 1.2
    evergreen_bonus: float = 0.5
    history_penalty: float = 0.35
    week_injection_interval: int = 4
    archive_injection_interval: int = 8
    minimum_archive_score: float = 0.65


class HostSettings(BaseModel):
    """Personality configuration for the radio host."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Adrienne"
    identity: str = "A calm, sharp radio presenter who sounds concise and informed."
    tone: str = "Warm, brisk, lightly witty, never over-explained."
    max_link_words: int = 42
    max_link_sentences: int = 2
    tts_backend: str = "polly"
    voice_id: str = "Amy"
    polly_engine: str = "neural"
    silent_link_seconds: float = 1.2
    opener_templates: list[str] = Field(
        default_factory=lambda: [
            "You're listening to {station_name}.",
            "This is {station_name}, and I'm {host_name}.",
            "Stay with us on {station_name}.",
        ]
    )
    bridge_templates: list[str] = Field(
        default_factory=lambda: [
            "Next, {host_name} turns to {section}.",
            "Now for a quick shift into {section}.",
            "Coming up, a concise look at {section}.",
        ]
    )
    teaser_templates: list[str] = Field(
        default_factory=lambda: [
            "{title}: {summary}.",
            "It's {title}, with {summary}.",
            "Ahead, {title} and {summary}.",
        ]
    )
    banned_phrases: list[str] = Field(
        default_factory=lambda: [
            "in today's episode",
            "don't go anywhere",
            "after the break",
        ]
    )


class RuntimeSettings(BaseModel):
    """Local runtime paths and state storage."""

    model_config = ConfigDict(extra="forbid")

    working_root: Path = Path("./runtime")
    state_db_path: Path = Path("./runtime/state/radio.db")
    scratch_root: Path = Path("./runtime/scratch")
    synth_cache_root: Path = Path("./runtime/synth-cache")


class AudioSettings(BaseModel):
    """ffmpeg and encoding settings for the stream."""

    model_config = ConfigDict(extra="forbid")

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    output_codec: str = "aac"
    audio_bitrate: str = "128k"
    sample_rate_hz: int = 44100


class OutputSettings(BaseModel):
    """Live stream settings and optional AWS mirroring."""

    model_config = ConfigDict(extra="forbid")

    root_path: Path = Path("./runtime/output")
    public_mount_path: str = "/stream"
    playlist_name: str = "live.m3u8"
    segments_subdirectory: str = "segments"
    segment_duration_seconds: int = 6
    playlist_window_segments: int = 24
    retention_segments: int = 48
    target_buffer_seconds: int = 240
    max_buffer_seconds: int = 420
    public_base_url: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = "radio/live"
    aws_region: str = "eu-west-2"

    @field_validator("public_mount_path")
    @classmethod
    def normalise_mount(cls, value: str) -> str:
        if not value.startswith("/"):
            return f"/{value}"
        return value.rstrip("/") or "/stream"

    @model_validator(mode="after")
    def validate_segment_windows(self) -> "OutputSettings":
        if self.retention_segments < self.playlist_window_segments:
            raise ValueError("retention_segments must be >= playlist_window_segments")
        if self.max_buffer_seconds < self.target_buffer_seconds:
            raise ValueError("max_buffer_seconds must be >= target_buffer_seconds")
        return self


class AppSettings(BaseModel):
    """HTTP host process configuration."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class RadioSettings(BaseModel):
    """Validated application settings."""

    model_config = ConfigDict(extra="forbid")

    station: StationSettings = Field(default_factory=StationSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    scheduling: SchedulingSettings = Field(default_factory=SchedulingSettings)
    host: HostSettings = Field(default_factory=HostSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)
    app: AppSettings = Field(default_factory=AppSettings)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "RadioSettings":
        config_path = Path(path).expanduser().resolve()
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        settings = cls.model_validate(payload)
        settings._resolve_paths(config_path.parent)
        settings.ensure_runtime_paths()
        return settings

    def _resolve_paths(self, config_dir: Path) -> None:
        """Resolve every filesystem path relative to the config file location."""
        for model_name, field_name in (
            ("content", "root_path"),
            ("runtime", "working_root"),
            ("runtime", "state_db_path"),
            ("runtime", "scratch_root"),
            ("runtime", "synth_cache_root"),
            ("output", "root_path"),
        ):
            model = getattr(self, model_name)
            current = getattr(model, field_name)
            resolved = current if current.is_absolute() else (config_dir / current).resolve()
            setattr(model, field_name, resolved)

    def ensure_runtime_paths(self) -> None:
        """Create the directories that the live process needs before startup."""
        self.runtime.working_root.mkdir(parents=True, exist_ok=True)
        self.runtime.state_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.scratch_root.mkdir(parents=True, exist_ok=True)
        self.runtime.synth_cache_root.mkdir(parents=True, exist_ok=True)
        self.output.root_path.mkdir(parents=True, exist_ok=True)
        self.segments_root.mkdir(parents=True, exist_ok=True)

    @property
    def playlist_path(self) -> Path:
        return self.output.root_path / self.output.playlist_name

    @property
    def segments_root(self) -> Path:
        return self.output.root_path / self.output.segments_subdirectory

    @property
    def stream_url(self) -> str:
        base = self.output.public_base_url
        suffix = f"{self.output.public_mount_path}/{self.output.playlist_name}".replace("//", "/")
        if base:
            return f"{base.rstrip('/')}{suffix}"
        return suffix


def load_settings() -> RadioSettings:
    """Load config from RADIO_CONFIG_PATH or the default sample file."""
    config_path = os.getenv("RADIO_CONFIG_PATH", "config/radio.example.yaml")
    return RadioSettings.from_yaml(config_path)
