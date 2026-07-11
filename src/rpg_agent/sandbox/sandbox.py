"""SOLID Code Sandbox Execution Engine supporting V8 and Python.

Provides execution environments for LLM-generated code snippets to read or
modify RPG state dictionaries.
"""

from __future__ import annotations

import io
import logging
import multiprocessing
import traceback
import os
from abc import ABC, abstractmethod
from contextlib import redirect_stdout
from typing import Any

# Safe Python standard libraries pre-imported for Python engine
import math
import random
import json
import datetime
import collections
import itertools
import functools
import re
import string

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base Sandbox Interface
# ---------------------------------------------------------------------------

class SandboxEngine(ABC):
    """Abstract base class representing a code sandbox execution engine."""

    @property
    @abstractmethod
    def name(self) -> str:
        """The identifier of the engine (e.g. 'v8', 'python')."""
        pass

    @abstractmethod
    def execute(
        self,
        code: str,
        state: dict[str, Any],
        timeout_seconds: float = 2.0,
    ) -> tuple[dict[str, Any], str]:
        """Execute the given code to mutate `state` and return (updated_state, output_logs)."""
        pass


# ---------------------------------------------------------------------------
# Python Sandbox Engine Implementation
# ---------------------------------------------------------------------------

# Allowed modules to import in the Python sandbox
ALLOWED_PYTHON_MODULES = {
    "math", "time", "json", "random",
    "datetime", "collections", "itertools", "functools", "re", "string"
}

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in ALLOWED_PYTHON_MODULES:
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"Import of module '{name}' is not allowed in this sandbox.")

_SAFE_BUILTINS: dict[str, Any] = {
    # Singletons
    "None": None,
    "True": True,
    "False": False,
    # Types
    "bool": bool,
    "int": int,
    "float": float,
    "str": str,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "frozenset": frozenset,
    "bytes": bytes,
    # Iteration / functional
    "len": len,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "reversed": reversed,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "all": all,
    "any": any,
    # Type inspection (safe subset)
    "isinstance": isinstance,
    "issubclass": issubclass,
    "type": type,
    # String / repr
    "repr": repr,
    "print": print,  # captured via redirect_stdout in child
    # Exceptions (raise / catch)
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "StopIteration": StopIteration,
    # Safe Import
    "__import__": _safe_import,
}

_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": _SAFE_BUILTINS,
    "math": math,
    "random": random,
    "json": json,
    "datetime": datetime,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
    "re": re,
    "string": string,
}

def _python_worker(
    code: str,
    state: dict[str, Any],
    result_queue: multiprocessing.Queue,
) -> None:
    stdout_buf = io.StringIO()
    local_ns: dict[str, Any] = {"state": state}

    try:
        with redirect_stdout(stdout_buf):
            exec(code, dict(_SAFE_GLOBALS), local_ns)  # noqa: S102
    except Exception:  # noqa: BLE001
        stdout_buf.write("\n--- Sandbox Exception ---\n")
        stdout_buf.write(traceback.format_exc())

    updated_state = local_ns.get("state", state)
    if not isinstance(updated_state, dict):
        stdout_buf.write(
            "\n--- Sandbox Warning: 'state' was replaced with a non-dict; "
            "reverting to original state. ---\n"
        )
        updated_state = state

    result_queue.put((updated_state, stdout_buf.getvalue()))


class PythonSandboxEngine(SandboxEngine):
    """Execution engine for restricted pure Python code."""

    @property
    def name(self) -> str:
        return "python"

    def execute(
        self,
        code: str,
        state: dict[str, Any],
        timeout_seconds: float = 2.0,
    ) -> tuple[dict[str, Any], str]:
        ctx = multiprocessing.get_context("spawn")
        result_queue: multiprocessing.Queue = ctx.Queue()

        proc = ctx.Process(
            target=_python_worker,
            args=(code, dict(state), result_queue),
            daemon=True,
        )
        proc.start()
        proc.join(timeout=timeout_seconds)

        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)
            if proc.is_alive():
                proc.kill()
            logger.warning("Python sandbox timed out after %.1fs and was killed.", timeout_seconds)
            return state, f"[Sandbox timed out after {timeout_seconds}s — execution aborted]"

        if not result_queue.empty():
            updated_state, output = result_queue.get_nowait()
            return updated_state, output

        logger.error("Python sandbox worker exited without producing a result (exit code %s).", proc.exitcode)
        return state, f"[Sandbox worker crashed unexpectedly (exit code {proc.exitcode})]"


