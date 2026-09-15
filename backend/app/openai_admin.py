"""Thin async client for OpenAI's organization Admin API.

Endpoints used (all require an Admin key with api.usage.read / api.management.read):
  GET /v1/organization/usage/{completions,embeddings,images,audio_speech,audio_transcriptions}
  GET /v1/organization/costs
  GET /v1/organization/projects
  GET /v1/organization/projects/{id}/api_keys

Every usage endpoint returns time buckets and paginates through `next_page`.
"""
from __future__ import annotations

import asyncio
from typing import Any, Iterable

import httpx

from .config import OPENAI_BASE

# Bucket-width limits imposed by the API (max buckets per page).
BUCKET_LIMITS = {"1m": 1440, "1h": 168, "1d": 31}

USAGE_KINDS = [
    "completions",
    "embeddings",
    "images",
    "audio_speech",
    "audio_transcriptions",
]


class AdminAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"[{status}] {message}")


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}",
            "Content-Type": "application/json"}


def _flatten(params: dict[str, Any]) -> list[tuple[str, str]]:
    """httpx needs repeated keys for array params (project_ids[], group_by[])."""
    out: list[tuple[str, str]] = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            for item in v:
                if item is not None and item != "":
                    out.append((k, str(item)))
        elif isinstance(v, bool):
            out.append((k, "true" if v else "false"))
        else:
            out.append((k, str(v)))
    return out


async def _get(client: httpx.AsyncClient, key: str, path: str,
               params: dict[str, Any]) -> dict:
    for attempt in range(4):
        r = await client.get(f"{OPENAI_BASE}{path}", params=_flatten(params),
                             headers=_headers(key), timeout=60.0)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            await asyncio.sleep(1.5 * (2 ** attempt))
            continue
        try:
            err = r.json()
            msg = err.get("error", {}).get("message") if isinstance(err.get("error"), dict) \
                else str(err.get("error") or err)
        except Exception:
            msg = r.text[:300]
        raise AdminAPIError(r.status_code, msg or "request failed")
    raise AdminAPIError(500, "exhausted retries")


async def _paginate(client: httpx.AsyncClient, key: str, path: str,
                    params: dict[str, Any], max_pages: int = 40) -> list[dict]:
    """Walk `next_page` and return every bucket across all pages."""
    buckets: list[dict] = []
    page: str | None = None
    for _ in range(max_pages):
        body = await _get(client, key, path, {**params, "page": page})
        buckets.extend(body.get("data") or [])
        if not body.get("has_more"):
            break
        page = body.get("next_page")
        if not page:
            break
    return buckets


async def fetch_usage(key: str, kind: str, start: int, end: int, bucket_width: str = "1d",
                      group_by: Iterable[str] | None = None,
                      project_ids: Iterable[str] | None = None,
                      models: Iterable[str] | None = None) -> list[dict]:
    """One usage endpoint, fully paginated. Returns raw buckets."""
    params = {
        "start_time": start,
        "end_time": end,
        "bucket_width": bucket_width,
        "limit": BUCKET_LIMITS.get(bucket_width, 31),
        "group_by": list(group_by) if group_by else None,
        "project_ids": list(project_ids) if project_ids else None,
        "models": list(models) if models else None,
    }
    async with httpx.AsyncClient() as client:
        return await _paginate(client, key, f"/organization/usage/{kind}", params)


async def fetch_costs(key: str, start: int, end: int,
                      group_by: Iterable[str] | None = ("line_item", "project_id"),
                      project_ids: Iterable[str] | None = None) -> list[dict]:
    """Billed costs straight from OpenAI. bucket_width is 1d only."""
    params = {
        "start_time": start,
        "end_time": end,
        "bucket_width": "1d",
        "limit": 180,
        "group_by": list(group_by) if group_by else None,
        "project_ids": list(project_ids) if project_ids else None,
    }
    async with httpx.AsyncClient() as client:
        return await _paginate(client, key, "/organization/costs", params)


async def fetch_projects(key: str) -> list[dict]:
    out: list[dict] = []
    after: str | None = None
    async with httpx.AsyncClient() as client:
        for _ in range(20):
            body = await _get(client, key, "/organization/projects",
                              {"limit": 100, "after": after, "include_archived": True})
            data = body.get("data") or []
            out.extend(data)
            if not body.get("has_more") or not data:
                break
            after = data[-1].get("id")
    return out


