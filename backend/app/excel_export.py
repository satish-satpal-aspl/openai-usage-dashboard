"""Multi-sheet, formatted XLSX export.

Sheets: Usage Summary · Summary · Daily Usage · By Model · By Account · By Project
        · By API Key · Billed Costs · Model Rate Card
Every sheet gets frozen headers, an autofilter, tuned column widths and real
number formats, so the file is usable in Excel without cleanup.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=11)
TITLE_FONT = Font(bold=True, size=14)
MUTED_FONT = Font(color="6B7280", size=10)
THIN = Side(style="thin", color="D9DDE3")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

INT_FMT = "#,##0"
USD_FMT = '"$"#,##0.0000'
USD2_FMT = '"$"#,##0.00'
PCT_FMT = "0.0%"

SECTION_FONT = Font(bold=True, size=11, color="1F3A5F")
SECTION_FILL = PatternFill("solid", fgColor="EEF2F7")
TOTAL_FONT = Font(bold=True)
TOTAL_FILL = PatternFill("solid", fgColor="F3F4F6")
WARN_FONT = Font(color="B45309", size=10, italic=True)


def _sheet(wb: Workbook, title: str, columns: list[tuple[str, str, str]],
           rows: list[dict], note: str | None = None):
    """columns: (header, dict-key, number-format)."""
    ws = wb.create_sheet(title[:31])
    r0 = 1
    if note:
        ws.cell(row=1, column=1, value=note).font = MUTED_FONT
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(1, len(columns)))
        r0 = 2

    for c, (head, _, _) in enumerate(columns, start=1):
        cell = ws.cell(row=r0, column=c, value=head)
        cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for i, row in enumerate(rows, start=r0 + 1):
        for c, (_, key, fmt) in enumerate(columns, start=1):
            cell = ws.cell(row=i, column=c, value=row.get(key))
            cell.border = BORDER
            if fmt:
                cell.number_format = fmt
            if fmt in (INT_FMT, USD_FMT, USD2_FMT, PCT_FMT):
                cell.alignment = Alignment(horizontal="right")

    ws.freeze_panes = ws.cell(row=r0 + 1, column=1)
    if rows:
        ws.auto_filter.ref = (f"A{r0}:{get_column_letter(len(columns))}{r0 + len(rows)}")

    for c, (head, key, _) in enumerate(columns, start=1):
        longest = max([len(str(head))] + [len(str(r.get(key, ""))) for r in rows[:400]] or [10])
        ws.column_dimensions[get_column_letter(c)].width = min(42, max(12, longest + 4))
    return ws


# ── the credit/usage summary sheet ────────────────────────────────────────────
class _Cursor:
    """Row-at-a-time writer for the summary sheet's stacked sections."""

    def __init__(self, ws):
        self.ws = ws
        self.row = 1

    def blank(self, n: int = 1):
        self.row += n

    def title(self, text: str, font=TITLE_FONT):
        self.ws.cell(row=self.row, column=1, value=text).font = font
        self.row += 1

    def muted(self, text: str, font=MUTED_FONT):
        self.ws.cell(row=self.row, column=1, value=text).font = font
        self.row += 1

    def section(self, text: str, width: int = 5):
        for c in range(1, width + 1):
            cell = self.ws.cell(row=self.row, column=c)
            cell.fill = SECTION_FILL
            if c == 1:
                cell.value, cell.font = text, SECTION_FONT
        self.row += 1

    def header(self, labels: list[str]):
        for c, label in enumerate(labels, start=1):
            cell = self.ws.cell(row=self.row, column=c, value=label)
            cell.fill, cell.font, cell.border = HEADER_FILL, HEADER_FONT, BORDER
            cell.alignment = Alignment(horizontal="center", vertical="center",
                                       wrap_text=True)
        self.row += 1

    def line(self, values: list, fmts: list[str] | None = None,
             bold: bool = False, fill=None):
        for c, v in enumerate(values, start=1):
            cell = self.ws.cell(row=self.row, column=c, value=v)
            cell.border = BORDER
            fmt = (fmts or [""] * len(values))[c - 1] if fmts else ""
            if fmt:
                cell.number_format = fmt
                cell.alignment = Alignment(horizontal="right")
            if bold:
                cell.font = TOTAL_FONT
            if fill is not None:
                cell.fill = fill
        self.row += 1

    def total(self, values: list, fmts: list[str] | None = None):
        self.line(values, fmts, bold=True, fill=TOTAL_FILL)


