"""Configuration, the multi-account registry, and admin-key detection."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

OPENAI_BASE = "https://api.openai.com/v1"
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
ALLOW_DEMO_MODE = os.getenv("ALLOW_DEMO_MODE", "true").lower() == "true"

ACCOUNTS_FILE = BASE_DIR / "accounts.json"
REPORT_CONFIG_FILE = BASE_DIR / "report_config.json"

# LiteLLM's community-maintained price sheet - the "real-time pricing" source.
PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
PRICING_TTL_SECONDS = 6 * 3600
PRICING_CACHE = BASE_DIR / "pricing_cache.json"

# Legacy single-key variable, still honoured as the first account.
LEGACY_KEY_ENV = "OPENAI_ADMIN_KEY"


@dataclass(frozen=True)
class Account:
    """One OpenAI organization we can read usage from."""
    id: str
    label: str
    key: str
    key_env: str
    org_id: str | None = None
    owner_email: str | None = None
    # How client attribution works for this org. Account 1 keeps one project per
    # client; the legacy org puts every client in a single project and separates
    # them by API key, which the Costs API cannot group by - so cost there is
    # apportioned from per-key token usage instead.
    attribute_by: str = "project"

    @property
    def kind(self) -> str:
        if not self.key:
            return "missing"
        if self.key.startswith("sk-admin-"):
            return "admin"
        if self.key.startswith("sk-proj-"):
            return "project"
        return "unknown"

    @property
    def usable(self) -> bool:
        return self.kind == "admin"

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "org_id": self.org_id,
                "owner_email": self.owner_email, "attribute_by": self.attribute_by,
                "key_env": self.key_env, "kind": self.kind, "usable": self.usable,
                "message": _kind_message(self.kind, self.key_env)}


def _kind_message(kind: str, env: str) -> str:
    return {
        "missing": f"{env} is not set.",
        "admin": "Admin key configured.",
        "project": (f"{env} holds a PROJECT key (sk-proj-). Organization usage and cost "
                    "endpoints need an Admin key (sk-admin-) created by an org Owner at "
                    "platform.openai.com/settings/organization/admin-keys."),
        "unknown": f"{env} does not look like an Admin key (expected sk-admin-...).",
    }[kind]


def _load_registry() -> list[dict]:
    if ACCOUNTS_FILE.exists():
        try:
            data = json.loads(ACCOUNTS_FILE.read_text())
            entries = [a for a in (data.get("accounts") or []) if isinstance(a, dict)]
            if entries:
                return entries
        except Exception:
            pass
    # No registry file: fall back to the original single-key behaviour.
    return [{"id": "default", "label": "OpenAI organization", "key_env": LEGACY_KEY_ENV}]


def load_accounts() -> list[Account]:
    out: list[Account] = []
    seen: set[str] = set()
    for entry in _load_registry():
        env = str(entry.get("key_env") or LEGACY_KEY_ENV)
        acc_id = str(entry.get("id") or env.lower())
        if acc_id in seen:
            continue
        seen.add(acc_id)
        out.append(Account(
            id=acc_id,
            label=str(entry.get("label") or acc_id),
            key=os.getenv(env, "").strip(),
            key_env=env,
            org_id=entry.get("org_id"),
            owner_email=entry.get("owner_email"),
            attribute_by=str(entry.get("attribute_by") or "project"),
        ))
    return out


ACCOUNTS: list[Account] = load_accounts()


def accounts() -> list[Account]:
    return ACCOUNTS


def account(acc_id: str) -> Account | None:
    return next((a for a in ACCOUNTS if a.id == acc_id), None)


def usable_accounts(ids: list[str] | None = None) -> list[Account]:
    """Accounts we can actually query, optionally narrowed to `ids`."""
    pool = [a for a in ACCOUNTS if a.usable]
    if ids:
        wanted = set(ids)
        pool = [a for a in pool if a.id in wanted]
    return pool


def live_mode(ids: list[str] | None = None) -> bool:
    return bool(usable_accounts(ids))


def key_status(ids: list[str] | None = None) -> dict:
    """Aggregate key health, plus a per-account breakdown. Never leaks a key."""
    pool = [a for a in ACCOUNTS if not ids or a.id in set(ids)]
    live = [a for a in pool if a.usable]
    if not pool:
        msg = "No accounts configured."
    elif not live:
        msg = "; ".join(_kind_message(a.kind, a.key_env) for a in pool) + " Serving demo data."
    elif len(live) == len(pool):
        msg = f"{len(live)} account(s) configured with Admin keys."
    else:
        bad = [a for a in pool if not a.usable]
        msg = (f"{len(live)} of {len(pool)} accounts usable. "
               + "; ".join(_kind_message(a.kind, a.key_env) for a in bad))
    return {
        "configured": bool(live),
        "kind": "admin" if live else (pool[0].kind if pool else None),
        "message": msg,
        "accounts": [a.public() for a in pool],
        "usable_count": len(live),
        "total_count": len(pool),
    }


def report_config() -> dict:
    if REPORT_CONFIG_FILE.exists():
        try:
            return json.loads(REPORT_CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}
