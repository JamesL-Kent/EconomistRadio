from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from radio_agent.config import RadioSettings, load_settings
from radio_agent.engine import RadioEngine


def build_app(settings: RadioSettings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = RadioEngine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine
        await engine.start()
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(
        title="Radio Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.mount(
        settings.output.public_mount_path,
        StaticFiles(directory=settings.output.root_path),
        name="stream",
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    async def status() -> dict[str, object]:
        snapshot = app.state.engine.snapshot()
        return {
            "running": snapshot.running,
            "stream_url": snapshot.stream_url,
            "playlist_path": snapshot.playlist_path,
            "buffer_seconds": round(snapshot.buffer_seconds, 2),
            "content_items": snapshot.content_items,
            "last_program_id": snapshot.last_program_id,
            "last_title": snapshot.last_title,
            "last_error": snapshot.last_error,
        }

    return app
