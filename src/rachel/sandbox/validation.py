"""Validation functions for state and hidden_state constraints."""

from typing import Any

def validate_state_constraints(
    data: Any,
    max_depth: int,
    max_width: int,
    max_str_len: int,
    path: str = "state",
    depth: int = 1
) -> None:
    """Recursively validates dictionary/list state structures against width, depth, and string length limits.
    
    Raises:
        ValueError: If any validation rule is violated.
    """
    if depth > max_depth:
        raise ValueError(
            f"State nesting depth limit exceeded at '{path}' (depth: {depth}, max allowed: {max_depth})."
        )

    if isinstance(data, dict):
        if len(data) > max_width:
            raise ValueError(
                f"State width limit exceeded at '{path}' ({len(data)} keys, max allowed: {max_width})."
            )
        for key, val in data.items():
            validate_state_constraints(
                val, max_depth, max_width, max_str_len, f"{path}.{key}", depth + 1
            )
    elif isinstance(data, list):
        if len(data) > max_width:
            raise ValueError(
                f"State width limit exceeded at '{path}' ({len(data)} elements, max allowed: {max_width})."
            )
        for idx, val in enumerate(data):
            validate_state_constraints(
                val, max_depth, max_width, max_str_len, f"{path}[{idx}]", depth + 1
            )
    elif isinstance(data, str):
        if len(data) > max_str_len:
            raise ValueError(
                f"String length limit exceeded at '{path}' ({len(data)} characters, max allowed: {max_str_len}). "
                "AVOID storing narrative logs, dialogue history, or story details in state/hidden_state. "
                "Use the 'append_summary' or 'update_plan' tools for text narratives."
            )