def _usage_summary_sheet(wb: Workbook, rep: dict, meta: dict):
    """Section-by-section rebuild of the hand-maintained credit summary."""
    ws = wb.create_sheet("Usage Summary")
    cur = _Cursor(ws)
    cur_sym = "USD"
    periods = rep.get("periods", [])

    cur.title(rep.get("title", "API Credit Usage Summary"))
    cur.muted(f"Period: {rep.get('period', {}).get('label', '-')}")
    accounts = ", ".join(a["label"] for a in rep.get("accounts", []))
    cur.muted(f"Accounts: {accounts or '-'}")
    cur.muted(f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
              f"   ·   Usage figures are billed amounts from the OpenAI Costs API")
    cur.blank()

    # 1. Top-ups
    cur.section("1. Top-ups")
    cur.header(["Date", "Description", f"Amount ({cur_sym})", "Account"])
    for t in rep.get("top_ups", []):
        cur.line([datetime.strptime(t["date"], "%Y-%m-%d").strftime("%d-%b-%Y"),
                  t["description"], t["amount"], t.get("account_label", "")],
                 ["", "", USD2_FMT, ""])
    cur.total(["Total topped up", "", rep.get("top_ups_total", 0.0), ""],
              ["", "", USD2_FMT, ""])
    cur.blank()

    # 2. Usage by period and client
    cur.section("2. Usage by period and client")
    cur.header(["Period", "Client", f"Line item ({cur_sym})",
                f"Client total ({cur_sym})", f"Period total ({cur_sym})"])
    for p in rep.get("usage_by_period", []):
        lines = p.get("lines", [])
        if not lines:
            cur.line([p["label"], "(no usage)", None, None, 0.0],
                     ["", "", USD2_FMT, USD2_FMT, USD2_FMT])
            continue
        for i, l in enumerate(lines):
            label = p["label"] if i == 0 else ""
            name = l["client"] + (" *" if l.get("apportioned") else "")
            last = i == len(lines) - 1
            cur.line([label, name, l["amount"], l["amount"],
                      p["total"] if last else None],
                     ["", "", USD2_FMT, USD2_FMT, USD2_FMT])
    cur.total(["Total usage", "", None, rep.get("usage_total", 0.0),
               rep.get("usage_total", 0.0)], ["", "", "", USD2_FMT, USD2_FMT])
    cur.blank()

    # 3. Usage by client across periods
    cur.section("3. Usage by client (all periods)")
    cur.header(["Client"] + [p["short_label"] for p in periods]
               + [f"Total ({cur_sym})", "Share of usage"])
    fmts = [""] + [USD2_FMT] * len(periods) + [USD2_FMT, PCT_FMT]
    for c in rep.get("usage_by_client", []):
        cur.line([c["client"] + (" *" if c.get("apportioned") else "")]
                 + [c["periods"].get(p["key"], 0.0) for p in periods]
                 + [c["total"], c["share"]], fmts)
    cur.total(["Total"]
              + [next((p2["total"] for p2 in rep.get("usage_by_period", [])
                       if p2["key"] == p["key"]), 0.0) for p in periods]
              + [rep.get("usage_total", 0.0), 1.0], fmts)
    cur.blank()

    # 4. Balance
    bal = rep.get("balance", {})
    cur.section("4. Balance")
    cur.header(["Item", f"Amount ({cur_sym})"])
    cur.line(["Total topped up", bal.get("topped_up", 0.0)], ["", USD2_FMT])
    cur.line(["Less: total usage", -abs(bal.get("usage", 0.0))], ["", USD2_FMT])
    cur.total(["Balance available", bal.get("available", 0.0)], ["", USD2_FMT])
    if bal.get("warning"):
        cur.muted(bal["warning"], WARN_FONT)
    cur.muted("Balance = top-ups recorded in report_config.json less billed usage "
              "for this period. OpenAI does not expose credit balance to API keys.")
    cur.blank()

    # 5. Excluded / disputed charges
    excluded = rep.get("excluded", [])
    if excluded:
        cur.section("5. Excluded from client usage - disputed charges")
        cur.header(["Date", "Item", f"Gross ({cur_sym})",
                    f"Retained as normal ({cur_sym})", f"Excluded ({cur_sym})"])
        for e in excluded:
            cur.line([datetime.strptime(e["date"], "%Y-%m-%d").strftime("%d-%b-%Y"),
                      e["label"], e["gross"], e["retained_as_normal"], e["amount"]],
                     ["", "", USD2_FMT, USD2_FMT, USD2_FMT])
        cur.total(["Total excluded", "", None, None, rep.get("excluded_total", 0.0)],
                  ["", "", "", "", USD2_FMT])
        cur.line(["Org billed total (usage + excluded)", "", None, None,
                  rep.get("billed_total_including_excluded", 0.0)],
                 ["", "", "", "", USD2_FMT], bold=True)
        for e in excluded:
            if e.get("note"):
                cur.muted(e["note"], WARN_FONT)
        cur.blank()

    # 6. Documents processed
    docs = rep.get("documents", {})
    envs = docs.get("environments", [])
    if envs:
        n = len(excluded) and 6 or 5
        client = docs.get("client") or "Client"
        cur.section(f"{n}. {client} - documents processed")
        cur.header(["Environment", "In this period", "All time"])
        for env in envs:
            cur.line([env, docs.get("period_totals", {}).get(env, 0),
                      docs.get("all_time_totals", {}).get(env, 0)],
                     ["", INT_FMT, INT_FMT])
        cur.total(["Total", docs.get("period_total", 0), docs.get("all_time_total", 0)],
                  ["", INT_FMT, INT_FMT])
        months = ", ".join(docs.get("months_in_period", [])) or "-"
        cur.muted(f"Source: {docs.get('source', '-')}. "
                  f"'In this period' sums whole months overlapping the range ({months}), "
                  "so a partial month is counted in full. Pending database access.",
                  WARN_FONT)
        cur.blank()

        cur.section(f"{n + 1}. Documents processed by month")
        cur.header(["Month"] + envs + ["Total"])
        for row in docs.get("monthly", []):
            cur.line([row["month"]] + [row.get(e, 0) for e in envs] + [row["total"]],
                     [""] + [INT_FMT] * (len(envs) + 1))
        cur.total(["TOTAL"] + [docs.get("all_time_totals", {}).get(e, 0) for e in envs]
                  + [docs.get("all_time_total", 0)],
                  [""] + [INT_FMT] * (len(envs) + 1))
        cur.blank()

    # Notes
    cur.section("Notes")
    notes = list(rep.get("notes", []))
    if rep.get("has_apportioned"):
        notes.append("* Cost apportioned across API keys by token spend. That org keeps "
                     "every client in one project and the Costs API cannot group by API "
                     "key, so per-client figures there are proportional, not exact.")
    notes.append(f"Pricing reference: {meta.get('pricing_source', '-')}. "
                 "Usage dollars are billed amounts and do not depend on it.")
    for note in notes:
        cur.muted(note)

    widths = [28, 26, 18, 20, 20, 18]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"
    return ws


