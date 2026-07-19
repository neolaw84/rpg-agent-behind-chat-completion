# All About Sessions

In the RPG Agent Proxy, a **Session** holds the persistent game state for a specific chat or character. A session state is structured into four distinct components:

* **`state`**: The dynamic, user-defined game state (e.g. inventory, character stats, location) that is read and mutated by sandbox code.
* **`plan`**: The narrative progression checklist of upcoming goals and NPC plans.
* **`summary`**: The rolling story summary of events that have occurred so far (appended periodically or probabilistically).
* **`hidden_state`**: Mechanistic variables hidden from the player but visible to the LLM (e.g. status effect durations, secret parameters).

This document explains how session IDs are resolved and how you can manage (CRUD) active sessions using the proxy's built-in API endpoints.

---

## The Default Behavior (Zero-Configuration for Non-Tech Users)

If you are a non-technical user, **you do not need to configure anything manually**:

1. **Zero Setup**: Simply point JanitorAI to the basic URL: `https://<your-proxy-domain>/v1/chat/completions`. You do not need to append any session ID to the URL.
2. **Auto-Grouping**: The proxy will automatically generate a stable session ID for your chat based on the character's system settings and your username. Different chats will automatically get their own isolated memories and states.
3. **Finding Your Session ID**: Every response from the proxy starts with a small annotation at the top of the message:
   `[proxy: session=some-generated-id turn=some-turn-hash]`
   This annotation is visible directly in your chat interface. The value of `session` is your active Session ID.
4. **Wiping or Resetting Memory**: If you ever want to reset the proxy's state/memory for your chat, copy that `session` value from your chat window and use it with the Reset API endpoint described below (or override it in the chat using an OOC tag).

---

## Part 1: How Session IDs are Resolved

Whenever you send a chat completion request to the proxy, it automatically determines which session to load using a **4-level hierarchy** (highest priority to lowest):

### 1. Explicit Session ID (Highest Priority)
You can force the proxy to use a specific session ID by placing it directly in the API URL or query string:
* **URL Path**: Point your client at `https://<your-proxy-domain>/v1/<session-id>/chat/completions`
* **Query Parameter**: Point your client at `https://<your-proxy-domain>/v1/chat/completions?session_id=<session-id>`

This is the most reliable way to isolate games when using JanitorAI or other custom clients.

### 2. Out-Of-Character (OOC) Tag
If no explicit session ID is set in the URL, the proxy scans your message history (newest to oldest) looking for a session tag:
* **Format**: `[session: name_here]` or `[session: my_campaign]` inside any message.
* The proxy will extract `name_here` and use it as the session ID.

### 3. Session ID from Proxy Annotation
If no explicit session ID or OOC tag is found, the proxy scans assistant messages (newest to oldest) to find the last assistant message carrying a `[proxy: session=some-id turn=...]` annotation block and extracts `some-id` to reuse.

### 4. Implicit Hash & Username (Lowest Priority / Fallback)
If no prior level resolves the session ID, the proxy automatically calculates a fallback session ID by combining:
1. An MD5 hash of the first assistant message's suffix (last 300 characters with all whitespaces/spaces removed).
2. An MD5 hash of the username/persona prefix from the last user message (e.g., `"Shan Yu: I attack"` yields the MD5 hash of `"Shan Yu"`).

These two hashes are concatenated with double underscores, e.g. `<hash_of_message_suffix>__<hash_of_username>`. This ensures that different characters or users will automatically get isolated states.

---

## Part 2: Session CRUD Endpoints

The proxy provides endpoints to manage active sessions. All administrative endpoints require authentication. You must include your **Proxy API Key** as a Bearer Token in the headers of these requests:

`Authorization: Bearer <your-proxy-api-key>`

### 1. List Active Sessions (Read)
Lists all active session IDs that currently have state files stored on disk.
* **Method**: `GET`
* **Endpoint**: `/v1/sessions`
* **Response Example**:
  ```json
  {
    "sessions": ["campaign_1", "shan-yu-solo", "test-user"],
    "count": 3
  }
  ```

### 2. Get Session Details (Read Single)
Returns the complete history and current 4-element state for a specific session.
* **Method**: `GET`
* **Endpoint**: `/v1/sessions/{session_id}`
* **Response Example**:
  ```json
  {
    "session_id": "campaign_1",
    "current_state": {
      "state": {
        "gold": 100,
        "hp": 95
      },
      "plan": ["find dungeon key"],
      "summary": "The party entered the dungeon.",
      "hidden_state": {
        "poison_turns": 3
      }
    },
    "turn_count": 1,
    "turns": [
      {
        "turn_key": "abc123xyz...",
        "before": {
          "state": {},
          "plan": [],
          "summary": "",
          "hidden_state": {}
        },
        "after": {
          "state": {"gold": 100, "hp": 95},
          "plan": ["find dungeon key"],
          "summary": "The party entered the dungeon.",
          "hidden_state": {"poison_turns": 3}
        }
      }
    ]
  }
  ```

### 3. Reset Session History (Update/Clear)
Clears the turn history for a session, effectively wiping its state cache while retaining the session ID itself.
* **Method**: `POST`
* **Endpoint**: `/v1/sessions/{session_id}/reset`
* **Response Example**:
  ```json
  {
    "status": "ok",
    "message": "Session campaign_1 has been reset."
  }
  ```

### 4. Delete Session (Delete)
Completely deletes the session state file from disk. The next request with this session ID will start from a cold start (empty state).
* **Method**: `DELETE`
* **Endpoint**: `/v1/sessions/{session_id}`
* **Response Example**:
  ```json
  {
    "status": "ok",
    "message": "Session campaign_1 deleted."
  }
  ```