# ---------------------------------------------------------------------------
# V8 JavaScript Sandbox Engine Implementation
# ---------------------------------------------------------------------------

def _v8_worker(
    code: str,
    state: dict[str, Any],
    result_queue: multiprocessing.Queue,
) -> None:
    from py_mini_racer import MiniRacer
    import json

    # Redefine console.log to redirect prints to our logs buffer
    js_init = """
    var _logs = [];
    var console = {
        log: function() {
            var args = Array.prototype.slice.call(arguments);
            var msg = args.map(function(x) {
                if (x === null) return "null";
                if (x === undefined) return "undefined";
                if (typeof x === 'object') {
                    try { return JSON.stringify(x); } catch(e) { return String(x); }
                }
                return String(x);
            }).join(' ');
            _logs.push(msg);
        }
    };
    """

    # Inject current RPG state
    state_json = json.dumps(state, ensure_ascii=False)
    js_init += f"\nvar state = {state_json};\n"

    # Wrap inside IIFE and catch execution exceptions
    js_run = f"""
    try {{
        (function() {{
            {code}
        }})();
    }} catch (e) {{
        _logs.push("--- Sandbox Exception ---");
        _logs.push(e.stack || e.toString());
    }}
    JSON.stringify({{state: state, logs: _logs}});
    """

    try:
        ctx = MiniRacer()
        ctx.eval(js_init)
        result_str = ctx.eval(js_run)
        res = json.loads(result_str)
        updated_state = res.get("state", state)
        if not isinstance(updated_state, dict):
            logs = "\n".join(res.get("logs", [])) + (
                "\n--- Sandbox Warning: 'state' was replaced with a non-object; "
                "reverting to original state. ---\n"
            )
            updated_state = state
        else:
            logs = "\n".join(res.get("logs", []))
    except Exception as exc:
        updated_state = state
        logs = f"--- Sandbox Exception ---\n{traceback.format_exc()}"

    result_queue.put((updated_state, logs))


class V8SandboxEngine(SandboxEngine):
    """Execution engine for sandboxed JavaScript via V8 isolates."""

    @property
    def name(self) -> str:
        return "v8"

    def execute(
        self,
        code: str,
        state: dict[str, Any],
        timeout_seconds: float = 2.0,
    ) -> tuple[dict[str, Any], str]:
        ctx = multiprocessing.get_context("spawn")
        result_queue: multiprocessing.Queue = ctx.Queue()

        proc = ctx.Process(
            target=_v8_worker,
            args=(code, dict(state), result_queue),
            daemon=True,
        )
        proc.start()
        proc.join(timeout=timeout_seconds)

        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)
            if proc.is_alive():
                proc.kill()
            logger.warning("V8 sandbox timed out after %.1fs and was killed.", timeout_seconds)
            return state, f"[Sandbox timed out after {timeout_seconds}s — execution aborted]"

        if not result_queue.empty():
            updated_state, output = result_queue.get_nowait()
            return updated_state, output

        logger.error("V8 sandbox worker exited without producing a result (exit code %s).", proc.exitcode)
        return state, f"[Sandbox worker crashed unexpectedly (exit code {proc.exitcode})]"


# ---------------------------------------------------------------------------
# Factory & Helpers
# ---------------------------------------------------------------------------

def get_sandbox_engine() -> SandboxEngine:
    """Return the configured SandboxEngine instance based on environment variables."""
    engine_name = os.environ.get("RPG_AGENT_SANDBOX_ENGINE", "v8").strip().lower()
    if engine_name == "python":
        return PythonSandboxEngine()
    return V8SandboxEngine()


def execute_sandbox(
    code: str,
    state: dict[str, Any],
    timeout_seconds: float = 2.0,
) -> tuple[dict[str, Any], str]:
    """Execute code using the default/configured sandbox engine (compatibility helper)."""
    return get_sandbox_engine().execute(code, state, timeout_seconds)
