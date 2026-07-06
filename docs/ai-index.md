# AI & Developer Guidance Index

Welcome to the RPG Agent Behind Chat Completion repository! This file serves as the main index for developer and AI rules, conventions, and workflows.

## TABBOOS 

* NEVER ATTEMPT TO READ `.env` and other hidden variables. 

## Project Structure
- `src/rpg_agent/`: Main source package.
  - `proxy.py`: FastAPI OpenRouter chat completion proxy.
  - `session.py`: Session ID resolution and turn-key computation.
- `tests/`: Project unit and integration tests.
- `notebooks/`: Jupyter notebooks for experiments and prototyping.
- `docs/`: Project documentation.
  - `ai-index.md`: This file — central developer/AI guidance index.
- `data/` (Gitignored):
  - `example-janitorai-payload.md`: Auto-generated log of every payload received by the proxy.

## Running the Proxy

```bash
# Activate the venv first
source venv/bin/activate

# Run the proxy (auto-reloads on code changes)
PYTHONPATH=src uvicorn rpg_agent.proxy:app --host 0.0.0.0 --port 8000 --reload
```

The proxy listens at `http://localhost:8000/v1/chat/completions` and forwards requests to OpenRouter.
Every incoming payload is appended verbatim to `data/example-janitorai-payload.md`.


## Guidelines
- Follow standard PEP 8 coding styles.
- Use `pytest` for running test suites.
- **Virtual Environment (`venv`)**:
  - Always use a virtual environment named `venv` located in the repository root.
  - If `venv` does not exist:
    - Build it using an existing Python 3.12 conda environment named `py312`.
    - If the `py312` conda environment does not exist but `conda` is available, create the `py312` environment first.
    - If `conda` is not available, use whatever Python environment is available and print out a warning.

## Session & State Design

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
- **Retry** any turn (re-submit the same payload).
- **Edit** any system or user message at any point and re-submit.

These operations are indistinguishable from a new request at the proxy level.
The proxy cannot prevent or detect mid-conversation edits.

**Design rule**: Any state the proxy maintains must be:
1. **Indexed by turn key** — so retries at the same point rehydrate the same state.
2. **Derivable from the `messages` array alone** — so a cold-start proxy can always reconstruct state from scratch without prior history.

The `messages` array is the ground truth. The proxy state store is a cache, not the source of truth.
