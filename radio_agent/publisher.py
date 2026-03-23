from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import boto3

from radio_agent.config import RadioSettings


class OutputPublisher(ABC):
    """Publishes generated assets to a destination that clients can reach."""

    @abstractmethod
    def publish_file(self, local_path: Path, key: str, content_type: str) -> None:
        raise NotImplementedError


class FilesystemPublisher(OutputPublisher):
    """Local publisher used when the app serves files directly from disk."""

    def publish_file(self, local_path: Path, key: str, content_type: str) -> None:
        _ = (local_path, key, content_type)


class S3MirrorPublisher(OutputPublisher):
    """Optional publisher that mirrors live assets to S3 for CDN delivery."""

    def __init__(self, settings: RadioSettings) -> None:
        if not settings.output.s3_bucket:
            raise ValueError("S3 bucket is required for S3 mirroring")
        self._bucket = settings.output.s3_bucket
        self._prefix = settings.output.s3_prefix.strip("/")
        self._client = boto3.client("s3", region_name=settings.output.aws_region)

    def publish_file(self, local_path: Path, key: str, content_type: str) -> None:
        object_key = f"{self._prefix}/{key}".strip("/")
        self._client.upload_file(
            str(local_path),
            self._bucket,
            object_key,
            ExtraArgs={"ContentType": content_type},
        )


class CompositePublisher(OutputPublisher):
    """Small helper that fans the same asset out to multiple destinations."""

    def __init__(self, publishers: list[OutputPublisher]) -> None:
        self._publishers = publishers

    def publish_file(self, local_path: Path, key: str, content_type: str) -> None:
        for publisher in self._publishers:
            publisher.publish_file(local_path, key, content_type)


def build_publisher(settings: RadioSettings) -> OutputPublisher:
    publishers: list[OutputPublisher] = [FilesystemPublisher()]
    if settings.output.s3_bucket:
        publishers.append(S3MirrorPublisher(settings))
    return CompositePublisher(publishers)
