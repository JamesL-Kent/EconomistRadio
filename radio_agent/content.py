from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path, PurePosixPath

import boto3
import yaml
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from radio_agent.config import RadioSettings
from radio_agent.models import ContentItem, ContentSource
from radio_agent.timezones import load_timezone


class ContentRepositoryError(RuntimeError):
    """Raised when content discovery or materialization fails."""


class ContentRepository(ABC):
    """Source-aware repository for discovered radio items."""

    @abstractmethod
    def scan(self) -> list[ContentItem]:
        raise NotImplementedError

    @abstractmethod
    def materialize_audio(self, item: ContentItem) -> Path:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class MetadataCacheEntry:
    marker: str
    payload: dict


class FilesystemContentRepository(ContentRepository):
    """Scans the local content tree and returns directly playable items."""

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
            metadata = self._load_metadata_path(metadata_path) if metadata_path else {}
            relative_path = PurePosixPath(audio_path.relative_to(root).as_posix())
            source = ContentSource(
                backend="filesystem",
                identifier=str(audio_path.resolve()),
                relative_path=relative_path.as_posix(),
                last_modified=datetime.fromtimestamp(audio_path.stat().st_mtime, tz=self._timezone),
                size_bytes=audio_path.stat().st_size,
            )
            metadata_source = None
            if metadata_path:
                metadata_source = ContentSource(
                    backend="filesystem",
                    identifier=str(metadata_path.resolve()),
                    relative_path=PurePosixPath(metadata_path.relative_to(root).as_posix()).as_posix(),
                    last_modified=datetime.fromtimestamp(metadata_path.stat().st_mtime, tz=self._timezone),
                    size_bytes=metadata_path.stat().st_size,
                )
            items.append(
                self._build_item(
                    relative_path=relative_path,
                    audio_path=audio_path.resolve(),
                    metadata_path=metadata_path.resolve() if metadata_path else None,
                    metadata=metadata,
                    audio_source=source,
                    metadata_source=metadata_source,
                )
            )

        items.sort(key=lambda item: item.published_at, reverse=True)
        return items

    def materialize_audio(self, item: ContentItem) -> Path:
        if item.audio_path is None:
            raise ContentRepositoryError(f"Filesystem item {item.content_id} has no local audio path")
        return item.audio_path

    def _find_metadata(self, audio_path: Path) -> Path | None:
        for extension in self._settings.content.metadata_extensions:
            candidate = audio_path.with_suffix(extension)
            if candidate.exists():
                return candidate
        return None

    def _load_metadata_path(self, metadata_path: Path) -> dict:
        if metadata_path.suffix.lower() == ".json":
            return json.loads(metadata_path.read_text(encoding="utf-8"))
        return yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}

    def _build_item(
        self,
        *,
        relative_path: PurePosixPath,
        audio_path: Path | None,
        metadata_path: Path | None,
        metadata: dict,
        audio_source: ContentSource,
        metadata_source: ContentSource | None,
    ) -> ContentItem:
        published_at = self._resolve_published_at(relative_path, audio_path, metadata, audio_source.last_modified)
        interesting_score = self._parse_score(metadata.get("interesting_score"))
        raw_tags = metadata.get("tags", [])
        if isinstance(raw_tags, str):
            tags = (raw_tags,)
        else:
            tags = tuple(str(tag) for tag in raw_tags)

        title = str(metadata.get("title") or relative_path.stem.replace("-", " ").replace("_", " ").title())
        section = str(metadata.get("section") or relative_path.parent.name or "General")
        content_id = str(metadata.get("content_id") or self._hash_path(relative_path))
        return ContentItem(
            content_id=content_id,
            title=title,
            audio_path=audio_path,
            audio_source=audio_source,
            published_at=published_at,
            section=section,
            summary=str(metadata.get("summary") or metadata.get("dek") or "").strip(),
            tags=tags,
            interesting_score=max(0.0, min(interesting_score, 1.0)),
            evergreen=bool(metadata.get("evergreen", False)),
            source_url=metadata.get("source_url"),
            metadata_path=metadata_path,
            metadata_source=metadata_source,
            announcer_intro=metadata.get("announcer_intro"),
            duration_seconds=self._parse_duration(metadata.get("duration_seconds")),
            raw_metadata=metadata,
        )

    def _resolve_published_at(
        self,
        relative_path: PurePosixPath,
        audio_path: Path | None,
        metadata: dict,
        last_modified: datetime | None,
    ) -> datetime:
        value = metadata.get("published_at")
        if isinstance(value, str) and value:
            parsed = self._parse_datetime(value)
            if parsed:
                return parsed

        parent_name = relative_path.parent.name
        try:
            published_date = date.fromisoformat(parent_name)
            return datetime.combine(published_date, time(hour=6), tzinfo=self._timezone)
        except ValueError:
            pass

        if audio_path is not None:
            return datetime.fromtimestamp(audio_path.stat().st_mtime, tz=self._timezone)
        if last_modified is not None:
            return last_modified.astimezone(self._timezone)
        return datetime.now(self._timezone)

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

    def _hash_path(self, relative_path: PurePosixPath) -> str:
        digest = hashlib.sha1(str(relative_path).encode("utf-8")).hexdigest()
        return digest[:16]


