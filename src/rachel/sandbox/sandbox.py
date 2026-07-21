"""SOLID Code Sandbox Execution Engine supporting V8 and Python.

Provides execution environments for LLM-generated code snippets to read or
modify RPG state dictionaries.
"""

from __future__ import annotations

import os
from typing import Any
from rachel.sandbox.base import SandboxEngine
from rachel.sandbox.python_engine import PythonSandboxEngine
from rachel.sandbox.v8_engine import V8SandboxEngine

# Expose Base Interface and concrete engines for compatibility
__all__ = ["SandboxEngine", "PythonSandboxEngine", "V8SandboxEngine", "get_sandbox_engine", "execute_sandbox"]

def get_sandbox_engine() -> SandboxEngine:
    """Return the configured SandboxEngine instance based on environment variables."""
    engine_name = os.environ.get("RACHEL_SANDBOX_ENGINE", "v8").strip().lower()
    if engine_name == "python":
        return PythonSandboxEngine()
    else:
        return V8SandboxEngine()

def execute_sandbox(
    code: str,
    state: dict[str, Any],
    timeout_seconds: float = 2.0,
) -> tuple[dict[str, Any], str]:
    """Execute code using the default/configured sandbox engine (compatibility helper)."""
    return get_sandbox_engine().execute(code, state, timeout_seconds)
