"""Billing history and balance tracking.

OpenAI does not expose credit balance or invoices to API keys - /v1/dashboard/billing/*
is session-authenticated (browser only) and returns 403 even for an Admin key, and
there is no /v1/organization/billing/* equivalent. Verified against the live org.

So:
  * Billing HISTORY is derived from GET /v1/organization/costs, which is the same
    spend OpenAI bills - grouped into calendar months and projects.
  * BALANCE is user-declared: you record what the account had and when, and this
    module subtracts actual billed spend since that moment to track the remainder,
    the burn rate and the projected depletion date.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BALANCE_FILE = Path(__file__).resolve().parent.parent / "balance.json"


# ── declared balance ──────────────────────────────────────────────────────────
def load_balance() -> dict | None:
    if not BALANCE_FILE.exists():
        return None
    try:
        return json.loads(BALANCE_FILE.read_text())
    except Exception:
        return None


def save_balance(amount: float, as_of: str, note: str = "") -> dict:
    """as_of is the date the amount was accurate (YYYY-MM-DD)."""
    datetime.strptime(as_of, "%Y-%m-%d")            # validate or raise
    rec = {
        "amount": round(float(amount), 4),
        "as_of": as_of,
        "note": note[:200],
        "currency": "usd",
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    BALANCE_FILE.write_text(json.dumps(rec, indent=2))
    return rec


def clear_balance() -> None:
    BALANCE_FILE.unlink(missing_ok=True)


# ── aggregation over cost buckets ─────────────────────────────────────────────
def _bucket_day(b: dict) -> date:
    return datetime.fromtimestamp(int(b.get("start_time") or 0), tz=timezone.utc).date()


def _bucket_total(b: dict) -> float:
    return sum(float((r.get("amount") or {}).get("value") or 0.0)
               for r in (b.get("results") or []))


def monthly_history(cost_buckets: list[dict]) -> list[dict]:
    """Calendar-month totals, newest first, with month-over-month change."""
    months: dict[str, dict] = {}
    for b in cost_buckets:
        d = _bucket_day(b)
        key = f"{d.year:04d}-{d.month:02d}"
        m = months.setdefault(key, {"month": key, "cost": 0.0, "days": 0,
                                    "first_day": d.isoformat(), "last_day": d.isoformat()})
        total = _bucket_total(b)
        m["cost"] += total
        if total > 0:
            m["days"] += 1
        m["first_day"] = min(m["first_day"], d.isoformat())
        m["last_day"] = max(m["last_day"], d.isoformat())

    rows = sorted(months.values(), key=lambda r: r["month"])
    # trim leading months with no spend - an account that started in June shouldn't
    # show nine empty rows before it
    first = next((i for i, r in enumerate(rows) if r["cost"] > 0), len(rows))
    rows = rows[first:]
    for i, r in enumerate(rows):
        prev = rows[i - 1]["cost"] if i else None
        r["prev_cost"] = prev
        r["change_pct"] = ((r["cost"] - prev) / prev) if prev else None
        r["avg_per_day"] = (r["cost"] / r["days"]) if r["days"] else 0.0
    rows.reverse()                                   # newest first for display
    return rows


def monthly_by_project(cost_buckets: list[dict], names: dict[str, str]) -> list[dict]:
    grid: dict[tuple[str, str], float] = defaultdict(float)
    projects: set[str] = set()
    months: set[str] = set()
    for b in cost_buckets:
        d = _bucket_day(b)
        key = f"{d.year:04d}-{d.month:02d}"
        months.add(key)
        for r in (b.get("results") or []):
            pid = r.get("project_id") or "(unattributed)"
            projects.add(pid)
            grid[(pid, key)] += float((r.get("amount") or {}).get("value") or 0.0)

    ordered = sorted(months, reverse=True)
    rows = []
    for pid in projects:
        cells = {m: round(grid.get((pid, m), 0.0), 4) for m in ordered}
        rows.append({"project_id": pid, "name": names.get(pid, pid),
                     "total": round(sum(cells.values()), 4), **{f"m_{m}": v for m, v in cells.items()}})
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {"months": ordered, "rows": rows}


def spend_since(cost_buckets: list[dict], since: str) -> float:
    cut = datetime.strptime(since, "%Y-%m-%d").date()
    return sum(_bucket_total(b) for b in cost_buckets if _bucket_day(b) >= cut)


def balance_status(balance: dict | None, cost_buckets: list[dict]) -> dict | None:
    """Declared balance minus billed spend since it was recorded, plus runway."""
    if not balance:
        return None

    as_of = datetime.strptime(balance["as_of"], "%Y-%m-%d").date()
    today = datetime.now(timezone.utc).date()
    spent = spend_since(cost_buckets, balance["as_of"])
    remaining = balance["amount"] - spent

    elapsed = max(1, (today - as_of).days + 1)
    burn = spent / elapsed

    # Average burn understates risk when spend is accelerating, so also measure the
    # trailing 30 days and base the headline runway on whichever is higher.
    win_start = max(as_of, today - timedelta(days=29))
    win_days = max(1, (today - win_start).days + 1)
    burn_recent = spend_since(cost_buckets, win_start.isoformat()) / win_days

    basis = max(burn, burn_recent)
    runway_days = (remaining / basis) if basis > 0 else None

    return {
        "amount": balance["amount"],
        "as_of": balance["as_of"],
        "note": balance.get("note", ""),
        "updated_at": balance.get("updated_at"),
        "spent_since": round(spent, 4),
        "remaining": round(remaining, 4),
        "used_pct": (spent / balance["amount"]) if balance["amount"] else None,
        "days_elapsed": elapsed,
        "burn_per_day": round(burn, 4),
        "burn_recent_per_day": round(burn_recent, 4),
        "burn_recent_days": win_days,
        "burn_basis": "recent" if burn_recent >= burn else "average",
        "runway_days": round(runway_days, 1) if runway_days is not None else None,
        "depleted_on": ((today + timedelta(days=int(runway_days))).isoformat()
                        if runway_days is not None and runway_days < 3650 else None),
        # the window the spend figure was computed over - the caller may have
        # fetched less history than as_of, which would understate spend
        "covers_full_period": bool(cost_buckets) and _bucket_day(min(
            cost_buckets, key=lambda b: int(b.get("start_time") or 0))) <= as_of,
    }
