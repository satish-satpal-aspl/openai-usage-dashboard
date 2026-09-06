"""Reshape raw Admin-API buckets into the series/tables the dashboard renders."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from .pricing import estimate_cost

TOKEN_FIELDS = ("input_tokens", "output_tokens", "input_cached_tokens",
                "input_audio_tokens", "output_audio_tokens")


def _iso(ts: int, bucket_width: str) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d") if bucket_width == "1d" else dt.strftime("%Y-%m-%d %H:%M")


def _blank() -> dict:
    return {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,
            "audio_input_tokens": 0, "audio_output_tokens": 0, "est_cost": 0.0}


def _add(acc: dict, r: dict, price_models: dict) -> None:
    inp = int(r.get("input_tokens") or 0)
    out = int(r.get("output_tokens") or 0)
    cached = int(r.get("input_cached_tokens") or 0)
    acc["requests"] += int(r.get("num_model_requests") or 0)
    acc["input_tokens"] += inp
    acc["output_tokens"] += out
    acc["cached_tokens"] += cached
    acc["audio_input_tokens"] += int(r.get("input_audio_tokens") or 0)
    acc["audio_output_tokens"] += int(r.get("output_audio_tokens") or 0)
    acc["est_cost"] += estimate_cost(price_models, r.get("model"), inp, out, cached)


def summarise(usage_by_kind: dict[str, list[dict]], price_models: dict) -> dict:
    total = _blank()
    per_kind: dict[str, dict] = {}
    for kind, buckets in usage_by_kind.items():
        k = _blank()
        for b in buckets:
            for r in b.get("results") or []:
                _add(k, r, price_models)
                _add(total, r, price_models)
        if k["requests"] or k["input_tokens"] or k["output_tokens"]:
            per_kind[kind] = k
    total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return {"total": total, "by_endpoint": per_kind}


def timeseries(usage_by_kind: dict[str, list[dict]], price_models: dict,
               bucket_width: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for buckets in usage_by_kind.values():
        for b in buckets:
            key = _iso(int(b.get("start_time") or 0), bucket_width)
            acc = rows.setdefault(key, {**_blank(), "bucket": key,
                                        "start_time": int(b.get("start_time") or 0)})
            for r in b.get("results") or []:
                _add(acc, r, price_models)
    return sorted(rows.values(), key=lambda r: r["start_time"])


def group(usage_by_kind: dict[str, list[dict]], price_models: dict, field: str) -> list[dict]:
    """Collapse every bucket by one grouping field (model / project_id / api_key_id / user_id)."""
    rows: dict[str, dict] = defaultdict(_blank)
    for buckets in usage_by_kind.values():
        for b in buckets:
            for r in b.get("results") or []:
                key = r.get(field) or "(ungrouped)"
                _add(rows[key], r, price_models)
    out = [{field: k, **v} for k, v in rows.items()]
    out.sort(key=lambda r: (r["input_tokens"] + r["output_tokens"]), reverse=True)
    return out


def costs_timeseries(cost_buckets: list[dict]) -> list[dict]:
    rows: dict[str, dict] = {}
    for b in cost_buckets:
        key = _iso(int(b.get("start_time") or 0), "1d")
        acc = rows.setdefault(key, {"bucket": key, "start_time": int(b.get("start_time") or 0),
                                    "cost": 0.0})
        for r in b.get("results") or []:
            acc["cost"] += float((r.get("amount") or {}).get("value") or 0.0)
    return sorted(rows.values(), key=lambda r: r["start_time"])


def costs_group(cost_buckets: list[dict], field: str) -> list[dict]:
    rows: dict[str, float] = defaultdict(float)
    for b in cost_buckets:
        for r in b.get("results") or []:
            rows[r.get(field) or "(ungrouped)"] += float((r.get("amount") or {}).get("value") or 0.0)
    out = [{field: k, "cost": v} for k, v in rows.items()]
    out.sort(key=lambda r: r["cost"], reverse=True)
    return out


def costs_total(cost_buckets: list[dict]) -> float:
    return sum(float((r.get("amount") or {}).get("value") or 0.0)
               for b in cost_buckets for r in (b.get("results") or []))


def attach_names(rows: list[dict], field: str, names: dict[str, str],
                 label: str = "name") -> list[dict]:
    for r in rows:
        r[label] = names.get(r.get(field) or "", r.get(field) or "(ungrouped)")
    return rows


def unit_economics(model_rows: Iterable[dict], price_models: dict) -> list[dict]:
    """Per-model rate card alongside observed usage - the 'what does this cost me' table."""
    from .pricing import lookup
    out = []
    for r in model_rows:
        model = r.get("model")
        p = lookup(price_models, model) or {}
        tokens = r["input_tokens"] + r["output_tokens"]
        out.append({
            **r,
            "total_tokens": tokens,
            "price_in_per_1m": (p.get("input") or 0) * 1_000_000,
            "price_out_per_1m": (p.get("output") or 0) * 1_000_000,
            "price_cached_per_1m": (p.get("cached_input") or 0) * 1_000_000,
            "priced": bool(p),
            "avg_cost_per_request": (r["est_cost"] / r["requests"]) if r["requests"] else 0.0,
            "cache_hit_rate": (r["cached_tokens"] / r["input_tokens"]) if r["input_tokens"] else 0.0,
        })
    return out
