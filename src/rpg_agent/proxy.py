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

from rpg_agent.auth import PROXY_API_KEY
from rpg_agent.config import MAX_ITERATIONS, NUM_STATES_TO_TRACK, SANDBOX_TIMEOUT
from rpg_agent.routes.completions import router as completions_router
from rpg_agent.routes.sessions import router as sessions_router
from rpg_agent.routes.system import detect_public_url, router as system_router

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
    title="OpenRouter RPG Agent Proxy",
    description=(
        "Proxy that forwards JanitorAI requests to OpenRouter through a "
        "LangGraph agent with code sandbox and dice-rolling tools."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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

    parser = argparse.ArgumentParser(description="RPG Agent Chat Completion Proxy")
    parser.add_argument("--host", default="0.0.0.0", help="Binding host")
    parser.add_argument("--port", type=int, default=default_port, help="Binding port")
    parser.add_argument("--config", help="Path to configs.yaml")
    parser.add_argument("--state-dir", help="Directory where per-session state files are saved")
    parser.add_argument("--key-file", help="Path to the proxy API key file")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload")

    args = parser.parse_args()

    # Pass configurations to module via environment variables before running uvicorn
    if args.config:
        os.environ["RPG_AGENT_CONFIG_PATH"] = args.config
    if args.state_dir:
        os.environ["RPG_AGENT_STATE_DIR"] = args.state_dir
    if args.key_file:
        os.environ["RPG_AGENT_KEY_FILE"] = args.key_file

    uvicorn.run("rpg_agent.proxy:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
