from abc import ABC, abstractmethod
from typing import Any

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
