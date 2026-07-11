"""Session ID resolution and message-annotation helpers for the OpenRouter proxy.

Implements a three-level session-ID hierarchy (highest → lowest priority):

1. Explicit session ID — from URL path ``/v1/{session_id}/chat/completions``
   or query parameter ``?session_id=…``.
2. OOC tag — a ``[session: name]`` tag found inside any message, scanned
   newest-first so the user can override it at any time.
3. Stable suffix hash + username — MD5 of the last 300 characters of the
   system prompt concatenated with the username extracted from the last user
   message (e.g. ``"Shan Yu: blar"`` → ``"Shan Yu"``).

The username component of option 3 is intentionally extracted from the
*last* user message, but the username itself is expected to remain stable
across a conversation; only the message body changes.

Also provides helpers to extract and strip the ``[proxy: ...]`` annotation
block that the proxy prepends to every assistant reply.
"""

import hashlib
import re
from typing import Any


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_OOC_SESSION_RE = re.compile(r"\[session:\s*([a-zA-Z0-9_\-]+)\]", re.IGNORECASE)

# Matches "PersonaName: message body" — the name is everything before the
# first ": " on the first line of the content.
_USERNAME_RE = re.compile(r"^([^:\n]{1,64}):\s")

_SYSTEM_SUFFIX_CHARS = 300

# Pattern to extract turn_key from a proxy-annotated assistant message.
_TURN_KEY_RE = re.compile(r"\[proxy:.*?turn=([a-f0-9]{24})", re.IGNORECASE)

# Pattern to strip the full [proxy: ...] annotation block (including trailing
# blank lines) from message content.  The block is always a single line of the
# form ``[proxy: session=<sid> turn=<key>]`` optionally followed by one or more
# newlines that separate it from the actual response text.
_PROXY_BLOCK_RE = re.compile(r"\[proxy:[^\]]*\]\n*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Individual extractors
# ---------------------------------------------------------------------------


def extract_ooc_session(messages: list[dict[str, Any]]) -> str | None:
    """Return the value of the first ``[session: name]`` tag found, scanning
    messages from newest to oldest.
    """
    for msg in reversed(messages):
        content = msg.get("content") or ""
        match = _OOC_SESSION_RE.search(content)
        if match:
            return match.group(1)
    return None


def extract_username_from_last_user_message(
    messages: list[dict[str, Any]],
) -> str | None:
    """Return the persona / username prefix of the last user message.

    JanitorAI prefixes user messages with ``"PersonaName: …"``.
    We extract only the name part, which is stable across the conversation.
    """
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        match = _USERNAME_RE.match(content)
        if match:
            return match.group(1).strip()
    return None


def extract_system_suffix_hash(
    messages: list[dict[str, Any]],
    suffix_chars: int = _SYSTEM_SUFFIX_CHARS,
) -> str | None:
    """Return an MD5 hex digest of the last ``suffix_chars`` characters of the
    system prompt. Returns ``None`` if no system message is present.
    """
    for msg in messages:
        if msg.get("role") == "system":
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            suffix = content[-suffix_chars:] if len(content) > suffix_chars else content
            return hashlib.md5(suffix.encode("utf-8")).hexdigest()[:16]
    return None


# ---------------------------------------------------------------------------
# Proxy-annotation helpers
# ---------------------------------------------------------------------------


def extract_prev_turn_key(messages: list[dict[str, Any]]) -> str | None:
    """Scan the messages list (newest first) for the last assistant message
    that carries a ``[proxy: ... turn=<key>]`` annotation and return the key.
    """
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content") or ""
        match = _TURN_KEY_RE.search(content)
        if match:
            return match.group(1)
    return None


def strip_proxy_annotations(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a new messages list with all ``[proxy: ...]`` annotation blocks
    removed from every message's ``content`` field.

    Some LLMs echo the annotation back at the start of their reply because they
    see it in the conversation history.  Stripping it here — after session/turn
    resolution (which needs the annotation) but before the LLM call — prevents
    that hallucination without affecting turn-key or session-ID resolution.

    Only string ``content`` fields are modified; structured content (lists) and
    ``None`` values are left untouched.
    """
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and _PROXY_BLOCK_RE.search(content):
            msg = {**msg, "content": _PROXY_BLOCK_RE.sub("", content)}
        cleaned.append(msg)
    return cleaned


# ---------------------------------------------------------------------------
# Turn key
# ---------------------------------------------------------------------------


def compute_turn_key(session_id: str, messages: list[dict[str, Any]]) -> str:
    """Compute a stable turn key for the current point in the conversation.

    The turn key uniquely identifies a specific turn within a session:

        turn_key = SHA-256[:24](session_id + NUL + last_user_content + NUL + penultimate_assistant_content)

    **Best-effort only**: users can edit any message (system, user, or
    assistant) or retry from any prior turn.  The proxy cannot detect or
    prevent these edits.  The turn key will differ after an edit, which
    means any cached state for the old key becomes stale.  All state indexed
    by turn key must therefore be re-derivable from the ``messages`` array
    alone on a cold start.

    Args:
        session_id: Already-resolved session identifier for this chat.
        messages: Full ``messages`` list from the incoming payload.

    Returns:
        A 24-character lowercase hex string.
    """
    last_user_content = ""
    penultimate_assistant_content = ""

    # Walk backwards to find the last user message and the assistant message
    # that immediately precedes it.
    last_user_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_content = messages[i].get("content") or ""
            last_user_idx = i
            break

    if last_user_idx is not None:
        for i in range(last_user_idx - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                penultimate_assistant_content = messages[i].get("content") or ""
                break

    raw = "\x00".join([session_id, last_user_content, penultimate_assistant_content])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Public resolver
# ---------------------------------------------------------------------------


def resolve_session_id(
    messages: list[dict[str, Any]],
    explicit_session_id: str | None = None,
) -> tuple[str, str]:
    """Resolve the session ID using the three-level hierarchy.

    Returns a tuple of ``(session_id, method)`` where ``method`` is a
    human-readable description of which level matched (for logging).

    Args:
        messages: The ``messages`` list from the incoming payload.
        explicit_session_id: Value from the URL path or query parameter, if any.
    """
    # --- Level 1: Explicit session ID (path or query param) ---
    if explicit_session_id:
        return explicit_session_id, "explicit"

    # --- Level 2: OOC tag inside messages ---
    ooc = extract_ooc_session(messages)
    if ooc:
        return ooc, "ooc-tag"

    # --- Level 3: Stable suffix hash + username ---
    suffix_hash = extract_system_suffix_hash(messages)
    username = extract_username_from_last_user_message(messages)

    if suffix_hash or username:
        parts = filter(None, [suffix_hash, username])
        combined = "__".join(parts)
        return combined, "suffix-hash+username"

    # Fallback — should be rare in practice
    return "unknown-session", "fallback"
