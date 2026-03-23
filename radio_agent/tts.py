from __future__ import annotations

import hashlib
import wave
from abc import ABC, abstractmethod
from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from radio_agent.config import RadioSettings


class TextToSpeechSynthesizer(ABC):
    """Abstract TTS interface so the engine does not depend on a single provider."""

    @abstractmethod
    def synthesize_to_file(self, text: str, destination: Path) -> Path:
        raise NotImplementedError


class SilentLinkSynthesizer(TextToSpeechSynthesizer):
    """Local development fallback that emits a short silent WAV placeholder."""

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings

    def synthesize_to_file(self, text: str, destination: Path) -> Path:
        _ = text
        destination = destination.with_suffix(".wav")
        destination.parent.mkdir(parents=True, exist_ok=True)

        sample_rate = self._settings.audio.sample_rate_hz
        duration_seconds = max(self._settings.host.silent_link_seconds, 0.2)
        frame_count = int(sample_rate * duration_seconds)

        with wave.open(str(destination), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(b"\x00\x00" * frame_count)
        return destination


class AmazonPollySynthesizer(TextToSpeechSynthesizer):
    """Uses AWS Polly to render the host links as MP3 files."""

    def __init__(self, settings: RadioSettings) -> None:
        self._settings = settings
        self._client: BaseClient = boto3.client(
            "polly",
            region_name=settings.output.aws_region,
        )

    def synthesize_to_file(self, text: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = self._client.synthesize_speech(
                Engine=self._settings.host.polly_engine,
                OutputFormat="mp3",
                Text=text,
                VoiceId=self._settings.host.voice_id,
            )
        except NoCredentialsError as error:
            raise RuntimeError(
                "AWS credentials were not found. Configure credentials for Polly before starting the radio engine."
            ) from error
        except ClientError as error:
            raise RuntimeError(f"Polly request failed: {error.response['Error']['Message']}") from error
        except BotoCoreError as error:
            raise RuntimeError(f"Polly client failed: {error}") from error
        audio_stream = response["AudioStream"]
        destination.write_bytes(audio_stream.read())
        return destination


def build_cache_key(text: str, backend: str, voice_id: str, engine: str) -> str:
    digest = hashlib.sha1(f"{backend}:{voice_id}:{engine}:{text}".encode("utf-8")).hexdigest()
    return digest


def build_synthesizer(settings: RadioSettings) -> TextToSpeechSynthesizer:
    backend = settings.host.tts_backend.strip().lower()
    if backend == "polly":
        return AmazonPollySynthesizer(settings)
    if backend == "silence":
        return SilentLinkSynthesizer(settings)
    raise ValueError(
        f"Unsupported host.tts_backend '{settings.host.tts_backend}'. "
        "Use 'polly' or 'silence'."
    )
