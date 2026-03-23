from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from radio_agent.config import RadioSettings, load_settings
from radio_agent.engine import RadioEngine


STATIC_ROOT = Path(__file__).with_name("static")


def build_app(settings: RadioSettings | None = None, engine: RadioEngine | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = engine or RadioEngine(settings)

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
    app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")
    app.mount(
        settings.output.public_mount_path,
        StaticFiles(directory=settings.output.root_path),
        name="stream",
    )

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _player_page(settings.station.name)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        snapshot = app.state.engine.snapshot()
        status_code = 200 if snapshot.running else 503
        return JSONResponse(
            status_code=status_code,
            content={"status": "ready" if snapshot.running else "starting", "running": snapshot.running},
        )

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


def _player_page(station_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{station_name}</title>
  <link rel="stylesheet" href="/assets/player.css" />
</head>
<body>
  <main class="shell">
    <section class="hero">
      <p class="eyebrow">Authenticated Live Radio</p>
      <h1>{station_name}</h1>
      <p class="dek">Continuous live playback for narrated features, served from the same origin as the HLS stream.</p>
    </section>

    <section class="player-card">
      <audio id="radio-player" controls preload="none"></audio>
      <p id="player-message" class="player-message">Checking stream availability...</p>
    </section>

    <section class="status-grid">
      <article class="status-card">
        <h2>Now Playing</h2>
        <p id="last-title" class="value">Waiting for first programme block</p>
      </article>
      <article class="status-card">
        <h2>Buffer</h2>
        <p id="buffer-seconds" class="value">0s</p>
      </article>
      <article class="status-card">
        <h2>Content Items</h2>
        <p id="content-items" class="value">0</p>
      </article>
      <article class="status-card">
        <h2>Engine</h2>
        <p id="engine-state" class="value">Starting</p>
      </article>
    </section>

    <section class="detail-card">
      <h2>Last Error</h2>
      <p id="last-error" class="detail">No errors reported.</p>
    </section>
  </main>

  <script src="/assets/hls.min.js"></script>
  <script src="/assets/player.js"></script>
</body>
</html>
"""
