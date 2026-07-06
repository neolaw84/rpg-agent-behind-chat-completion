"""Configuration Manager for the RPG Agent Proxy."""

import os
import logging
from pathlib import Path
import yaml

logger = logging.getLogger(__name__)

# Resolve the config file path dynamically
_config_env = os.environ.get("RPG_AGENT_CONFIG_PATH")
if _config_env:
    _CONFIG_PATH = Path(_config_env).resolve()
else:
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
_env_state_dir = os.environ.get("RPG_AGENT_STATE_DIR")
if _env_state_dir:
    STATE_STORAGE_DIR: Path = Path(_env_state_dir).resolve()
else:
    _storage_dir_str = _state_cfg.get("storage_dir", "data/states")
    _p = Path(_storage_dir_str)
    STATE_STORAGE_DIR = _p if _p.is_absolute() else (_BASE_DIR / _p).resolve()

# Resolve KEY_FILE
_env_key_file = os.environ.get("RPG_AGENT_KEY_FILE")
if _env_key_file:
    KEY_FILE: Path = Path(_env_key_file).resolve()
else:
    KEY_FILE: Path = (_BASE_DIR / "proxy.key").resolve()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