class S3ContentRepository(FilesystemContentRepository):
    """Discovers source material in S3 and downloads audio only when selected."""

    def __init__(self, settings: RadioSettings, client: BaseClient | None = None) -> None:
        super().__init__(settings)
        self._bucket = settings.content.s3_bucket or ""
        self._prefix = settings.content.s3_prefix.strip("/")
        self._cache_root = settings.content.local_cache_root
        self._cache_limit_bytes = int(settings.content.cache_max_gb * 1024 * 1024 * 1024)
        self._client = client or boto3.client("s3", region_name=settings.content.aws_region)
        self._metadata_cache: dict[str, MetadataCacheEntry] = {}

    def scan(self) -> list[ContentItem]:
        audio_objects: list[ContentSource] = []
        metadata_objects: dict[str, ContentSource] = {}

        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=self._object_prefix()):
                for descriptor in page.get("Contents", []):
                    key = str(descriptor["Key"])
                    relative_path = self._relative_path_from_key(key)
                    if relative_path is None:
                        continue

                    suffix = relative_path.suffix.lower()
                    source = ContentSource(
                        backend="s3",
                        identifier=f"s3://{self._bucket}/{key}",
                        relative_path=relative_path.as_posix(),
                        etag=self._normalise_etag(descriptor.get("ETag")),
                        last_modified=descriptor.get("LastModified"),
                        size_bytes=int(descriptor.get("Size", 0)),
                    )
                    stem_key = relative_path.with_suffix("").as_posix()
                    if suffix in self._settings.content.audio_extensions:
                        audio_objects.append(source)
                    elif suffix in self._settings.content.metadata_extensions:
                        metadata_objects[stem_key] = source
        except NoCredentialsError as error:
            raise ContentRepositoryError(
                "AWS credentials were not found. Configure credentials for S3 before starting the radio engine."
            ) from error
        except ClientError as error:
            raise ContentRepositoryError(f"S3 list failed: {error.response['Error']['Message']}") from error
        except BotoCoreError as error:
            raise ContentRepositoryError(f"S3 client failed: {error}") from error

        items: list[ContentItem] = []
        for audio_source in audio_objects:
            relative_path = PurePosixPath(audio_source.relative_path)
            stem_key = relative_path.with_suffix("").as_posix()
            metadata_source = metadata_objects.get(stem_key)
            metadata = self._load_metadata_source(metadata_source) if metadata_source else {}
            items.append(
                self._build_item(
                    relative_path=relative_path,
                    audio_path=None,
                    metadata_path=None,
                    metadata=metadata,
                    audio_source=audio_source,
                    metadata_source=metadata_source,
                )
            )

        items.sort(key=lambda item: item.published_at, reverse=True)
        return items

    def materialize_audio(self, item: ContentItem) -> Path:
        if item.audio_source is None:
            return super().materialize_audio(item)
        if item.audio_source.backend != "s3":
            return super().materialize_audio(item)

        destination = self._cache_path_for(item.audio_source)
        if destination.exists():
            destination.touch()
            return destination

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._evict_cache(required_bytes=item.audio_source.size_bytes or 0)
        temp_path = destination.with_suffix(f"{destination.suffix}.tmp")
        bucket, key = self._split_s3_identifier(item.audio_source.identifier)
        try:
            self._client.download_file(bucket, key, str(temp_path))
        except NoCredentialsError as error:
            raise ContentRepositoryError(
                "AWS credentials were not found. Configure credentials for S3 before starting the radio engine."
            ) from error
        except ClientError as error:
            raise ContentRepositoryError(f"S3 download failed: {error.response['Error']['Message']}") from error
        except BotoCoreError as error:
            raise ContentRepositoryError(f"S3 client failed: {error}") from error

        temp_path.replace(destination)
        destination.touch()
        self._evict_cache()
        return destination

    def _load_metadata_source(self, source: ContentSource) -> dict:
        marker = f"{source.etag or ''}:{source.last_modified.isoformat() if source.last_modified else ''}"
        cached = self._metadata_cache.get(source.identifier)
        if cached and cached.marker == marker:
            return cached.payload

        bucket, key = self._split_s3_identifier(source.identifier)
        try:
            response = self._client.get_object(Bucket=bucket, Key=key)
            payload = response["Body"].read().decode("utf-8")
        except NoCredentialsError as error:
            raise ContentRepositoryError(
                "AWS credentials were not found. Configure credentials for S3 before starting the radio engine."
            ) from error
        except ClientError as error:
            raise ContentRepositoryError(f"S3 metadata load failed: {error.response['Error']['Message']}") from error
        except BotoCoreError as error:
            raise ContentRepositoryError(f"S3 client failed: {error}") from error

        if key.lower().endswith(".json"):
            metadata = json.loads(payload)
        else:
            metadata = yaml.safe_load(payload) or {}
        self._metadata_cache[source.identifier] = MetadataCacheEntry(marker=marker, payload=metadata)
        return metadata

    def _object_prefix(self) -> str:
        return f"{self._prefix}/" if self._prefix else ""

    def _relative_path_from_key(self, key: str) -> PurePosixPath | None:
        prefix = self._object_prefix()
        if prefix and not key.startswith(prefix):
            return None
        trimmed = key[len(prefix) :] if prefix else key
        if not trimmed or trimmed.endswith("/"):
            return None
        return PurePosixPath(trimmed)

    def _cache_path_for(self, source: ContentSource) -> Path:
        relative = PurePosixPath(source.relative_path)
        suffix = relative.suffix
        key_hash = hashlib.sha1(source.identifier.encode("utf-8")).hexdigest()[:16]
        etag_fragment = (source.etag or "latest").replace('"', "").replace("/", "")[:12] or "latest"
        filename = f"{key_hash}_{etag_fragment}{suffix}"
        return self._cache_root / filename

    def _evict_cache(self, required_bytes: int = 0) -> None:
        files = [path for path in self._cache_root.glob("*") if path.is_file()]
        total = sum(path.stat().st_size for path in files)
        if total + required_bytes <= self._cache_limit_bytes:
            return

        for path in sorted(files, key=lambda item: item.stat().st_mtime):
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            if total + required_bytes <= self._cache_limit_bytes:
                break

    def _split_s3_identifier(self, identifier: str) -> tuple[str, str]:
        if not identifier.startswith("s3://"):
            raise ContentRepositoryError(f"Unsupported S3 identifier: {identifier}")
        bucket_and_key = identifier[5:]
        bucket, _, key = bucket_and_key.partition("/")
        if not bucket or not key:
            raise ContentRepositoryError(f"Unsupported S3 identifier: {identifier}")
        return bucket, key

    def _normalise_etag(self, value: object) -> str | None:
        if value is None:
            return None
        return str(value).strip('"')


class ContentLibrary:
    """Thin wrapper that selects the configured content repository."""

    def __init__(self, settings: RadioSettings, repository: ContentRepository | None = None) -> None:
        self._settings = settings
        self._repository = repository or build_content_repository(settings)

    def scan(self) -> list[ContentItem]:
        return self._repository.scan()

    def materialize_audio(self, item: ContentItem) -> Path:
        return self._repository.materialize_audio(item)


def build_content_repository(settings: RadioSettings) -> ContentRepository:
    backend = settings.content.backend.strip().lower()
    if backend == "filesystem":
        return FilesystemContentRepository(settings)
    if backend == "s3":
        return S3ContentRepository(settings)
    raise ContentRepositoryError(f"Unsupported content backend '{settings.content.backend}'")
