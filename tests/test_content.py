from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from radio_agent.config import ContentSettings, HostSettings, RadioSettings, RuntimeSettings
from radio_agent.content import (
    ContentLibrary,
    FilesystemContentRepository,
    S3ContentRepository,
)


class FakePaginator:
    def __init__(self, client: "FakeS3Client") -> None:
        self._client = client

    def paginate(self, Bucket: str, Prefix: str) -> list[dict]:
        assert Bucket == self._client.bucket
        pages = []
        contents = [item for item in self._client.objects if item["Key"].startswith(Prefix)]
        pages.append({"Contents": contents})
        return pages


class FakeS3Client:
    def __init__(self, objects: list[dict], bodies: dict[str, bytes], bucket: str = "radio-source") -> None:
        self.bucket = bucket
        self.objects = objects
        self.bodies = bodies
        self.metadata_requests = 0
        self.download_requests = 0

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self)

    def get_object(self, Bucket: str, Key: str) -> dict:
        assert Bucket == self.bucket
        self.metadata_requests += 1
        return {"Body": BytesIO(self.bodies[Key])}

    def download_file(self, Bucket: str, Key: str, Filename: str) -> None:
        assert Bucket == self.bucket
        self.download_requests += 1
        Path(Filename).write_bytes(self.bodies[Key])


def test_filesystem_repository_scan_and_materialize(tmp_path: Path) -> None:
    content_root = tmp_path / "content"
    dated = content_root / "2026-03-20"
    dated.mkdir(parents=True)
    audio_path = dated / "markets-briefing.mp3"
    audio_path.write_bytes(b"audio")
    metadata_path = dated / "markets-briefing.json"
    metadata_path.write_text('{"title":"Markets Briefing","summary":"Rates move again"}', encoding="utf-8")

    settings = RadioSettings(
        content=ContentSettings(root_path=content_root),
        runtime=RuntimeSettings(
            working_root=tmp_path / "runtime",
            state_db_path=tmp_path / "runtime" / "state" / "radio.db",
            scratch_root=tmp_path / "runtime" / "scratch",
            synth_cache_root=tmp_path / "runtime" / "synth-cache",
        ),
    )
    settings.ensure_runtime_paths()
    repository = FilesystemContentRepository(settings)

    items = repository.scan()

    assert len(items) == 1
    item = items[0]
    assert item.title == "Markets Briefing"
    assert item.audio_path == audio_path.resolve()
    assert item.audio_source is not None
    assert repository.materialize_audio(item) == audio_path.resolve()


def test_s3_repository_pairs_sidecars_uses_prefix_dates_and_caches_metadata(tmp_path: Path) -> None:
    london = ZoneInfo("Europe/London")
    last_modified = datetime(2026, 3, 20, 9, 15, tzinfo=london)
    client = FakeS3Client(
        objects=[
            {"Key": "radio/2026-03-20/markets-briefing.mp3", "ETag": '"audio-1"', "LastModified": last_modified, "Size": 7},
            {"Key": "radio/2026-03-20/markets-briefing.json", "ETag": '"meta-1"', "LastModified": last_modified, "Size": 96},
        ],
        bodies={
            "radio/2026-03-20/markets-briefing.json": b'{"title":"Markets Briefing","summary":"Rates move again"}',
            "radio/2026-03-20/markets-briefing.mp3": b"audio-1",
        },
    )
    settings = RadioSettings(
        content=ContentSettings(
            backend="s3",
            s3_bucket="radio-source",
            s3_prefix="radio",
            local_cache_root=tmp_path / "cache",
            cache_max_gb=1.0,
        ),
        host=HostSettings(tts_backend="silence"),
    )
    settings.ensure_runtime_paths()

    repository = S3ContentRepository(settings, client=client)
    first_scan = repository.scan()
    second_scan = repository.scan()

    assert len(first_scan) == 1
    item = first_scan[0]
    assert item.audio_path is None
    assert item.audio_source is not None
    assert item.published_at == datetime(2026, 3, 20, 6, 0, tzinfo=london)
    assert item.summary == "Rates move again"
    assert second_scan[0].title == "Markets Briefing"
    assert client.metadata_requests == 1


