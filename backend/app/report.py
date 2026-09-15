"""The 'API Credit Usage Summary' - credits topped up vs. usage, split by client.

Every dollar here is a *billed* amount from GET /v1/organization/costs, summed
across all configured accounts. The parts OpenAI cannot tell us - which client a
project belongs to, what was topped up and when, how many documents were
processed - come from report_config.json until the database is wired in.

Two attribution styles, because the two orgs are organised differently:
  * "project"  - one project per client. The Costs API groups by project_id, so
                 the split is exact.
  * "api_key"  - every client shares a single project (the legacy org). The Costs
                 API cannot group by API key, so that project's billed cost is
                 apportioned across keys by their token spend that day. Marked
                 `apportioned` in the output so nobody reads it as exact.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from .pricing import estimate_cost


# ── small helpers ─────────────────────────────────────────────────────────────
def _day(ts: int) -> date:
    return datetime.fromtimestamp(int(ts or 0), tz=timezone.utc).date()


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _amount(r: dict) -> float:
    return float((r.get("amount") or {}).get("value") or 0.0)


def _clean(mapping: dict) -> dict:
    """Drop the _comment keys people leave in the config."""
    return {k: v for k, v in mapping.items() if not k.startswith("_") and isinstance(v, str)}


# ── attribution ───────────────────────────────────────────────────────────────
def _key_spend_by_day(usage_by_kind: dict, price_models: dict) -> dict:
    """(account_id, date) -> {api_key_id: estimated $}. Drives apportioning."""
    out: dict[tuple[str, date], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for buckets in usage_by_kind.values():
        for b in buckets:
            d = _day(b.get("start_time"))
            for r in b.get("results") or []:
                est = estimate_cost(price_models, r.get("model"),
                                    int(r.get("input_tokens") or 0),
                                    int(r.get("output_tokens") or 0),
                                    int(r.get("input_cached_tokens") or 0))
                if est > 0:
                    out[(r.get("account_id") or "", d)][r.get("api_key_id") or "(none)"] += est
    return out


def attribute(cost_buckets: list[dict], usage_by_kind: dict, price_models: dict,
              accounts: list, cfg: dict, key_names: dict[str, str]) -> list[dict]:
    """Billed cost buckets -> flat rows of {date, account_id, client, amount, exact}."""
    mapping = {a: _clean(m) for a, m in (cfg.get("client_mapping") or {}).items()
               if isinstance(m, dict)}
    unmapped = cfg.get("unmapped_client") or "Unattributed"
    style = {a.id: a.attribute_by for a in accounts}
    key_spend = _key_spend_by_day(usage_by_kind, price_models)

    rows: list[dict] = []
    for b in cost_buckets:
        d = _day(b.get("start_time"))
        for r in b.get("results") or []:
            amt = _amount(r)
            if not amt:
                continue
            acc = r.get("account_id") or ""
            pid = r.get("project_id") or ""
            table = mapping.get(acc, {})

            if style.get(acc) != "api_key":
                rows.append({"date": d, "account_id": acc, "project_id": pid,
                             "client": table.get(pid) or unmapped,
                             "amount": amt, "exact": True})
                continue

            # Legacy org: split the day's billed cost across that day's API keys.
            shares = key_spend.get((acc, d)) or {}
            total = sum(shares.values())
            if total <= 0:
                rows.append({"date": d, "account_id": acc, "project_id": pid,
                             "client": unmapped, "amount": amt, "exact": False})
                continue
            for key_id, est in shares.items():
                rows.append({"date": d, "account_id": acc, "project_id": pid,
                             "client": table.get(key_names.get(key_id, key_id)) or unmapped,
                             "amount": amt * est / total, "exact": False})
    return rows


def apply_exclusions(rows: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """Hold disputed charges out of client usage, returning them separately.

    An exclusion names a day, account and project. `baseline_retained` is the
    normal spend for that day which stays billed to the client - only the excess
    is held out.
    """
    excluded: list[dict] = []
    kept = rows

    for ex in cfg.get("exclusions") or []:
        try:
            when = _d(str(ex.get("date")))
        except (TypeError, ValueError):
            continue
        acc, pid = ex.get("account_id"), ex.get("project_id")

        def hit(r: dict) -> bool:
            return (r["date"] == when
                    and (not acc or r["account_id"] == acc)
                    and (not pid or r["project_id"] == pid))

        matched = [r for r in kept if hit(r)]
        if not matched:
            continue
        gross = sum(r["amount"] for r in matched)
        retained = min(gross, max(0.0, float(ex.get("baseline_retained") or 0.0)))
        held = gross - retained

        kept = [r for r in kept if not hit(r)]
        if retained > 0:                      # keep the normal-day portion with the client
            share = retained / gross
            kept += [{**r, "amount": r["amount"] * share} for r in matched]

        excluded.append({
            "id": ex.get("id") or f"exclusion-{when}",
            "label": ex.get("label") or "Excluded charge",
            "date": when.isoformat(),
            "account_id": acc,
            "project_id": pid,
            "gross": round(gross, 4),
            "retained_as_normal": round(retained, 4),
            "amount": round(held, 4),
            "note": ex.get("note") or "",
        })
    return kept, excluded


# ── periods ───────────────────────────────────────────────────────────────────
def build_periods(start: date, end: date, top_ups: list[dict]) -> list[dict]:
    """Split the range at each top-up date, the way the manual sheet does."""
    cuts = sorted({_d(t["date"]) for t in top_ups
                   if start < _d(t["date"]) <= end})
    bounds = [start] + cuts
    periods = []
    for i, s in enumerate(bounds):
        nxt = bounds[i + 1] if i + 1 < len(bounds) else None
        e = (nxt - timedelta(days=1)) if nxt else end
        if e < s:
            continue
        # Label reads "31-Aug to 10-Sep" - the boundary date, as on the sheet.
        label_end = nxt or end
        periods.append({
            "key": f"{s.isoformat()}..{e.isoformat()}",
            "label": f"{s:%d-%b} to {label_end:%d-%b-%Y}",
            "short_label": f"{s:%d-%b} to {label_end:%d-%b}",
            "start": s.isoformat(),
            "end": e.isoformat(),
        })
    return periods


# ── documents ─────────────────────────────────────────────────────────────────
def _documents(cfg: dict, start: date, end: date) -> dict:
    docs = cfg.get("documents") or {}
    envs = {k: v for k, v in (docs.get("environments") or {}).items()
            if isinstance(v, dict)}
    months = sorted({m for v in envs.values() for m in v if not m.startswith("_")})
    in_range = [m for m in months
                if f"{start:%Y-%m}" <= m <= f"{end:%Y-%m}"]

    rows = [{"month": m, **{env: int(v.get(m, 0)) for env, v in envs.items()},
             "total": sum(int(v.get(m, 0)) for v in envs.values())}
            for m in months]
    period_totals = {env: sum(int(v.get(m, 0)) for m in in_range) for env, v in envs.items()}
    all_totals = {env: sum(int(c) for k, c in v.items() if not k.startswith("_"))
                  for env, v in envs.items()}
    return {
        "client": docs.get("client") or "",
        "source": docs.get("source") or "manually recorded",
        "environments": list(envs),
        "monthly": rows,
        "months_in_period": in_range,
        "period_totals": period_totals,
        "period_total": sum(period_totals.values()),
        "all_time_totals": all_totals,
        "all_time_total": sum(all_totals.values()),
    }


# ── the report ────────────────────────────────────────────────────────────────
def build(cost_buckets: list[dict], usage_by_kind: dict, price_models: dict,
          accounts: list, cfg: dict, key_names: dict[str, str],
          start_iso: str, end_iso: str) -> dict:
    start, end = _d(start_iso), _d(end_iso)

    rows = attribute(cost_buckets, usage_by_kind, price_models, accounts, cfg, key_names)
    rows, excluded = apply_exclusions(rows, cfg)

    top_ups = sorted((t for t in (cfg.get("top_ups") or [])
                      if start <= _d(t["date"]) <= end),
                     key=lambda t: t["date"])
    periods = build_periods(start, end, top_ups)

    # section 2/3: client x period
    grid: dict[tuple[str, str], float] = defaultdict(float)
    approx: set[str] = set()
    for r in rows:
        if not (start <= r["date"] <= end):
            continue
        p = next((p for p in periods
                  if _d(p["start"]) <= r["date"] <= _d(p["end"])), None)
        if not p:
            continue
        grid[(r["client"], p["key"])] += r["amount"]
        if not r["exact"]:
            approx.add(r["client"])

    clients = sorted({c for c, _ in grid}, key=lambda c: -sum(
        v for (cc, _), v in grid.items() if cc == c))
    grand = sum(grid.values())

    by_period = []
    for p in periods:
        lines = [{"client": c, "amount": round(grid.get((c, p["key"]), 0.0), 4),
                  "apportioned": c in approx}
                 for c in clients if grid.get((c, p["key"]))]
        by_period.append({**p, "lines": lines,
                          "total": round(sum(l["amount"] for l in lines), 4)})

    by_client = [{
        "client": c,
        "apportioned": c in approx,
        "periods": {p["key"]: round(grid.get((c, p["key"]), 0.0), 4) for p in periods},
        "total": round(sum(grid.get((c, p["key"]), 0.0) for p in periods), 4),
        "share": (sum(grid.get((c, p["key"]), 0.0) for p in periods) / grand) if grand else 0.0,
    } for c in clients]

    # section 1 / 4
    topped = sum(float(t.get("amount") or 0.0) for t in top_ups)
    by_account = defaultdict(float)
    for r in rows:
        if start <= r["date"] <= end:
            by_account[r["account_id"]] += r["amount"]

    labels = {a.id: a.label for a in accounts}
    excluded_total = sum(e["amount"] for e in excluded)

    # A balance only means something when the recorded top-ups actually cover the
    # usage being counted. Spend before the first recorded top-up makes the figure
    # a difference between unrelated numbers, so say so rather than print it bare.
    first_top_up = _d(top_ups[0]["date"]) if top_ups else None
    used_dates = [r["date"] for r in rows if start <= r["date"] <= end]
    first_usage = min(used_dates) if used_dates else None
    covered = bool(first_top_up) and (first_usage is None or first_usage >= first_top_up)
    balance_warning = ""
    if not top_ups:
        balance_warning = ("No top-ups recorded for this period in report_config.json, "
                           "so the balance below is not meaningful.")
    elif not covered:
        balance_warning = (f"Usage starts {first_usage:%d %b %Y} but the first recorded "
                           f"top-up is {first_top_up:%d %b %Y}. Earlier top-ups are not in "
                           "report_config.json, so the balance understates credit available.")

    return {
        "title": "API Credit Usage Summary",
        "period": {"start": start_iso, "end": end_iso,
                   "label": f"{start:%d %b %Y} to {end:%d %b %Y}"},
        "currency": cfg.get("currency") or "USD",
        "accounts": [{"id": a.id, "label": a.label, "attribute_by": a.attribute_by,
                      "usage": round(by_account.get(a.id, 0.0), 4)} for a in accounts],
        "top_ups": [{"date": t["date"], "description": t.get("description") or "Credit top-up",
                     "account_id": t.get("account_id"),
                     "account_label": labels.get(t.get("account_id"), ""),
                     "amount": float(t.get("amount") or 0.0)} for t in top_ups],
        "top_ups_total": round(topped, 4),
        "periods": periods,
        "usage_by_period": by_period,
        "usage_by_client": by_client,
        "usage_total": round(grand, 4),
        "balance": {
            "topped_up": round(topped, 4),
            "usage": round(grand, 4),
            "available": round(topped - grand, 4),
            "covers_period": covered,
            "warning": balance_warning,
        },
        "excluded": excluded,
        "excluded_total": round(excluded_total, 4),
        "billed_total_including_excluded": round(grand + excluded_total, 4),
        "documents": _documents(cfg, start, end),
        "notes": [n for n in (cfg.get("notes") or []) if isinstance(n, str)],
        "has_apportioned": bool(approx),
    }
