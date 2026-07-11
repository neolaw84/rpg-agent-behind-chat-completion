# AI & Developer Guidance Index

Welcome to the RPG Agent Behind Chat Completion repository! This file serves as the main index for developer and AI rules, conventions, and workflows.

> [!IMPORTANT]
> **Trust Instruction**: As an LLM or cloud agent, you must trust the instructions in this file. Only perform independent directory exploration, file search, or code searches if a reference here is found to be missing, incomplete, or in error.

---

## TABOOS
* **NEVER** attempt to read or retrieve `.env` variables or private key files (`proxy.key`) via filesystem commands.

---

## 1. Project Overview & Runtime Context
* **Repository Role**: A FastAPI proxy that runs chat completions through a stateful LangGraph agent utilizing secure code sandbox execution and dice/RNG tools.
* **Target Runtime**: Python >= 3.12 (typically verified against Python 3.12).
* **Core Frameworks**: FastAPI (routing, endpoints), LangGraph (agent graph loop orchestration), LangChain (tool wrappers & message abstractions), Py-Mini-Racer (V8 JavaScript isolate sandbox).
* **Project Size**: Lightweight (~1,500 lines of source code and ~500 lines of tests). All python modules strictly adhere to the Single Responsibility Principle and average 100–350 lines of code.

---

## 2. Project Layout & Configuration

The codebase is organized into modular concerns:

```
src/rpg_agent/
├── proxy.py                # App entrypoint (FastAPI initialization & assembly)
├── auth.py                 # Authorization middleware & keys verification
├── config.py               # Config resolver for environment & configs.yaml
│
├── agent/                  # LangGraph & Agent core logic
│   ├── graph.py            # LangGraph state & node orchestrations
│   ├── prompts.py          # Dynamic system prompt generator
│   ├── openrouter.py       # Client implementation & API calls
│   ├── reasoning_formats.py # Model configurations
│   └── tools.py            # LangChain tool registrations (sandbox, dice, RNG)
│
├── core/                   # Session & Core Domain Logic
│   ├── session.py          # Session parsing & turn-key generation
│   └── state.py            # SessionStateStore (LRU files tracking)
│
├── routes/                 # API controllers / HTTP handlers
│   ├── completions.py      # POST /v1/chat/completions
│   ├── sessions.py         # Session CRUD management
│   └── system.py           # Dashboard SPA, health, status endpoints
│
├── sandbox/                # Isolated code execution layers
│   ├── sandbox.py          # SandboxEngine interface definition & implementations
│   └── schemas.py          # JSON Schemas for OpenRouter tool definitions
│
└── templates/              # HTML & static template files
    └── index.html          # SPA dashboard front-end page
```

### Configuration Files
* **[configs.yaml](file:///home/neolaw/projects/rpg-agent-behind-chat-completion/configs.yaml)**: Preserves state limits (`num_states_to_track`), sandbox timeout limits (`timeout_seconds`), LangGraph limits (`max_iterations`), and LLM endpoints/models.
* **[pyproject.toml](file:///home/neolaw/projects/rpg-agent-behind-chat-completion/pyproject.toml)**: Defines package dependency specifications and Hatch building config.

---

## 3. Setup, Run, and Validation Steps

Always perform tasks in the following order:

### A. Environment Bootstrapping
Always use a virtual environment named `venv` located in the repository root:
```bash
# 1. Create venv (if it does not exist)
python3.12 -m venv venv

# 2. Activate venv
source venv/bin/activate

# 3. Install packages in editable mode with development dependencies
pip install -e ".[dev]"
```
*Note on Python 3.12 Fallbacks:*
* If `python3.12` is not available but `conda` is, check if a conda environment named `py312` exists. If not, create it first:
  ```bash
  conda create -n py312 python=3.12 -y
  conda activate py312
  ```
* If `conda` is not available or cannot be used, try using any other Python runtime >= 3.12 on the host (e.g. `python3`, `python3.13`).
* If no Python >= 3.12 environment exists on the system, fall back to the available `python3` runtime and print out a warning (some type annotations or dependencies might fail on Python <= 3.11).

### B. Running the Test Suite
Always validate code changes by running `pytest`. Preconditions: the `venv` must be activated.
```bash
venv/bin/pytest
```
*Expected output: All test cases under `tests/` pass successfully (average execution time < 3s).*

### C. Running the Proxy
Ensure you copy `.env.example` to `.env` and set a valid `OPENROUTER_API_KEY` before starting the server.
```bash
# Activate the venv first
source venv/bin/activate

# Run the proxy (auto-reloads on code changes)
PYTHONPATH=src uvicorn rpg_agent.proxy:app --host 0.0.0.0 --port 8000 --reload
```
* The proxy listens at `http://localhost:8000/v1/chat/completions` and forwards requests to OpenRouter.
* Every incoming payload is appended verbatim to `data/example-janitorai-payload.md`.
* The dashboard and system health status are available at `http://localhost:8000/`.

---

## 4. Session & State Design

### Session ID
Resolved per-request using a three-level hierarchy (highest → lowest priority):
1. **Explicit** — URL path `/v1/{session_id}/chat/completions` or query param `?session_id=`.
2. **OOC tag** — `[session: name]` inside any message, scanned newest-first.
3. **Suffix hash + username** — MD5 of last 300 chars of system prompt, concatenated with the persona name prefix of the last user message (e.g. `"Shan Yu: blar"` → `"Shan Yu"`).

### Turn Key
Each distinct point in a conversation is identified by a **turn key**:
```
turn_key = SHA-256[:24](session_id + "\0" + last_user_msg_content + "\0" + penultimate_assistant_msg_content)
```
The turn key is injected into the **message text** of every response, prepended as a plain-text annotation:
```
[proxy: session=<session_id> turn=<turn_key>]

<actual assistant response>
```

This makes it visible in the client's chat UI (JanitorAI renders it as part of the message) and ensures it can be copy-pasted or referenced by the user at any time.

### Best-Effort State Rehydration

> **All proxy state is maintained on a best-effort basis.**

The client (JanitorAI) allows users to:
* **Retry** any turn (re-submit the same payload).
* **Edit** any system or user message at any point and re-submit.

These operations are indistinguishable from a new request at the proxy level.
The proxy cannot prevent or detect mid-conversation edits.

**Design rule**: Any state the proxy maintains must be:
1. **Indexed by turn key** — so retries at the same point rehydrate the same state.
2. **Derivable from the `messages` array alone** — so a cold-start proxy can always reconstruct state from scratch without prior history.

The `messages` array is the ground truth. The proxy state store is a cache, not the source of truth.
