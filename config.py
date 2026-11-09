"""Run-mode switches. The same code runs locally and as a public web app; everything is set by env vars.

    T2C_SERVER_MODE=1        public deployment (auto-on on Streamlit Community Cloud and Hugging Face Spaces)
    APP_PASSWORD=...         optional: visitors must enter it before using the app
    MAX_BUILDS_PER_HOUR=12   per-visitor build limit (default 12 in server mode, unlimited locally)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


ON_STREAMLIT_CLOUD = os.path.abspath(__file__).replace("\\", "/").startswith("/mount/src/")
SERVER_MODE = _flag("T2C_SERVER_MODE") or bool(os.environ.get("SPACE_ID")) or ON_STREAMLIT_CLOUD
# Builds that may run at the same time. A heavy build peaks at ~0.6 GB, so 1 keeps small free hosts
# (e.g. ~1 GB on Streamlit Community Cloud) from running out of memory; others wait their turn.
MAX_PARALLEL_BUILDS = int(os.environ.get("MAX_PARALLEL_BUILDS") or (1 if SERVER_MODE else 4))
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
MAX_BUILDS_PER_HOUR = int(os.environ.get("MAX_BUILDS_PER_HOUR") or (12 if SERVER_MODE else 0))   # 0 = unlimited

# Environment variables the CAD sandbox subprocess may see. Everything else (API keys, tokens) is withheld.
SANDBOX_ENV_KEYS = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
                    "LANG", "LC_ALL", "LD_LIBRARY_PATH", "PYTHONIOENCODING")


def sandbox_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in SANDBOX_ENV_KEYS}
