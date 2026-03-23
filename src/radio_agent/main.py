from __future__ import annotations

import os

import uvicorn

from radio_agent.api import build_app

app = build_app()


if __name__ == "__main__":
    uvicorn.run(
        "radio_agent.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
