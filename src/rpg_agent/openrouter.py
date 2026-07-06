"""OpenRouter API client for the RPG Agent Proxy."""

import asyncio
import json
from typing import Sequence
import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from rpg_agent.schemas import TOOLS_SCHEMA

def convert_to_openai_messages(messages: Sequence[BaseMessage]) -> list[dict]:
    """Convert LangChain messages to OpenAI-compatible message dicts."""
    openai_msgs = []
    for m in messages:
        if isinstance(m, SystemMessage):
            openai_msgs.append({"role": "system", "content": m.content})
        elif isinstance(m, AIMessage):
            msg = {"role": "assistant"}
            if m.content:
                msg["content"] = m.content
            if m.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"])
                        }
                    }
                    for tc in m.tool_calls
                ]
            rc = m.additional_kwargs.get("reasoning_content")
            if rc:
                msg["reasoning_content"] = rc
            openai_msgs.append(msg)
        elif isinstance(m, ToolMessage):
            openai_msgs.append({
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "name": m.name,
                "content": m.content
            })
        else:
            openai_msgs.append({"role": "user", "content": m.content})
    return openai_msgs

async def call_openrouter_streaming(
    api_key: str,
    base_url: str,
    model: str,
    openai_messages: list[dict],
    stream_queue: asyncio.Queue | None,
) -> tuple[str, str, list[dict]]:
    """Call OpenRouter, streaming reasoning/content chunks to stream_queue if present."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "RPG Agent Proxy",
    }
    payload = {
        "model": model,
        "messages": openai_messages,
        "tools": TOOLS_SCHEMA,
        "stream": stream_queue is not None,
    }
    # Request reasoning explicitly if the provider/model supports it
    payload["extra_body"] = {"include_reasoning": True}

    if stream_queue is not None:
        final_content = []
        final_reasoning = []
        tool_calls_map = {}

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code >= 400:
                    err = await response.aread()
                    raise RuntimeError(f"OpenRouter error: {response.status_code} - {err.decode()}")
                
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    
                    # 1. Parse reasoning_content
                    rc = delta.get("reasoning_content") or delta.get("reasoning")
                    if rc:
                        final_reasoning.append(rc)
                        await stream_queue.put(("reasoning", rc))
                        
                    # 2. Parse content
                    c = delta.get("content")
                    if c:
                        final_content.append(c)
                        await stream_queue.put(("content", c))
                        
                    # 3. Parse tool_calls
                    tcs = delta.get("tool_calls", [])
                    for tc in tcs:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_map:
                            tool_calls_map[idx] = {
                                "id": tc.get("id", ""),
                                "name": tc.get("function", {}).get("name", ""),
                                "arguments": ""
                            }
                        if tc.get("id"):
                            tool_calls_map[idx]["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            tool_calls_map[idx]["name"] = tc["function"]["name"]
                        
                        arg_frag = tc.get("function", {}).get("arguments", "")
                        tool_calls_map[idx]["arguments"] += arg_frag

        tc_list = []
        for idx in sorted(tool_calls_map.keys()):
            tc = tool_calls_map[idx]
            tc_list.append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"]
                }
            })
        return "".join(final_content), "".join(final_reasoning), tc_list
    else:
        # Non-streaming call
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"OpenRouter error: {response.status_code} - {response.text}")
            
            res_json = response.json()
            msg = res_json["choices"][0]["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            tcs = msg.get("tool_calls") or []
            return content, reasoning, tcs
