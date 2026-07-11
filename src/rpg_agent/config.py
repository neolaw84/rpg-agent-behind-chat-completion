"""Configuration Manager for the RPG Agent Proxy."""

import os
import logging
from pathlib import Path
import yaml
from dotenv import load_dotenv
from rpg_agent.agent.reasoning_formats import REASONING_FORMATS

# Load environment variables from .env file if present
load_dotenv()

logger = logging.getLogger(__name__)

# Resolve the config file path dynamically
_cwd_config = Path("configs.yaml").resolve()
if _cwd_config.exists():
    _CONFIG_PATH = _cwd_config
else:
    _package_config = (Path(__file__).parent.parent.parent / "configs.yaml").resolve()
    if _package_config.exists():
        _CONFIG_PATH = _package_config
    else:
        _CONFIG_PATH = Path.cwd() / "configs.yaml"

# Base directory for relative config paths
_BASE_DIR = _CONFIG_PATH.parent if _CONFIG_PATH.exists() else Path.cwd()

def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            with _CONFIG_PATH.open(encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error("Failed to load configs.yaml at %s: %s", _CONFIG_PATH, e)
    return {}

_cfg = _load_config()
_state_cfg     = _cfg.get("state", {})
_sandbox_cfg   = _cfg.get("sandbox", {})
_langgraph_cfg = _cfg.get("langgraph", {})

NUM_STATES_TO_TRACK: int = int(_state_cfg.get("num_states_to_track", 8))
SANDBOX_TIMEOUT: float = float(_sandbox_cfg.get("timeout_seconds", 2.0))
MAX_ITERATIONS: int = int(_langgraph_cfg.get("max_iterations", 5))

# Resolve STATE_STORAGE_DIR
_storage_dir_str = _state_cfg.get("storage_dir", "data/states")
_p = Path(_storage_dir_str)
STATE_STORAGE_DIR = _p if _p.is_absolute() else (_BASE_DIR / _p).resolve()

# Resolve KEY_FILE
KEY_FILE: Path = (_BASE_DIR / "proxy.key").resolve()

_llm_cfg = _cfg.get("llm", {})

_env_base_url = os.environ.get("OPENROUTER_BASE_URL")
OPENROUTER_BASE_URL = _env_base_url if _env_base_url else _llm_cfg.get("base_url") or "https://openrouter.ai/api/v1/chat/completions"

_env_default_model = os.environ.get("DEFAULT_MODEL")
DEFAULT_MODEL = _env_default_model if _env_default_model else _llm_cfg.get("default_model") or "google/gemini-flash-1.5"

_env_include_reasoning = os.environ.get("RPG_AGENT_INCLUDE_REASONING")
if _env_include_reasoning is not None and _env_include_reasoning != "":
    INCLUDE_REASONING = _env_include_reasoning.lower() not in ("false", "0", "no")
else:
    val = _llm_cfg.get("include_reasoning")
    INCLUDE_REASONING = True if val is None else bool(val)

REASONING_FORMAT = _llm_cfg.get("reasoning_format") or "Open-Router"

if REASONING_FORMAT.lower() == "custom":
    REASONING_PAYLOAD = _llm_cfg.get("reasoning_payload") or {}
else:
    _match = None
    for k, v in REASONING_FORMATS.items():
        if k.lower() == REASONING_FORMAT.lower():
            _match = v
            break
    REASONING_PAYLOAD = _match if _match is not None else REASONING_FORMATS["Open-Router"]

