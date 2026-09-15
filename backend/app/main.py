"""OpenAI organization usage & cost dashboard - API layer.

The Admin key never leaves this process; the browser talks only to this service.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from . import aggregate as agg
from . import billing, demo, openai_admin as admin, report as rpt
from .auth import BasicAuthMiddleware, auth_enabled
from .config import (ALLOW_DEMO_MODE, CORS_ORIGINS, accounts, key_status,
                     live_mode, report_config, usable_accounts)
from .excel_export import build_workbook
from .pricing import get_pricing

# Clients poll for fresh usage; this keeps N browsers x M polls from turning into
# N*M upstream calls against the Admin API's rate limits.
CACHE_TTL = float(os.getenv("CACHE_TTL_SECONDS", "30"))
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_MAX = 64

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

app = FastAPI(title="OpenAI Usage Dashboard", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(BasicAuthMiddleware)


# ── helpers ───────────────────────────────────────────────────────────────────
def _range(start: str | None, end: str | None) -> tuple[int, int, str, str]:
    """ISO dates -> UTC unix bounds. end is inclusive of the whole day."""
    today = datetime.now(timezone.utc).date()
    try:
        e = datetime.strptime(end, "%Y-%m-%d").date() if end else today
        s = datetime.strptime(start, "%Y-%m-%d").date() if start else e - timedelta(days=29)
    except ValueError:
        raise HTTPException(400, "start/end must be YYYY-MM-DD")
    if s > e:
        raise HTTPException(400, "start must be on or before end")
    if (e - s).days > 365:
        raise HTTPException(400, "range capped at 366 days")
    s_ts = int(datetime.combine(s, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    e_ts = int(datetime.combine(e + timedelta(days=1), datetime.min.time(),
                                tzinfo=timezone.utc).timestamp())
    return s_ts, e_ts, s.isoformat(), e.isoformat()


async def _load(start: int, end: int, bucket: str, project_ids: list[str] | None,
                account_ids: list[str] | None = None):
    """Fetch usage + costs + projects across every selected account, plus pricing."""
    pricing = await get_pricing()
    accs = usable_accounts(account_ids)
    if accs:
        usage, costs, projects = await asyncio.gather(
            admin.fetch_all_usage_multi(accs, start, end, bucket,
                                        ["project_id", "api_key_id", "model"], project_ids),
            admin.fetch_costs_multi(accs, start, end, ["line_item", "project_id"], project_ids),
            admin.fetch_projects_multi(accs),
        )
        live = True
    else:
        if not ALLOW_DEMO_MODE:
            raise HTTPException(503, key_status()["message"])
        buckets = demo.usage_buckets(start, end, bucket)
        if project_ids:
            buckets = [{**b, "results": [r for r in b["results"]
                                         if r["project_id"] in project_ids]} for b in buckets]
        usage = {"completions": admin._tag(buckets, "demo")}
        costs = admin._tag(demo.cost_buckets(start, end), "demo")
        if project_ids:
            costs = [{**b, "results": [r for r in b["results"]
                                       if r.get("project_id") in project_ids]} for b in costs]
        projects = [{**p, "account_id": "demo", "account_label": "Demo"}
                    for p in demo.projects()]
        live = False
    return usage, costs, projects, pricing, live


async def _api_key_names(projects: list[dict],
                         account_ids: list[str] | None = None) -> dict[str, str]:
    """key_id -> label, across accounts. A project we can't read just yields no names."""
    accs = usable_accounts(account_ids)
    if accs:
        return await admin.fetch_api_key_names(accs, projects)
    names: dict[str, str] = {}
    for p in projects:
        for k in demo.api_keys(p["id"]):
            names[k["id"]] = k["name"]
    return names


