"""Multi-sheet, formatted XLSX export.

Sheets: Summary · Daily Usage · By Model · By Project · By API Key · Billed Costs
        · Model Rate Card
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


def build_workbook(payload: dict) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)

    meta = payload.get("meta", {})
    rng = f"{meta.get('start_date','?')} to {meta.get('end_date','?')}"
    src = ("LIVE - OpenAI Admin API" if meta.get("live") else
           "DEMO DATA - no Admin key configured, figures are synthetic")

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

    _sheet(wb, "By Project", [
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
