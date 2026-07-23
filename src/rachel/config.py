"""Configuration Manager for the RACHEL Proxy."""

import os
import logging
from pathlib import Path
import yaml
from dotenv import load_dotenv
from rachel.agent.reasoning_formats import REASONING_FORMATS

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
_server_cfg       = _cfg.get("server", {})
_state_cfg         = _cfg.get("state", {})
_sandbox_cfg       = _cfg.get("sandbox", {})
_langgraph_cfg     = _cfg.get("langgraph", {})
_orchestration_cfg = _cfg.get("orchestration", {})

CONFIG_PUBLIC_URL: str | None = _server_cfg.get("public_url")
STORAGE_ENGINE: str = _state_cfg.get("engine", "file").lower()
NUM_STATES_TO_TRACK: int = int(_state_cfg.get("num_states_to_track", 32))
MAX_STRING_LENGTH: int = int(_state_cfg.get("max_string_length", 80))
MAX_DEPTH: int = int(_state_cfg.get("max_depth", 4))
MAX_WIDTH: int = int(_state_cfg.get("max_width", 32))
SANDBOX_TIMEOUT: float = float(_sandbox_cfg.get("timeout_seconds", 8.0))
MAX_ITERATIONS: int = int(_langgraph_cfg.get("max_iterations", 5))

# Orchestration Configuration
PLAN_OFFSET: int = int(_orchestration_cfg.get("plan_offset", 0))
PLAN_SUMMARY_GAP: int = int(_orchestration_cfg.get("plan_summary_gap", 1))
PLAN_CLEANUP_GAP: int = int(_orchestration_cfg.get("plan_cleanup_gap", 2))

_plan_cfg = _orchestration_cfg.get("plan", {})
PLAN_TRIGGER_TYPE: str = _plan_cfg.get("trigger_type", "periodic")
PLAN_INTERVAL_TURNS: int = int(_plan_cfg.get("interval_turns", 10))
PLAN_TRIGGER_PROBABILITY: float = float(_plan_cfg.get("trigger_probability", 0.10))
PLAN_BUNDLE_LLM: bool = bool(_plan_cfg.get("bundle_llm", True))
_plan_llm_cfg = _plan_cfg.get("llm", {})
PLAN_MODEL: str = _plan_llm_cfg.get("model", "google/gemini-3.5-flash")
PLAN_BASE_URL: str = _plan_llm_cfg.get("base_url") or "https://openrouter.ai/api/v1/chat/completions"
PLAN_INCLUDE_REASONING: bool = bool(_plan_llm_cfg.get("include_reasoning", True))
PLAN_TEMPERATURE: float = float(_plan_llm_cfg.get("temperature", 0.2))

_summary_cfg = _orchestration_cfg.get("summary", {})
SUMMARY_TRIGGER_TYPE: str = _summary_cfg.get("trigger_type", "periodic")
SUMMARY_INTERVAL_TURNS: int = int(_summary_cfg.get("interval_turns", 10))
SUMMARY_TRIGGER_PROBABILITY: float = float(_summary_cfg.get("trigger_probability", 0.10))
SUMMARY_BUNDLE_LLM: bool = bool(_summary_cfg.get("bundle_llm", True))
SUMMARY_TARGET_WORDS: int = int(_summary_cfg.get("summary_target_words", 200))
_summary_llm_cfg = _summary_cfg.get("llm", {})
SUMMARY_MODEL: str = _summary_llm_cfg.get("model", "google/gemini-3.5-flash")
SUMMARY_BASE_URL: str = _summary_llm_cfg.get("base_url") or "https://openrouter.ai/api/v1/chat/completions"
SUMMARY_INCLUDE_REASONING: bool = bool(_summary_llm_cfg.get("include_reasoning", True))
SUMMARY_TEMPERATURE: float = float(_summary_llm_cfg.get("temperature", 0.2))

_cleanup_cfg = _orchestration_cfg.get("cleanup", {})
CLEANUP_TRIGGER_TYPE: str = _cleanup_cfg.get("trigger_type", "periodic")
CLEANUP_INTERVAL_TURNS: int = int(_cleanup_cfg.get("interval_turns", 8))
CLEANUP_TRIGGER_PROBABILITY: float = float(_cleanup_cfg.get("trigger_probability", 0.10))
CLEANUP_BUNDLE_LLM: bool = bool(_cleanup_cfg.get("bundle_llm", True))
_cleanup_llm_cfg = _cleanup_cfg.get("llm", {})
CLEANUP_MODEL: str = _cleanup_llm_cfg.get("model", "google/gemini-3.5-flash")
CLEANUP_BASE_URL: str = _cleanup_llm_cfg.get("base_url") or "https://openrouter.ai/api/v1/chat/completions"
CLEANUP_INCLUDE_REASONING: bool = bool(_cleanup_llm_cfg.get("include_reasoning", True))
CLEANUP_TEMPERATURE: float = float(_cleanup_llm_cfg.get("temperature", 0.2))


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
DEFAULT_MODEL = _env_default_model if _env_default_model else _llm_cfg.get("default_model") or "google/gemini-3.5-flash"

_env_include_reasoning = os.environ.get("RACHEL_INCLUDE_REASONING")
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


# Multi-Tenant Mode Flag
_env_mt = os.environ.get("MULTI_TENANT_MODE")
if _env_mt is not None and _env_mt != "":
    MULTI_TENANT_MODE: bool = _env_mt.lower() in ("true", "1", "yes")
else:
    MULTI_TENANT_MODE: bool = bool(_cfg.get("multi_tenant_mode", False))

# PostgreSQL Connection Settings (sourced exclusively from environment)
DATABASE_URL = os.environ.get("DATABASE_URL")
PGDATABASE = os.environ.get("PGDATABASE")
PGHOST = os.environ.get("PGHOST")
PGPASSWORD = os.environ.get("PGPASSWORD")
PGPORT = os.environ.get("PGPORT")
PGUSER = os.environ.get("PGUSER")

# SQLite Default Path & Database URL Resolver
DEFAULT_SQLITE_PATH: Path = (_BASE_DIR / "data" / "rpg_agent.sqlite3").resolve()

def get_default_db_url() -> str:
    """Return configured or derived SQL database URL (PostgreSQL or SQLite fallback)."""
    if DATABASE_URL:
        return DATABASE_URL
    if any((PGHOST, PGUSER, PGDATABASE)):
        user = PGUSER or ""
        pwd = f":{PGPASSWORD}" if PGPASSWORD else ""
        host = PGHOST or "localhost"
        port = f":{PGPORT}" if PGPORT else ""
        dbname = f"/{PGDATABASE}" if PGDATABASE else ""
        auth = f"{user}{pwd}@" if user or pwd else ""
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


# Envelope Encryption Master Secret (derived from environment or config)
ENCRYPTION_MASTER_KEY: str = os.environ.get(
    "ENCRYPTION_MASTER_KEY",
    _cfg.get("encryption_master_key", "rachel-master-encryption-secret-default")
)

# OpenID Connect / SSO Settings for Cloud Mode
OIDC_ISSUER_URL: str | None = os.environ.get("OIDC_ISSUER_URL", _cfg.get("oidc", {}).get("issuer_url"))
OIDC_JWKS_URL: str | None = os.environ.get("OIDC_JWKS_URL", _cfg.get("oidc", {}).get("jwks_url"))