async def _payload(start: str | None, end: str | None, bucket: str,
                   project_ids: list[str] | None,
                   account_ids: list[str] | None = None) -> dict:
    s_ts, e_ts, s_iso, e_iso = _range(start, end)
    usage, costs, projects, pricing, live = await _load(s_ts, e_ts, bucket,
                                                       project_ids, account_ids)
    pm = pricing["models"]

    proj_names = {p["id"]: p.get("name") or p["id"] for p in projects}
    acc_of_project = {p["id"]: p.get("account_id") for p in projects}
    key_names = await _api_key_names(projects, account_ids)
    selected = usable_accounts(account_ids) or list(accounts())
    acc_labels = {a.id: a.label for a in accounts()} | {"demo": "Demo"}

    by_model = agg.unit_economics(agg.group(usage, pm, "model"), pm)
    by_project = agg.attach_names(agg.group(usage, pm, "project_id"), "project_id", proj_names)
    by_api_key = agg.attach_names(agg.group(usage, pm, "api_key_id"), "api_key_id", key_names)

    by_account = agg.attach_names(agg.group(usage, pm, "account_id"),
                                  "account_id", acc_labels)
    # A selected account with no traffic still belongs in the table - an empty row
    # is information, a missing row looks like the account was never queried.
    present = {r["account_id"] for r in by_account}
    by_account += [{"account_id": a.id, "name": a.label, "requests": 0,
                    "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,
                    "audio_input_tokens": 0, "audio_output_tokens": 0, "est_cost": 0.0}
                   for a in selected if a.usable and a.id not in present]
    billed_by_account = {r["account_id"]: r["cost"] for r in agg.costs_group(costs, "account_id")}
    for r in by_account:
        r["billed_cost"] = billed_by_account.get(r["account_id"], 0.0)

    billed_by_project = {r["project_id"]: r["cost"] for r in agg.costs_group(costs, "project_id")}
    for r in by_project:
        r["billed_cost"] = billed_by_project.get(r["project_id"], 0.0)
        r["account_id"] = acc_of_project.get(r["project_id"], "")
        r["account_label"] = acc_labels.get(r["account_id"], "")
    for r in by_api_key:
        r["project_name"] = "-"

    summary_report = rpt.build(costs, usage, pm, selected, report_config(),
                               key_names, s_iso, e_iso)

    rate_card = sorted(
        ({"model": m,
          "price_in_per_1m": v["input"] * 1e6,
          "price_out_per_1m": v["output"] * 1e6,
          "price_cached_per_1m": (v.get("cached_input") or 0) * 1e6}
         for m, v in pm.items() if v.get("provider") == "openai"),
        key=lambda r: r["model"])

    return {
        "meta": {
            "start_date": s_iso, "end_date": e_iso, "bucket_width": bucket, "live": live,
            "pricing_source": pricing["source"],
            "accounts": [a.public() for a in accounts()],
            "selected_accounts": [a.id for a in selected],
            "pricing_fetched": datetime.fromtimestamp(pricing["fetched_at"],
                                                      tz=timezone.utc).isoformat(timespec="seconds"),
            "key_status": key_status(),
        },
        "summary": agg.summarise(usage, pm),
        "timeseries": agg.timeseries(usage, pm, bucket),
        "cost_timeseries": agg.costs_timeseries(costs),
        "billed_cost": agg.costs_total(costs),
        "by_model": by_model,
        "by_account": by_account,
        "by_project": by_project,
        "by_api_key": by_api_key,
        "cost_by_line_item": agg.costs_group(costs, "line_item"),
        "projects": [{"id": p["id"], "name": p.get("name") or p["id"],
                      "status": p.get("status"), "account_id": p.get("account_id"),
                      "account_label": p.get("account_label")} for p in projects],
        "rate_card": rate_card,
        "report": summary_report,
    }


