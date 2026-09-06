"""Live model pricing, sourced from LiteLLM's model_prices_and_context_window.json.

OpenAI's /organization/costs endpoint already returns *billed* dollars. This module
exists for the other half of the picture: per-model, per-token unit economics
(what a model costs per 1M tokens, and what a given token mix *should* cost), which
the costs endpoint does not break out.

Cached on disk with a TTL so the dashboard keeps working offline.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import PRICING_CACHE, PRICING_TTL_SECONDS, PRICING_URL

# Last-resort floor so the dashboard never renders $0 for common models.
FALLBACK = {
    "gpt-4o":      {"input": 2.50e-6, "output": 1.00e-5, "cached_input": 1.25e-6},
    "gpt-4o-mini": {"input": 1.50e-7, "output": 6.00e-7, "cached_input": 7.50e-8},
}

_mem: dict[str, Any] = {"fetched_at": 0.0, "models": {}, "source": "none"}


def _normalise(raw: dict) -> dict[str, dict]:
    """Reduce LiteLLM's sheet to the fields we price with."""
    out: dict[str, dict] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        inp = spec.get("input_cost_per_token")
        outp = spec.get("output_cost_per_token")
        if inp is None and outp is None:
            continue
        out[name] = {
            "input": float(inp or 0.0),
            "output": float(outp or 0.0),
            "cached_input": float(spec.get("cache_read_input_token_cost") or 0.0),
            "provider": spec.get("litellm_provider"),
            "max_input_tokens": spec.get("max_input_tokens"),
            "mode": spec.get("mode"),
        }
    return out


async def get_pricing(force: bool = False) -> dict[str, Any]:
    """Return {models, fetched_at, source}. Network -> disk cache -> fallback."""
    now = time.time()
    if not force and _mem["models"] and now - _mem["fetched_at"] < PRICING_TTL_SECONDS:
        return dict(_mem)

    if not force and PRICING_CACHE.exists():
        try:
            disk = json.loads(PRICING_CACHE.read_text())
            if now - disk.get("fetched_at", 0) < PRICING_TTL_SECONDS and disk.get("models"):
                _mem.update(disk)
                return dict(_mem)
        except Exception:
            pass

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(PRICING_URL)
            r.raise_for_status()
            models = _normalise(r.json())
        _mem.update({"fetched_at": now, "models": models, "source": "litellm"})
        try:
            PRICING_CACHE.write_text(json.dumps(_mem))
        except Exception:
            pass
        return dict(_mem)
    except Exception:
        if PRICING_CACHE.exists():          # stale is better than nothing
            try:
                disk = json.loads(PRICING_CACHE.read_text())
                if disk.get("models"):
                    disk["source"] = "litellm (stale cache)"
                    _mem.update(disk)
                    return dict(_mem)
            except Exception:
                pass
        _mem.update({"fetched_at": now,
                     "models": {k: {**v, "provider": "openai"} for k, v in FALLBACK.items()},
                     "source": "builtin fallback"})
        return dict(_mem)


def lookup(models: dict[str, dict], model: str | None) -> dict | None:
    """Resolve a usage-API model string against the price sheet.

    Usage rows carry dated snapshots ("gpt-4o-2024-08-06") and ft- prefixes that
    the sheet may not list verbatim; fall back to progressively shorter forms.
    """
    if not model:
        return None
    if model in models:
        return models[model]
    if model.startswith("ft:"):
        base = model.split(":")[1] if len(model.split(":")) > 1 else ""
        if base in models:
            return models[base]
    parts = model.split("-")
    for cut in range(len(parts) - 1, 1, -1):
        cand = "-".join(parts[:cut])
        if cand in models:
            return models[cand]
    return None


def estimate_cost(models: dict[str, dict], model: str | None, input_tokens: int,
                  output_tokens: int, cached_tokens: int = 0) -> float:
    """Token mix -> dollars, using the live sheet. Cached tokens billed at the
    cached rate and removed from the full-price input count."""
    p = lookup(models, model)
    if not p:
        return 0.0
    billable_input = max(0, input_tokens - cached_tokens)
    cached_rate = p.get("cached_input") or p["input"]
    return (billable_input * p["input"]
            + cached_tokens * cached_rate
            + output_tokens * p["output"])