def build_workbook(payload: dict) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    meta = payload.get("meta", {})
    rng = f"{meta.get('start_date','?')} to {meta.get('end_date','?')}"
    src = ("LIVE - OpenAI Admin API" if meta.get("live") else
           "DEMO DATA - no Admin key configured, figures are synthetic")

    # ---- Usage Summary (the client-facing credit report) ----------------------
    if payload.get("report"):
        _usage_summary_sheet(wb, payload["report"], meta)

    # ---- Summary -------------------------------------------------------------
    ws = wb.create_sheet("Summary")
    ws["A1"] = "OpenAI Organization Usage Report"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Date range: {rng}   ·   Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}"
    ws["A2"].font = MUTED_FONT
    ws["A3"] = f"Source: {src}   ·   Pricing: {meta.get('pricing_source','-')}"
    ws["A3"].font = MUTED_FONT

    t = payload.get("summary", {}).get("total", {})
    kpis = [
        ("Total API calls", t.get("requests", 0), INT_FMT),
        ("Input tokens", t.get("input_tokens", 0), INT_FMT),
        ("Output tokens", t.get("output_tokens", 0), INT_FMT),
        ("Cached input tokens", t.get("cached_tokens", 0), INT_FMT),
        ("Total tokens", t.get("input_tokens", 0) + t.get("output_tokens", 0), INT_FMT),
        ("Billed cost (OpenAI Costs API)", payload.get("billed_cost", 0.0), USD2_FMT),
        ("Estimated cost (tokens x live rates)", t.get("est_cost", 0.0), USD2_FMT),
    ]
    for i, (label, value, fmt) in enumerate(kpis, start=5):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        c = ws.cell(row=i, column=2, value=value)
        c.number_format = fmt
        c.alignment = Alignment(horizontal="right")
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 22

    # ---- Detail sheets -------------------------------------------------------
    _sheet(wb, "Daily Usage", [
        ("Date", "bucket", ""), ("API calls", "requests", INT_FMT),
        ("Input tokens", "input_tokens", INT_FMT), ("Output tokens", "output_tokens", INT_FMT),
        ("Cached tokens", "cached_tokens", INT_FMT), ("Est. cost", "est_cost", USD_FMT),
    ], payload.get("timeseries", []))

    _sheet(wb, "By Model", [
        ("Model", "model", ""), ("API calls", "requests", INT_FMT),
        ("Input tokens", "input_tokens", INT_FMT), ("Output tokens", "output_tokens", INT_FMT),
        ("Cached tokens", "cached_tokens", INT_FMT), ("Total tokens", "total_tokens", INT_FMT),
        ("Cache hit rate", "cache_hit_rate", PCT_FMT),
        ("$/1M in", "price_in_per_1m", USD_FMT), ("$/1M out", "price_out_per_1m", USD_FMT),
        ("Avg $/call", "avg_cost_per_request", USD_FMT), ("Est. cost", "est_cost", USD_FMT),
    ], payload.get("by_model", []))

    _sheet(wb, "By Account", [
        ("Account", "name", ""), ("Account ID", "account_id", ""),
        ("API calls", "requests", INT_FMT), ("Input tokens", "input_tokens", INT_FMT),
        ("Output tokens", "output_tokens", INT_FMT), ("Cached tokens", "cached_tokens", INT_FMT),
        ("Est. cost", "est_cost", USD_FMT), ("Billed cost", "billed_cost", USD2_FMT),
    ], payload.get("by_account", []),
        note="One row per configured OpenAI organization.")

    _sheet(wb, "By Project", [
        ("Account", "account_label", ""),
        ("Project", "name", ""), ("Project ID", "project_id", ""),
        ("API calls", "requests", INT_FMT), ("Input tokens", "input_tokens", INT_FMT),
        ("Output tokens", "output_tokens", INT_FMT), ("Cached tokens", "cached_tokens", INT_FMT),
        ("Est. cost", "est_cost", USD_FMT), ("Billed cost", "billed_cost", USD2_FMT),
    ], payload.get("by_project", []))

    _sheet(wb, "By API Key", [
        ("API key", "name", ""), ("Key ID", "api_key_id", ""), ("Project", "project_name", ""),
        ("API calls", "requests", INT_FMT), ("Input tokens", "input_tokens", INT_FMT),
        ("Output tokens", "output_tokens", INT_FMT), ("Est. cost", "est_cost", USD_FMT),
    ], payload.get("by_api_key", []),
        note="Key IDs only - secret values are never returned by the API.")

    _sheet(wb, "Billed Costs", [
        ("Date", "bucket", ""), ("Billed cost", "cost", USD2_FMT),
    ], payload.get("cost_timeseries", []),
        note="Authoritative billed amounts from GET /v1/organization/costs.")

    _sheet(wb, "Cost by Line Item", [
        ("Line item", "line_item", ""), ("Billed cost", "cost", USD2_FMT),
    ], payload.get("cost_by_line_item", []))

    _sheet(wb, "Model Rate Card", [
        ("Model", "model", ""), ("$/1M input", "price_in_per_1m", USD_FMT),
        ("$/1M output", "price_out_per_1m", USD_FMT),
        ("$/1M cached input", "price_cached_per_1m", USD_FMT),
    ], payload.get("rate_card", []),
        note=f"Live rates from {meta.get('pricing_source','-')}, fetched {meta.get('pricing_fetched','-')}.")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
