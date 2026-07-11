import json
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

import os
os.environ["OPENROUTER_API_KEY"] = "mock_key"

from rpg_agent.proxy import app
from rpg_agent.auth import PROXY_API_KEY
from rpg_agent.core.state import SessionStateStore


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def auth_headers():
    return {"Authorization": f"Bearer {PROXY_API_KEY}"}


@patch("rpg_agent.routes.completions.run_agent", new_callable=AsyncMock)
def test_unauthorized_request(mock_run, client):
    """Verify that requests without a valid Bearer token are rejected with 401."""
    resp = client.post("/v1/chat/completions", json={"messages": []})
    assert resp.status_code == 401
    mock_run.assert_not_called()


@pytest.mark.parametrize("engine_name", ["v8", "python"])
@patch("rpg_agent.routes.completions.run_agent", new_callable=AsyncMock)
def test_normal_flow_and_persistence(mock_run, client, auth_headers, tmp_path, engine_name):
    """Verify normal non-streaming request flow and state persistence."""
    mock_run.return_value = {
        "content": f"Hello player from {engine_name}!",
        "reasoning_content": "Thinking...",
        "after_state": {"gold": 100},
    }

    env_patch = {"RPG_AGENT_SANDBOX_ENGINE": engine_name}

    with patch.dict(os.environ, env_patch):
        # Use patch for state storage dir to keep it clean
        with patch("rpg_agent.routes.completions.STATE_STORAGE_DIR", tmp_path):
            payload = {
                "messages": [
                    {"role": "system", "content": "You are a GM."},
                    {"role": "user", "content": "hello: hi proxy"},
                ],
                "model": "google/gemini-flash-1.5",
            }

            resp = client.post("/v1/chat/completions", json=payload, headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            assert f"Hello player from {engine_name}!" in content
            assert "[proxy: session=" in content
            
            # Verify call arguments
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert kwargs["before_state"] == {}

            # The response must contain the annotation with session ID and turn key
            import re
            m = re.search(r"\[proxy:\s*session=([^\s]+)\s*turn=([a-f0-9]{24})\]", content)
            assert m is not None
            session_id = m.group(1)
            turn_key = m.group(2)

            # Verify that state was written to disk
            store = SessionStateStore(session_id, tmp_path)
            assert store.get_before_state(turn_key) == {"gold": 100}


@pytest.mark.parametrize("engine_name", ["v8", "python"])
@patch("rpg_agent.routes.completions.run_agent", new_callable=AsyncMock)
def test_cache_miss_handling(mock_run, client, auth_headers, tmp_path, engine_name):
    """Verify that a cache miss does not return 400 but treats request as if new,
    appending the OOC recovery message.
    """
    mock_run.return_value = {
        "content": f"A new quest begins with {engine_name}!",
        "after_state": {"quest": "active"},
    }

    env_patch = {"RPG_AGENT_SANDBOX_ENGINE": engine_name}

    with patch.dict(os.environ, env_patch):
        with patch("rpg_agent.routes.completions.STATE_STORAGE_DIR", tmp_path):
            payload = {
                "messages": [
                    {"role": "system", "content": "You are a GM."},
                    {"role": "assistant", "content": "[proxy: session=test-session-miss turn=deadbeefdeadbeefdeadbeef]\n\nHello player!"},
                    {"role": "user", "content": "test_user: let's proceed"},
                ],
                "model": "google/gemini-flash-1.5",
            }

            resp = client.post("/v1/chat/completions", json=payload, headers=auth_headers)
            assert resp.status_code == 200
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            
            # Should contain OOC message
            assert "OOC: A state cache miss occurred" in content
            assert f"A new quest begins with {engine_name}!" in content

            # Run agent should have been called with empty before_state
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert kwargs["before_state"] == {}

            # Verify new turn state was saved under computed turn key
            import re
            m = re.search(r"\[proxy:\s*session=([^\s]+)\s*turn=([a-f0-9]{24})\]", content)
            assert m is not None
            session_id = m.group(1)
            turn_key = m.group(2)

            store = SessionStateStore(session_id, tmp_path)
            assert store.get_before_state(turn_key) == {"quest": "active"}


@pytest.mark.parametrize("engine_name", ["v8", "python"])
@patch("rpg_agent.routes.completions.run_agent", new_callable=AsyncMock)
def test_streaming_cache_miss(mock_run, client, auth_headers, tmp_path, engine_name):
    """Verify that streaming response handles cache miss by appending the OOC notice chunk."""
    async def mock_run_streaming(*args, **kwargs):
        stream_queue = kwargs.get("stream_queue")
        if stream_queue:
            await stream_queue.put(("reasoning", "Thinking... "))
            await stream_queue.put(("content", f"Streaming events from {engine_name}!"))
        return {
            "content": f"Streaming events from {engine_name}!",
            "after_state": {"stream_state": 42},
        }

    mock_run.side_effect = mock_run_streaming
    env_patch = {"RPG_AGENT_SANDBOX_ENGINE": engine_name}

    with patch.dict(os.environ, env_patch):
        with patch("rpg_agent.routes.completions.STATE_STORAGE_DIR", tmp_path):
            payload = {
                "messages": [
                    {"role": "system", "content": "You are a GM."},
                    {"role": "assistant", "content": "[proxy: session=test-stream-miss turn=deadbeefdeadbeefdeadbeef]\n\nHello player!"},
                    {"role": "user", "content": "test_user: stream to me"},
                ],
                "model": "google/gemini-flash-1.5",
                "stream": True,
            }

            resp = client.post("/v1/chat/completions", json=payload, headers=auth_headers)
            assert resp.status_code == 200
            
            # Accumulate streaming text
            full_content = ""
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    chunk_str = line[len("data: "):].strip()
                    if chunk_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(chunk_str)
                        delta = chunk["choices"][0]["delta"]
                        if "content" in delta:
                            full_content += delta["content"]
                    except json.JSONDecodeError:
                        pass

            # Verify that OOC recovery message is included at the end of content
            assert "OOC: A state cache miss occurred" in full_content
            assert f"Streaming events from {engine_name}!" in full_content
