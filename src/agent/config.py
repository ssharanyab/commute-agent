"""
Gemini / ADK environment configuration.

Credentials are read from the environment only. Missing credentials must
force deterministic fallback — never pretend Gemini was called.
"""

import os
from typing import Optional


PLACEHOLDER_KEYS = {"", "your_key_here", "changeme"}

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
FALLBACK_NOTICE = "Gemini unavailable — deterministic fallback"


def _clean_env(name: str) -> str:
    return os.environ.get(name, "").strip()


def get_gemini_api_key() -> Optional[str]:
    for name in ("GOOGLE_GENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = _clean_env(name)
        if value and value not in PLACEHOLDER_KEYS:
            return value
    return None


def use_vertex_auth() -> bool:
    flag = _clean_env("GOOGLE_GENAI_USE_VERTEXAI").lower()
    if flag not in {"1", "true", "yes"}:
        return False
    return bool(_clean_env("GOOGLE_CLOUD_PROJECT"))


def gemini_credentials_available() -> bool:
    """True only when a real API key or Vertex project is configured."""
    return get_gemini_api_key() is not None or use_vertex_auth()


def get_gemini_model() -> str:
    return _clean_env("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL


def adk_importable() -> bool:
    try:
        import google.adk.agents  # noqa: F401
        return True
    except Exception:
        return False
