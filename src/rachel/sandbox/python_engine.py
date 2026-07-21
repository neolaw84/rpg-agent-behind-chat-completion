import io
import logging
import multiprocessing
import traceback
from typing import Any
from contextlib import redirect_stdout
from rachel.sandbox.base import SandboxEngine

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
    "None": None,
    "True": True,
    "False": False,
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
    "isinstance": isinstance,
    "issubclass": issubclass,
    "type": type,
    "repr": repr,
    "print": print,
    "Exception": Exception,
    "ValueError": ValueError,
    "TypeError": TypeError,
    "KeyError": KeyError,
    "IndexError": IndexError,
    "AttributeError": AttributeError,
    "StopIteration": StopIteration,
    "__import__": _safe_import,
}

def _sandbox_roll_xdy(num_dice: int, num_sides: int, interpretation: dict[int | str, str]) -> dict[str, Any]:
    from rachel.agent.tools import get_dice_interpretation
    rolls = [random.randint(1, num_sides) for _ in range(num_dice)]
    total = sum(rolls)
    interp = get_dice_interpretation(total, interpretation)
    interp_str = f"interpretation of the dice roll is '{interp}'"
    print(f"Rolled {num_dice}d{num_sides}: {rolls} = {total}\n{interp_str}")
    return {
        "rolls": rolls,
        "total": total,
        "interpretation": interp_str,
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
    "roll_xdy": _sandbox_roll_xdy,
}

def _python_worker(
    code: str,
    state: dict[str, Any],
    result_queue: multiprocessing.Queue,
) -> None:
    stdout_buf = io.StringIO()
    is_wrapper = isinstance(state, dict) and "state" in state and "hidden_state" in state
    if is_wrapper:
        local_ns: dict[str, Any] = {
            "state": state.get("state", {}),
            "hidden_state": state.get("hidden_state", {}),
        }
    else:
        local_ns = {"state": state}

    try:
        with redirect_stdout(stdout_buf):
            exec(code, dict(_SAFE_GLOBALS), local_ns)  # noqa: S102
    except Exception:  # noqa: BLE001
        stdout_buf.write("\n--- Sandbox Exception ---\n")
        stdout_buf.write(traceback.format_exc())

    if is_wrapper:
        updated_state = local_ns.get("state", {})
        updated_hidden = local_ns.get("hidden_state", {})
        if not isinstance(updated_state, dict):
            stdout_buf.write(
                "\n--- Sandbox Warning: 'state' was replaced with a non-dict; "
                "reverting to original state. ---\n"
            )
            updated_state = state.get("state", {})
        if not isinstance(updated_hidden, dict):
            stdout_buf.write(
                "\n--- Sandbox Warning: 'hidden_state' was replaced with a non-dict; "
                "reverting to original hidden_state. ---\n"
            )
            updated_hidden = state.get("hidden_state", {})
        
        result_queue.put(({
            "state": updated_state,
            "hidden_state": updated_hidden
        }, stdout_buf.getvalue()))
    else:
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
