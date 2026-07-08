"""System Prompt Templates for the RPG Proxy Agent."""

def get_system_instruction(
    state_str: str,
    sandbox_timeout: float,
    max_iterations: int,
    current_iteration: int,
    rem_iterations: int,
    engine_name: str = "v8",
) -> str:
    """Return the dynamic system instruction for the LLM node."""
    if engine_name == "v8":
        sandbox_info = (
            "- You have access to a JavaScript code execution sandbox (`execute_code_sandbox`) and dice rolling tools (`roll_xdy`).\n"
            "- The JavaScript sandbox allows you to read/mutate the global `state` object. Standard console methods like `console.log` work.\n"
            "- Note: If the sandbox execution fails (due to syntax errors, exceptions, timeouts, or replacing `state` with a non-object), any changes are discarded and the original pre-execution state is fully restored.\n"
        )
    else:
        sandbox_info = (
            "- You have access to a Python code execution sandbox (`execute_code_sandbox`) and dice rolling tools (`roll_xdy`).\n"
            "- The Python sandbox allows you to read/mutate the `state` dict.\n"
            "- The Python sandbox has the following libraries available: math, random, json, time, datetime, collections, itertools, functools, re, string. "
            "Nothing outside of these libraries is available.\n"
            "- Note: If the sandbox execution fails (due to syntax errors, exceptions, timeouts, or replacing `state` with a non-dict), any changes are discarded and the original pre-execution state is fully restored.\n"
        )

    return (
        "[Agent System Instruction]\n"
        f"- Current Role-Play State:\n```json\n{state_str}\n```\n"
        "- If the Current Role-Play State is empty ({}), you are encouraged to use `execute_code_sandbox` "
        "to initialize a structured schema for the state based on the context and rules.\n"
        f"{sandbox_info}"
        f"- Sandbox execution has a hard timeout of {sandbox_timeout} seconds.\n"
        f"- You have a strict budget of up to {max_iterations} tool-calling iterations.\n"
        f"- Current Iteration: {current_iteration} of {max_iterations}.\n"
        f"- Remaining Tool-Calling Budget: {rem_iterations}.\n"
        f"- If you reach iteration {max_iterations}, no further tool calls will be executed. "
        "You must formulate your final response based on the state at that point."
    )
