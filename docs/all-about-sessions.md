# All About Sessions

In the RPG Agent Proxy, a **Session** holds the persistent game state (such as attributes, inventory items, health points, and history) for a specific chat or character. 

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

Whenever you send a chat completion request to the proxy, it automatically determines which session to load using a **3-level hierarchy** (highest priority to lowest):

### 1. Explicit Session ID (Highest Priority)
You can force the proxy to use a specific session ID by placing it directly in the API URL or query string:
* **URL Path**: Point your client at `https://<your-proxy-domain>/v1/<session-id>/chat/completions`
* **Query Parameter**: Point your client at `https://<your-proxy-domain>/v1/chat/completions?session_id=<session-id>`

This is the most reliable way to isolate games when using JanitorAI or other custom clients.

### 2. Out-Of-Character (OOC) Tag
If no explicit session ID is set in the URL, the proxy scans your message history (newest to oldest) looking for a session tag:
* **Format**: `[session: name_here]` or `[session: my_campaign]` inside any message.
* The proxy will extract `name_here` and use it as the session ID.

### 3. Implicit Hash & Username (Lowest Priority / Fallback)
If no explicit URL parameter or OOC tag is found, the proxy automatically calculates a fallback session ID by combining:
1. An MD5 hash of the last 300 characters of the system prompt.
2. The username/persona prefix from the last user message (e.g., `"Shan Yu: I attack the guard"` yields `"Shan Yu"`).

This ensures that even if you configure nothing, different characters or users will automatically get isolated states.

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

### 2. Reset Session History (Update/Clear)
Clears the turn history for a session, effectively wiping its state cache while retaining the session ID itself.
* **Method**: `POST`
* **Endpoint**: `/v1/sessions/{session_id}/reset`
* **Response Example**:
  ```json
  {
    "status": "reset",
    "session_id": "campaign_1"
  }
  ```

### 3. Delete Session (Delete)
Completely deletes the session state file from disk. The next request with this session ID will start from a cold start (empty state).
* **Method**: `DELETE`
* **Endpoint**: `/v1/sessions/{session_id}`
* **Response Example**:
  ```json
  {
    "status": "deleted",
    "session_id": "campaign_1"
  }
  ```
