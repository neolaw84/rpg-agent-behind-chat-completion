"""Integration test for the LangGraph agent execution and streaming queue."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, SystemMessage

from rachel.agent.graph import run_agent, _convert_messages


@pytest.mark.asyncio
async def test_run_agent_flow_with_streaming():
    """Verify that run_agent correctly puts reasoning chunks, tool execution logs,
    and final content chunks onto the provided stream_queue.
    """
    stream_queue = asyncio.Queue()
    before_state = {"hp": 100}

    # Custom responses to simulate 2 iterations of the LLM node:
    # Iteration 1: Calls execute_code_sandbox
    # Iteration 2: Final text response
    mock_responses = [
        # Response 1
        {
            "choices": [{
                "delta": {
                    "reasoning_content": "Checking player health first...",
                }
            }]
        },
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "call_123",
                        "function": {
                            "name": "execute_code_sandbox",
                            "arguments": '{"code": "state[\'hp\'] -= 20"}'
                        }
                    }]
                }
            }]
        },
        # DONE indicator for Iteration 1 stream
        "[DONE]",

        # Response 2 (Final)
        {
            "choices": [{
                "delta": {
                    "content": "You took damage! Your HP is now 80."
                }
            }]
        },
        "[DONE]"
    ]

    mock_response_idx = 0

    class MockStreamResponse:
        def __init__(self, status_code=200):
            self.status_code = status_code

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_lines(self):
            nonlocal mock_response_idx
            # Yield lines for the current mock response stream
            while mock_response_idx < len(mock_responses):
                val = mock_responses[mock_response_idx]
                mock_response_idx += 1
                if val == "[DONE]":
                    yield "data: [DONE]"
                    break
                else:
                    yield f"data: {json.dumps(val)}"

    def mock_stream(*args, **kwargs):
        return MockStreamResponse()

    # Patch httpx.AsyncClient.stream
    with patch("httpx.AsyncClient.stream", side_effect=mock_stream):
        result = await run_agent(
            messages=[{"role": "user", "content": "attack me"}],
            before_state=before_state,
            api_key="mock_key",
            base_url="https://mock-openrouter/api/v1/chat/completions",
            model="mock-model",
            sandbox_timeout=1.0,
            max_iterations=5,
            stream_queue=stream_queue,
        )

        # 1. Assert return payload values
        assert result["content"] == "You took damage! Your HP is now 80."
        assert result["after_state"] == {"hp": 80}

        # 2. Extract queue items to check the exact order of events
        events = []
        while not stream_queue.empty():
            events.append(await stream_queue.get())

        # Ensure we captured:
        # - Reasoning chunks from Iteration 1
        # - Tool start log from Tool Node
        # - Sandbox execution output from Tool Node
        # - Content chunks from Iteration 2
        assert len(events) > 0
        
        # Verify reasoning event was captured
        reasoning_events = [val for ctype, val in events if ctype == "reasoning"]
        assert len(reasoning_events) > 0
        assert "Checking player health" in reasoning_events[0]

        # Verify tool log event was captured
        tool_events = [val for ctype, val in events if ctype == "tool_log"]
        assert len(tool_events) >= 2
        assert any("Calling tool: execute_code_sandbox" in e for e in tool_events)
        assert any("[Output]" in e for e in tool_events)

        # Verify content event was captured
        content_events = [val for ctype, val in events if ctype == "content"]
        assert len(content_events) > 0
        assert "You took damage!" in content_events[0]