async def _payload_cached(start: str | None, end: str | None, bucket: str,
                          project_ids: list[str] | None,
                          account_ids: list[str] | None = None,
                          refresh: bool = False) -> dict:
    key = (start, end, bucket, tuple(sorted(project_ids or ())),
           tuple(sorted(account_ids or ())))
    now = time.monotonic()

    if not refresh:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            payload = hit[1]
            payload["meta"]["cache_age_seconds"] = round(now - hit[0], 1)
            return payload

    payload = await _payload(start, end, bucket, project_ids, account_ids)
    payload["meta"]["cache_age_seconds"] = 0.0
    payload["meta"]["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if len(_CACHE) >= _CACHE_MAX:                      # evict oldest
        _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
    _CACHE[key] = (now, payload)
    return payload


# ── routes ────────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    pricing = await get_pricing()
    return {"ok": True, "live": live_mode(), "demo_allowed": ALLOW_DEMO_MODE,
            "cache_ttl_seconds": CACHE_TTL, "auth_enabled": auth_enabled(),
            "key_status": key_status(), "pricing_source": pricing["source"],
            "priced_models": len(pricing["models"])}


@app.get("/api/accounts")
async def accounts_route():
    """The configured organizations. Keys are never included."""
    return [a.public() for a in accounts()]


@app.get("/api/projects")
async def projects_route(account_ids: list[str] | None = Query(None)):
    accs = usable_accounts(account_ids)
    if accs:
        try:
            ps = await admin.fetch_projects_multi(accs)
        except admin.AdminAPIError as e:
            raise HTTPException(e.status, e.message)
    else:
        ps = [{**p, "account_id": "demo", "account_label": "Demo"} for p in demo.projects()]
    return [{"id": p["id"], "name": p.get("name") or p["id"], "status": p.get("status"),
             "account_id": p.get("account_id"), "account_label": p.get("account_label")}
            for p in ps]


@app.get("/api/pricing")
async def pricing_route(refresh: bool = False):
    p = await get_pricing(force=refresh)
    return {"source": p["source"], "fetched_at": p["fetched_at"],
            "models": {k: v for k, v in p["models"].items() if v.get("provider") == "openai"}}


@app.get("/api/dashboard")
async def dashboard(
    start: str | None = Query(None, description="YYYY-MM-DD"),
    end: str | None = Query(None, description="YYYY-MM-DD"),
    bucket_width: str = Query("1d", pattern="^(1m|1h|1d)$"),
    project_ids: list[str] | None = Query(None),
    account_ids: list[str] | None = Query(None),
    refresh: bool = Query(False, description="bypass the server-side cache"),
):
    try:
        return await _payload_cached(start, end, bucket_width, project_ids,
                                     account_ids, refresh)
    except admin.AdminAPIError as e:
        raise HTTPException(e.status, e.message)


@app.get("/api/report")
async def report_route(
    start: str | None = Query(None, description="YYYY-MM-DD"),
    end: str | None = Query(None, description="YYYY-MM-DD"),
    account_ids: list[str] | None = Query(None),
    refresh: bool = Query(False),
):
    """The credit/usage summary: top-ups, usage by client, balance, documents."""
    try:
        payload = await _payload_cached(start, end, "1d", None, account_ids, refresh)
    except admin.AdminAPIError as e:
        raise HTTPException(e.status, e.message)
    return payload["report"]


# ── billing ───────────────────────────────────────────────────────────────────
async def _cost_buckets(months: int) -> tuple[list[dict], list[dict]]:
    """Daily cost buckets covering the last `months` calendar months, + projects."""
    today = datetime.now(timezone.utc).date()
    start = (today.replace(day=1) - timedelta(days=31 * max(0, months - 1))).replace(day=1)
    s_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    e_ts = int(datetime.combine(today + timedelta(days=1), datetime.min.time(),
                                tzinfo=timezone.utc).timestamp())
    accs = usable_accounts()
    if accs:
        buckets = await admin.fetch_costs_multi(accs, s_ts, e_ts, ["project_id"])
        projects = await admin.fetch_projects_multi(accs)
    else:
        buckets = demo.cost_buckets(s_ts, e_ts)
        projects = demo.projects()
    return buckets, projects


@app.get("/api/billing")
async def billing_route(months: int = Query(12, ge=1, le=24)):
    """Billing history from the Costs API + declared-balance tracking.

    OpenAI exposes neither credit balance nor invoices to API keys
    (/v1/dashboard/billing/* is browser-session-only, 403 even for Admin keys),
    so `balance` reflects a figure you record here, drawn down by real billed spend.
    """
    try:
        buckets, projects = await _cost_buckets(months)
    except admin.AdminAPIError as e:
        raise HTTPException(e.status, e.message)

    names = {p["id"]: p.get("name") or p["id"] for p in projects}
    declared = billing.load_balance()
    grid = billing.monthly_by_project(buckets, names)
    return {
        "live": live_mode(),
        "months_requested": months,
        "history": billing.monthly_history(buckets),
        "by_project": grid["rows"],
        "project_months": grid["months"],
        "balance": billing.balance_status(declared, buckets),
        "balance_supported_by_api": False,
        "balance_note": ("OpenAI does not expose credit balance or invoices to API "
                         "keys - /v1/dashboard/billing/* requires a browser session "
                         "key. This figure is the amount you recorded, minus billed "
                         "spend since that date."),
    }


@app.put("/api/billing/balance")
async def set_balance(payload: dict = Body(...)):
    try:
        amount = float(payload["amount"])
        as_of = str(payload["as_of"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "expected {amount: number, as_of: 'YYYY-MM-DD', note?: string}")
    if amount < 0:
        raise HTTPException(400, "amount must be >= 0")
    try:
        return billing.save_balance(amount, as_of, str(payload.get("note", "")))
    except ValueError:
        raise HTTPException(400, "as_of must be YYYY-MM-DD")


@app.delete("/api/billing/balance")
async def delete_balance():
    billing.clear_balance()
    return {"ok": True}


@app.get("/api/export.xlsx")
async def export_xlsx(
    start: str | None = None, end: str | None = None,
    bucket_width: str = Query("1d", pattern="^(1m|1h|1d)$"),
    project_ids: list[str] | None = Query(None),
    account_ids: list[str] | None = Query(None),
):
    try:
        payload = await _payload_cached(start, end, bucket_width, project_ids, account_ids)
    except admin.AdminAPIError as e:
        raise HTTPException(e.status, e.message)
    blob = build_workbook(payload)
    m = payload["meta"]
    name = f"openai-usage_{m['start_date']}_to_{m['end_date']}.xlsx"
    return Response(
        blob,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ── static frontend (production) ─────────────────────────────────────────────
if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """Serve the React SPA - all non-API routes return index.html."""
        file = FRONTEND_DIR / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(FRONTEND_DIR / "index.html")
