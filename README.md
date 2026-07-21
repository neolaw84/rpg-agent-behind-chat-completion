---
title: RACHEL (rachel-proxy)
emoji: 🎲
colorFrom: red
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# RACHEL (rachel-proxy)

**RACHEL** (**R**pg **A**gent **CH**at **E**valuation **L**oop) is a FastAPI proxy that sits between JanitorAI (or any OpenAI-compatible client) and LLM completion providers (OpenRouter, OpenAI, Google Gemini, DeepSeek), running request payloads through a stateful LangGraph agent with a secure Python/V8 code sandbox and dice rolling tools.

* [Why Use RACHEL?](docs/why-rachel.md) — Core features, benefits, assumptions, and design philosophies.
* [All About Sessions](docs/all-about-sessions.md) — How session IDs are resolved and managed via API endpoints.
* [Road to Multi-Tenant](docs/road-to-multi-tenant.md) — Multi-tenant cloud roadmap and architecture.

---

## One-Click Desktop Launchers (Single-Tenant Mode)

Download the release zip for your operating system from [Releases](../../releases) and launch with one click:

### Windows
1. Unzip `rachel-proxy-vX.X.X-win-x64.zip`.
2. Double-click `launch.bat`.
3. *Security Warning Bypass*: If Windows SmartScreen displays *"Windows protected your PC"*, click **More info** $\rightarrow$ **Run anyway**.

### macOS
1. Unzip `rachel-proxy-vX.X.X-mac-arm64.zip` (Apple Silicon) or `rachel-proxy-vX.X.X-mac-x64.zip` (Intel).
2. Double-click `launch.command`.
3. *Security Warning Bypass*: If macOS blocks execution (*"Unidentified Developer"*), open **System Settings** $\rightarrow$ **Privacy & Security** $\rightarrow$ click **Open Anyway**, or run `xattr -cr launch.command` in Terminal.

### Linux
1. Unzip `rachel-proxy-vX.X.X-linux-x64.zip`.
2. Double-click `launch.sh` (or `rachel-proxy.desktop`).

---

## Initial Setup & LLM Provider Credentials

Once the proxy starts, open the Admin Console in your browser at `http://localhost:8000`:

1. **Proxy API Key**: Enter the local admin key (printed to console logs or saved in `data/proxy.key`).
2. **Provider Credentials**: Configure your preferred provider (**OpenRouter BYOK / PKCE**, **OpenAI**, **Google Gemini**, or **DeepSeek**) directly in the **Provider Credentials** card.
3. Select your **Active Provider** and save settings.

Captured payloads are appended to [`docs/example-janitorai-payload.md`](docs/example-janitorai-payload.md).
