# RPG Agent Behind Chat Completion

A FastAPI proxy that sits between JanitorAI (or any OpenAI-compatible client) and [OpenRouter](https://openrouter.ai/), forwarding chat completion payloads and logging them for inspection.

## Quick Start

1. Copy `.env.example` to `.env` and set your OpenRouter key:
   ```bash
   cp .env.example .env
   # edit .env and fill in OPENROUTER_API_KEY
   ```

2. Activate the virtual environment:
   ```bash
   source venv/bin/activate
   ```

3. Run the proxy:
   ```bash
   PYTHONPATH=src uvicorn rpg_agent.proxy:app --host 0.0.0.0 --port 8000 --reload
   ```

4. Point your client at `http://localhost:8000/v1/chat/completions`.

Captured payloads are appended to [`docs/example-janitorai-payload.md`](docs/example-janitorai-payload.md).
