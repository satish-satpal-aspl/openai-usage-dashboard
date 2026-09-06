"""Configuration + admin-key detection."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

OPENAI_ADMIN_KEY = os.getenv("OPENAI_ADMIN_KEY", "").strip()
OPENAI_BASE = "https://api.openai.com/v1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
ALLOW_DEMO_MODE = os.getenv("ALLOW_DEMO_MODE", "true").lower() == "true"

# LiteLLM's community-maintained price sheet - the "real-time pricing" source.
PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
PRICING_TTL_SECONDS = 6 * 3600
PRICING_CACHE = BASE_DIR / "pricing_cache.json"


def key_status() -> dict:
    """Describe the configured key without ever leaking it."""
    if not OPENAI_ADMIN_KEY:
        return {"configured": False, "kind": None,
                "message": "No OPENAI_ADMIN_KEY set. Serving demo data."}
    if OPENAI_ADMIN_KEY.startswith("sk-admin-"):
        return {"configured": True, "kind": "admin", "message": "Admin key configured."}
    if OPENAI_ADMIN_KEY.startswith("sk-proj-"):
        return {"configured": True, "kind": "project",
                "message": ("This is a PROJECT key (sk-proj-). The organization usage and "
                            "cost endpoints require an Admin key (sk-admin-) created by an "
                            "org Owner at platform.openai.com/settings/organization/admin-keys.")}
    return {"configured": True, "kind": "unknown",
            "message": "Key does not look like an Admin key (expected sk-admin-...)."}


def live_mode() -> bool:
    return key_status().get("kind") == "admin"
