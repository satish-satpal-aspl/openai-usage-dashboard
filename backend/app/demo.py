"""Synthetic buckets shaped exactly like the Admin API's, so the dashboard is
fully explorable before an Admin key exists. Deterministic - same range, same data.

Everything served from here is flagged `live: false` and the UI shows a demo banner.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

PROJECTS = [
    ("proj_hnb_ocr_prod", "HNB Life OCR - Production"),
    ("proj_hnb_ocr_stg", "HNB Life OCR - Staging"),
    ("proj_hnb_sig", "Signature & Photo Verification"),
    ("proj_internal", "Internal Tooling"),
]
API_KEYS = [
    ("key_prod_1", "prod-key-1", "proj_hnb_ocr_prod"),
    ("key_prod_2", "prod-key-2", "proj_hnb_ocr_prod"),
    ("key_prod_3", "prod-key-3", "proj_hnb_ocr_prod"),
    ("key_stg_1", "staging-key", "proj_hnb_ocr_stg"),
    ("key_sig_1", "signature-key", "proj_hnb_sig"),
    ("key_int_1", "internal-key", "proj_internal"),
]
MODELS = ["gpt-4o", "gpt-4o-mini", "text-embedding-3-small"]

# Relative traffic weights: project -> model -> share
MIX = {
    "proj_hnb_ocr_prod": {"gpt-4o": 0.62, "gpt-4o-mini": 0.10, "text-embedding-3-small": 0.04},
    "proj_hnb_ocr_stg":  {"gpt-4o": 0.06, "gpt-4o-mini": 0.03},
    "proj_hnb_sig":      {"gpt-4o": 0.11, "gpt-4o-mini": 0.02},
    "proj_internal":     {"gpt-4o-mini": 0.02},
}


def _rand(*parts: object) -> float:
    """Deterministic pseudo-random in [0,1) from a stable hash of the inputs."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _day_weight(d: datetime) -> float:
    """Weekday-heavy traffic with a mild upward trend and daily jitter."""
    weekday = 0.35 if d.weekday() >= 5 else 1.0
    trend = 1.0 + 0.012 * (d.timetuple().tm_yday % 60)
    return weekday * trend * (0.82 + 0.36 * _rand(d.date(), "w"))


def usage_buckets(start: int, end: int, bucket_width: str = "1d") -> list[dict]:
    step = {"1d": 86400, "1h": 3600, "1m": 60}.get(bucket_width, 86400)
    out: list[dict] = []
    t = start - (start % step)
    while t < end:
        d = datetime.fromtimestamp(t, tz=timezone.utc)
        w = _day_weight(d) * (1.0 if step == 86400 else step / 86400.0)
        results = []
        for pid, _ in PROJECTS:
            for model, share in MIX[pid].items():
                calls = int(1400 * w * share * (0.8 + 0.4 * _rand(t, pid, model)))
                if calls <= 0:
                    continue
                kid = next((k for k, _, p in API_KEYS if p == pid), "key_unknown")
                keys = [k for k, _, p in API_KEYS if p == pid]
                kid = keys[int(_rand(t, pid, model, "k") * len(keys))] if keys else kid
                if model.startswith("text-embedding"):
                    inp, outp, cached = calls * 480, 0, 0
                else:
                    inp = int(calls * (1850 + 500 * _rand(t, model, "i")))
                    outp = int(calls * (140 + 90 * _rand(t, model, "o")))
                    cached = int(inp * 0.22 * _rand(t, model, "c"))
                results.append({
                    "object": "organization.usage.completions.result",
                    "input_tokens": inp, "output_tokens": outp,
                    "input_cached_tokens": cached,
                    "input_audio_tokens": 0, "output_audio_tokens": 0,
                    "num_model_requests": calls,
                    "project_id": pid, "api_key_id": kid, "user_id": None,
                    "model": model, "batch": False,
                })
        out.append({"object": "bucket", "start_time": t, "end_time": t + step,
                    "results": results})
        t += step
    return out


def cost_buckets(start: int, end: int) -> list[dict]:
    """Billed costs derived from the same traffic, plus a small always-on line item."""
    from .pricing import FALLBACK
    out: list[dict] = []
    for b in usage_buckets(start, end, "1d"):
        per_project: dict[str, float] = {}
        for r in b["results"]:
            p = FALLBACK.get(r["model"], {"input": 1e-7, "output": 4e-7, "cached_input": 5e-8})
            billable = r["input_tokens"] - r["input_cached_tokens"]
            amt = (billable * p["input"] + r["input_cached_tokens"] * p.get("cached_input", p["input"])
                   + r["output_tokens"] * p["output"])
            per_project[r["project_id"]] = per_project.get(r["project_id"], 0.0) + amt
        results = [{"object": "organization.costs.result",
                    "amount": {"value": round(v, 6), "currency": "usd"},
                    "line_item": "gpt-4o, input", "project_id": pid,
                    "organization_id": "org-demo"}
                   for pid, v in per_project.items()]
        results.append({"object": "organization.costs.result",
                        "amount": {"value": 0.42, "currency": "usd"},
                        "line_item": "assistants api | file search",
                        "project_id": "proj_internal", "organization_id": "org-demo"})
        out.append({"object": "bucket", "start_time": b["start_time"],
                    "end_time": b["end_time"], "results": results})
    return out


def projects() -> list[dict]:
    return [{"id": pid, "name": name, "status": "active",
             "created_at": int((datetime.now(timezone.utc) - timedelta(days=400)).timestamp())}
            for pid, name in PROJECTS]


def api_keys(project_id: str) -> list[dict]:
    return [{"id": kid, "name": name, "created_at": 0, "redacted_value": f"sk-...{kid[-4:]}"}
            for kid, name, pid in API_KEYS if pid == project_id]
