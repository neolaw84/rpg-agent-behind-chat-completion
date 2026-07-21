"""OpenRouter Chat Completion Proxy — application factory.

Assembles the FastAPI application by wiring together the three routers:

* ``routes.completions`` — ``POST /v1/chat/completions`` (streaming & non-streaming)
* ``routes.sessions``    — session CRUD endpoints
* ``routes.system``      — dashboard SPA, health check, and status endpoint

All business logic lives in those routers and the modules they import.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rachel.auth import PROXY_API_KEY
from rachel.config import MAX_ITERATIONS, NUM_STATES_TO_TRACK, SANDBOX_TIMEOUT
from rachel.routes.completions import router as completions_router
from rachel.routes.sessions import router as sessions_router
from rachel.routes.system import detect_public_url, router as system_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    public_url = detect_public_url()
    api_endpoint = f"{public_url}/v1"
    dashboard_url = f"{public_url}/"
    print(
        "\n" + "=" * 60 + "\n"
        f"  Proxy API Key (use as Bearer token):\n"
        f"  {PROXY_API_KEY}\n"
        "\n"
        f"  Server Public URL:  {public_url}\n"
        f"  Proxy API Endpoint: {api_endpoint}\n"
        f"  Dashboard URL:      {dashboard_url}\n"
        + "=" * 60 + "\n"
    )
    logger.info(
        "Config loaded: states=%d, timeout=%.1fs, max_iter=%d",
        NUM_STATES_TO_TRACK, SANDBOX_TIMEOUT, MAX_ITERATIONS,
    )
    logger.info("Server Public URL:  %s", public_url)
    logger.info("Proxy API Endpoint: %s", api_endpoint)
    logger.info("Dashboard URL:      %s", dashboard_url)
    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="RACHEL Proxy",
    description=(
        "RACHEL (Rpg Agent CHat Evaluation Loop) - OpenAI-compatible Chat "
        "Completion API proxy with stateful LangGraph agent and V8 code sandbox."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://janitorai.com"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(completions_router)
app.include_router(sessions_router)
app.include_router(system_router)


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main():
    import argparse
    import uvicorn

    default_port = int(os.environ.get("PORT", 8000))

    parser = argparse.ArgumentParser(description="RACHEL (Rpg Agent CHat Evaluation Loop) Proxy")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host")
    parser.add_argument("--port", type=int, default=default_port, help="Binding port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    args = parser.parse_args()

    uvicorn.run("rachel.proxy:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
