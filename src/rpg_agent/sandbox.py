"""Pure Python Restricted Code Sandbox.

Executes an LLM-generated Python code snippet in a restricted environment with:
  - A stripped ``__builtins__`` to block dangerous system-level access.
  - A configurable wall-clock timeout enforced via ``multiprocessing`` so that
    a runaway infinite loop is **hard-killed** (unlike threads, a subprocess
    can be terminated with SIGKILL/TerminateProcess).
  - A mutable ``state`` dict (the current turn's ``before`` state) injected
    into the execution namespace so the code can read and update RPG state.

Security note
-------------
This sandbox uses Python's ``exec()`` with a restricted globals dict running in
a child process.  It is NOT equivalent to OS-level isolation (e.g. Docker).
Language-level restrictions can be escaped by determined adversarial code.
This is intentional: the system is for entertainment and runs locally or in
trusted cloud environments.  The subprocess boundary is the key safety layer
— a runaway loop or crash cannot hang the parent proxy server.
"""

from __future__ import annotations

import io
import logging
import multiprocessing
import traceback
from contextlib import redirect_stdout
from typing import Any

logger = logging.getLogger(__name__)


import math
import random

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in ("math", "random"):
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
}


# ---------------------------------------------------------------------------
# Worker function (runs in child process)
# ---------------------------------------------------------------------------

def _worker(
    code: str,
    state: dict[str, Any],
    result_queue: "multiprocessing.Queue[tuple[dict, str]]",
) -> None:
    """Execute ``code`` inside a restricted namespace and push results to the
    queue.  Any exception is caught and serialised into the output string.
    """
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_sandbox(
    code: str,
    state: dict[str, Any],
    timeout_seconds: float = 2.0,
) -> tuple[dict[str, Any], str]:
    """Run ``code`` in an isolated child process with a hard timeout.

    The child process is forcibly terminated (SIGKILL / TerminateProcess) if
    it does not finish within ``timeout_seconds``, preventing runaway loops
    from blocking the proxy.

    Args:
        code:             Python source to execute.
        state:            The current RPG state dict (``before`` state).
                          The code may read/mutate it via the ``state`` variable.
        timeout_seconds:  Hard wall-clock limit on execution time.

    Returns:
        ``(updated_state, output)`` where ``output`` is stdout + any exception
        traceback produced during execution.
    """
    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue = ctx.Queue()

    proc = ctx.Process(
        target=_worker,
        args=(code, dict(state), result_queue),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=timeout_seconds)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2.0)   # Allow SIGTERM to propagate
        if proc.is_alive():
            proc.kill()          # SIGKILL as last resort
        logger.warning("Sandbox code timed out after %.1fs and was killed.", timeout_seconds)
        return state, f"[Sandbox timed out after {timeout_seconds}s — execution aborted]"

    if not result_queue.empty():
        updated_state, output = result_queue.get_nowait()
        return updated_state, output

    # Child exited without putting a result (crash / OOM)
    logger.error("Sandbox worker exited without producing a result (exit code %s).", proc.exitcode)
    return state, f"[Sandbox worker crashed unexpectedly (exit code {proc.exitcode})]"
