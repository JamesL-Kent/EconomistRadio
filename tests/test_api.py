from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from radio_agent.api import build_app
from radio_agent.config import HostSettings, OutputSettings, RadioSettings, RuntimeSettings
from radio_agent.models import EngineSnapshot


class DummyEngine:
    def __init__(self, snapshot: EngineSnapshot) -> None:
        self._snapshot = snapshot
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def snapshot(self) -> EngineSnapshot:
        return self._snapshot


def make_settings(tmp_path: Path) -> RadioSettings:
    settings = RadioSettings(
        host=HostSettings(tts_backend="silence"),
        runtime=RuntimeSettings(
            working_root=tmp_path / "runtime",
            state_db_path=tmp_path / "runtime" / "state" / "radio.db",
            scratch_root=tmp_path / "runtime" / "scratch",
            synth_cache_root=tmp_path / "runtime" / "synth-cache",
        ),
        output=OutputSettings(root_path=tmp_path / "runtime" / "output", public_base_url="https://radio.example.com"),
    )
    settings.ensure_runtime_paths()
    return settings


def test_player_page_exposes_same_origin_assets(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    engine = DummyEngine(
        EngineSnapshot(
            running=True,
            stream_url="/stream/live.m3u8",
            playlist_path=str(settings.playlist_path),
            buffer_seconds=120.0,
            content_items=6,
            last_title="Markets Briefing",
        )
    )
    app = build_app(settings=settings, engine=engine)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="radio-player"' in response.text
    assert "/assets/hls.min.js" in response.text
    assert engine.started is True
    assert engine.stopped is True


def test_readyz_reflects_engine_state(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = build_app(
        settings=settings,
        engine=DummyEngine(
            EngineSnapshot(
                running=False,
                stream_url="/stream/live.m3u8",
                playlist_path=str(settings.playlist_path),
                buffer_seconds=0.0,
                content_items=0,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "starting", "running": False}


def test_status_contract_is_unchanged_except_for_new_routes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = build_app(
        settings=settings,
        engine=DummyEngine(
            EngineSnapshot(
                running=True,
                stream_url=settings.stream_url,
                playlist_path=str(settings.playlist_path),
                buffer_seconds=240.0,
                content_items=8,
                last_program_id="programme-1",
                last_title="The Budget Debate",
                last_error=None,
            )
        ),
    )

    with TestClient(app) as client:
        response = client.get("/status")

    assert response.status_code == 200
    assert response.json() == {
        "running": True,
        "stream_url": settings.stream_url,
        "playlist_path": str(settings.playlist_path),
        "buffer_seconds": 240.0,
        "content_items": 8,
        "last_program_id": "programme-1",
        "last_title": "The Budget Debate",
        "last_error": None,
    }