async def fetch_project_api_keys(key: str, project_id: str) -> list[dict]:
    out: list[dict] = []
    after: str | None = None
    async with httpx.AsyncClient() as client:
        for _ in range(20):
            body = await _get(client, key, f"/organization/projects/{project_id}/api_keys",
                              {"limit": 100, "after": after})
            data = body.get("data") or []
            out.extend(data)
            if not body.get("has_more") or not data:
                break
            after = data[-1].get("id")
    return out


async def fetch_all_usage(key: str, start: int, end: int, bucket_width: str,
                          group_by: Iterable[str] | None,
                          project_ids: Iterable[str] | None) -> dict[str, list[dict]]:
    """All usage kinds concurrently. A kind the org never used may 404 - tolerate it."""
    async def one(kind: str):
        try:
            return kind, await fetch_usage(key, kind, start, end, bucket_width,
                                           group_by, project_ids)
        except AdminAPIError as e:
            if e.status in (404, 400):
                return kind, []
            raise

    results = await asyncio.gather(*(one(k) for k in USAGE_KINDS))
    return dict(results)


# ── multi-account fan-out ─────────────────────────────────────────────────────
def _tag(buckets: list[dict], account_id: str) -> list[dict]:
    """Stamp every result row with the account it came from.

    Buckets from different orgs are merged into one series downstream, so the
    rows have to carry their origin or attribution is lost.
    """
    for b in buckets:
        for r in b.get("results") or []:
            r["account_id"] = account_id
    return buckets


def merge_buckets(per_account: list[list[dict]]) -> list[dict]:
    """Merge same-timestamp buckets from several orgs into a single series."""
    merged: dict[tuple, dict] = {}
    for buckets in per_account:
        for b in buckets:
            key = (int(b.get("start_time") or 0), int(b.get("end_time") or 0))
            slot = merged.get(key)
            if slot is None:
                merged[key] = {**b, "results": list(b.get("results") or [])}
            else:
                slot["results"].extend(b.get("results") or [])
    return sorted(merged.values(), key=lambda b: int(b.get("start_time") or 0))


async def fetch_costs_multi(accounts: Iterable[Any], start: int, end: int,
                            group_by: Iterable[str] | None = ("line_item", "project_id"),
                            project_ids: Iterable[str] | None = None) -> list[dict]:
    accounts = list(accounts)
    group_by = list(group_by) if group_by else None
    results = await asyncio.gather(*(
        fetch_costs(a.key, start, end, group_by, project_ids) for a in accounts))
    return merge_buckets([_tag(b, a.id) for a, b in zip(accounts, results)])


async def fetch_all_usage_multi(accounts: Iterable[Any], start: int, end: int,
                                bucket_width: str, group_by: Iterable[str] | None,
                                project_ids: Iterable[str] | None) -> dict[str, list[dict]]:
    accounts = list(accounts)
    group_by = list(group_by) if group_by else None
    per_account = await asyncio.gather(*(
        fetch_all_usage(a.key, start, end, bucket_width, group_by, project_ids)
        for a in accounts))
    out: dict[str, list[dict]] = {}
    for kind in USAGE_KINDS:
        out[kind] = merge_buckets([_tag(d.get(kind) or [], a.id)
                                   for a, d in zip(accounts, per_account)])
    return out


async def fetch_projects_multi(accounts: Iterable[Any]) -> list[dict]:
    accounts = list(accounts)
    results = await asyncio.gather(*(fetch_projects(a.key) for a in accounts))
    out: list[dict] = []
    for a, projects in zip(accounts, results):
        for p in projects:
            out.append({**p, "account_id": a.id, "account_label": a.label})
    return out


async def fetch_api_key_names(accounts: Iterable[Any],
                              projects: list[dict]) -> dict[str, str]:
    """key_id -> label, across every account. A project we can't read yields nothing."""
    by_id = {a.id: a for a in accounts}

    async def one(p: dict):
        acc = by_id.get(p.get("account_id"))
        if not acc:
            return []
        try:
            return await fetch_project_api_keys(acc.key, p["id"])
        except AdminAPIError:
            return []

    names: dict[str, str] = {}
    for keys in await asyncio.gather(*(one(p) for p in projects)):
        for k in keys:
            names[k["id"]] = k.get("name") or k["id"]
    return names
