"""System Prompt Templates for the RPG Proxy Agent."""

def get_system_instruction(
    state_str: str,
    sandbox_timeout: float,
    max_iterations: int,
    current_iteration: int,
    rem_iterations: int,
) -> str:
    """Return the dynamic system instruction for the LLM node."""
    return (
        "[Proxy System Instruction]\n"
        f"- Current RPG Game State:\n```json\n{state_str}\n```\n"
        f"- You have access to a Python code execution sandbox (`execute_code_sandbox`) and dice rolling tools (`roll_xdy`).\n"
        f"- Python sandbox execution has a hard timeout of {sandbox_timeout} seconds.\n"
        f"- You have a strict budget of up to {max_iterations} tool-calling iterations.\n"
        f"- Current Iteration: {current_iteration} of {max_iterations}.\n"
        f"- Remaining Tool-Calling Budget: {rem_iterations}.\n"
        f"- If you reach iteration {max_iterations}, no further tool calls will be executed. "
        "You must formulate your final response based on the state at that point."
    )
