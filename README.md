---
title: RPG Agent Behind Chat Completion
emoji: 🎲
colorFrom: red
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# RPG Agent Behind Chat Completion

A FastAPI proxy that sits between JanitorAI (or any OpenAI-compatible client) and [OpenRouter](https://openrouter.ai/), running request payloads through a stateful LangGraph agent with a secure Python code sandbox and dice rolling tools.

* [Why Use the RPG Agent Proxy?](docs/why-rpg-agent.md) — Core features, benefits, assumptions, and design philosophies.
* [All About Sessions](docs/all-about-sessions.md) — How session IDs are resolved and managed via API endpoints.

## One-Click Deployments

You can deploy your own instance of the RPG Agent proxy to the cloud instantly without configuring local environments:

### 1. Hugging Face Spaces (Free CPU)

Click the button below to duplicate the template Space to your Hugging Face account:

[![Deploy to Hugging Face](https://huggingface.co/datasets/huggingface/badges/resolve/main/deploy-to-spaces-lg.svg)](https://huggingface.co/spaces/edward-law/rab-cc?duplicate=true)

*Note: In the Space settings, make sure to set `OPENROUTER_API_KEY` under **Repository Secrets**. Also set `RPG_AGENT_PROXY_KEY` to your Hugging Face token.*

For step-by-step instructions, see the [Hugging Face Spaces Deployment Guide](docs/deployment-huggingface.md).

### 2. Railway.com

Click the button below to deploy this repository directly to Railway:

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2Fneolaw84%2Frpg-agent-behind-chat-completion)

*Note: Once deployed, go to the **Variables** tab in your Railway service settings and add `OPENROUTER_API_KEY`. You can view the auto-generated proxy API key in the **Logs** tab, or configure your own by setting the `RPG_AGENT_PROXY_KEY` variable.*

For step-by-step instructions, see the [Railway Deployment Guide](docs/deployment-railway.md).

---

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
