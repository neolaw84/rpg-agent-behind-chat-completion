import logging
import multiprocessing
import traceback
import json
from typing import Any
from rpg_agent.sandbox.base import SandboxEngine

logger = logging.getLogger(__name__)

def _v8_worker(
    code: str,
    state: dict[str, Any],
    result_queue: multiprocessing.Queue,
) -> None:
    from py_mini_racer import MiniRacer

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

    is_wrapper = isinstance(state, dict) and "state" in state and "hidden_state" in state

    if is_wrapper:
        state_json = json.dumps(state.get("state", {}), ensure_ascii=False)
        hidden_json = json.dumps(state.get("hidden_state", {}), ensure_ascii=False)
        js_init += f"\nvar state = {state_json};\nvar hidden_state = {hidden_json};\n"
    else:
        state_json = json.dumps(state, ensure_ascii=False)
        js_init += f"\nvar state = {state_json};\n"

    # Wrap inside IIFE and catch execution exceptions
    if is_wrapper:
        js_run = f"""
        try {{
            (function() {{
                {code}
            }})();
        }} catch (e) {{
            _logs.push("--- Sandbox Exception ---");
            _logs.push(e.stack || e.toString());
        }}
        JSON.stringify({{state: state, hidden_state: hidden_state, logs: _logs}});
        """
    else:
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
        if is_wrapper:
            updated_state = res.get("state", {})
            updated_hidden = res.get("hidden_state", {})
            if not isinstance(updated_state, dict):
                logs = "\n".join(res.get("logs", [])) + (
                    "\n--- Sandbox Warning: 'state' was replaced with a non-object; "
                    "reverting to original state. ---\n"
                )
                updated_state = state.get("state", {})
            if not isinstance(updated_hidden, dict):
                logs = "\n".join(res.get("logs", [])) + (
                    "\n--- Sandbox Warning: 'hidden_state' was replaced with a non-object; "
                    "reverting to original hidden_state. ---\n"
                )
                updated_hidden = state.get("hidden_state", {})
            
            logs = "\n".join(res.get("logs", []))
            updated_wrapper = {
                "state": updated_state,
                "hidden_state": updated_hidden
            }
            result_queue.put((updated_wrapper, logs))
        else:
            updated_state = res.get("state", state)
            if not isinstance(updated_state, dict):
                logs = "\n".join(res.get("logs", [])) + (
                    "\n--- Sandbox Warning: 'state' was replaced with a non-object; "
                    "reverting to original state. ---\n"
                )
                updated_state = state
            else:
                logs = "\n".join(res.get("logs", []))
            result_queue.put((updated_state, logs))
    except Exception as exc:
        logs = f"--- Sandbox Exception ---\n{traceback.format_exc()}"
        result_queue.put((state, logs))

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