def test_s3_repository_invalidates_metadata_cache_when_etag_changes(tmp_path: Path) -> None:
    last_modified = datetime(2026, 3, 20, 9, 15, tzinfo=ZoneInfo("Europe/London"))
    client = FakeS3Client(
        objects=[
            {"Key": "radio/2026-03-20/markets-briefing.mp3", "ETag": '"audio-1"', "LastModified": last_modified, "Size": 7},
            {"Key": "radio/2026-03-20/markets-briefing.json", "ETag": '"meta-1"', "LastModified": last_modified, "Size": 96},
        ],
        bodies={
            "radio/2026-03-20/markets-briefing.json": b'{"title":"Markets Briefing","summary":"First summary"}',
            "radio/2026-03-20/markets-briefing.mp3": b"audio-1",
        },
    )
    settings = RadioSettings(
        content=ContentSettings(
            backend="s3",
            s3_bucket="radio-source",
            s3_prefix="radio",
            local_cache_root=tmp_path / "cache",
            cache_max_gb=1.0,
        ),
    )
    settings.ensure_runtime_paths()
    repository = S3ContentRepository(settings, client=client)

    first_scan = repository.scan()
    client.objects[1]["ETag"] = '"meta-2"'
    client.bodies["radio/2026-03-20/markets-briefing.json"] = b'{"title":"Markets Briefing","summary":"Updated summary"}'
    second_scan = repository.scan()

    assert first_scan[0].summary == "First summary"
    assert second_scan[0].summary == "Updated summary"
    assert client.metadata_requests == 2


def test_s3_repository_downloads_on_demand_and_evicts_old_cache(tmp_path: Path) -> None:
    last_modified = datetime(2026, 3, 20, 9, 15, tzinfo=ZoneInfo("Europe/London"))
    client = FakeS3Client(
        objects=[
            {"Key": "radio/2026-03-20/first.mp3", "ETag": '"audio-1"', "LastModified": last_modified, "Size": 7},
            {"Key": "radio/2026-03-20/second.mp3", "ETag": '"audio-2"', "LastModified": last_modified, "Size": 7},
        ],
        bodies={
            "radio/2026-03-20/first.mp3": b"audio-1",
            "radio/2026-03-20/second.mp3": b"audio-2",
        },
    )
    settings = RadioSettings(
        content=ContentSettings(
            backend="s3",
            s3_bucket="radio-source",
            s3_prefix="radio",
            local_cache_root=tmp_path / "cache",
            cache_max_gb=0.00000001,
        ),
    )
    settings.ensure_runtime_paths()
    repository = S3ContentRepository(settings, client=client)

    items = repository.scan()
    first_path = repository.materialize_audio(items[0])
    cached_first_again = repository.materialize_audio(items[0])
    assert first_path.read_bytes() == b"audio-1"
    second_path = repository.materialize_audio(items[1])

    assert first_path == cached_first_again
    assert second_path.read_bytes() == b"audio-2"
    assert client.download_requests == 2
    assert not first_path.exists()
    assert second_path.exists()


def test_content_library_uses_configured_repository(tmp_path: Path) -> None:
    content_root = tmp_path / "content"
    dated = content_root / "2026-03-20"
    dated.mkdir(parents=True)
    audio_path = dated / "markets-briefing.mp3"
    audio_path.write_bytes(b"audio")

    settings = RadioSettings(
        content=ContentSettings(root_path=content_root),
        runtime=RuntimeSettings(
            working_root=tmp_path / "runtime",
            state_db_path=tmp_path / "runtime" / "state" / "radio.db",
            scratch_root=tmp_path / "runtime" / "scratch",
            synth_cache_root=tmp_path / "runtime" / "synth-cache",
        ),
    )
    settings.ensure_runtime_paths()

    library = ContentLibrary(settings)
    items = library.scan()

    assert len(items) == 1
    assert library.materialize_audio(items[0]) == audio_path.resolve()
