"""Builders for small synthetic documents and records used by the pipeline tests (no API calls)."""

from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from pipeline.llm import CallRecord, ToolResult


def make_pdf(path: Path, pages: list[list[str]], font_size: int = 11) -> Path:
    """A text-layer PDF: one list of lines per page."""
    c = canvas.Canvas(str(path), pagesize=A4)
    _, h = A4
    for lines in pages:
        c.setFont("Helvetica", font_size)
        y = h - 72
        for line in lines:
            c.drawString(72, y, line)
            y -= font_size * 1.8
        c.showPage()
    c.save()
    return path


def make_scanned_pdf(path: Path, lines: list[str]) -> Path:
    """An image-only PDF (no text layer): the lines are drawn into a bitmap, as a scanner would."""
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 34)
    except OSError:
        font = ImageFont.load_default(size=34)
    y = 150
    for line in lines:
        draw.text((120, y), line, fill=0, font=font)
        y += 70
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    return path


def make_xlsx(path: Path, sheets: dict[str, list[list]]) -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


def raw_field(value, quote, page=1, doc="om.pdf", unit=None, **extra) -> dict:
    """A field as the model returns it."""
    return {"value": value, "unit": unit, "as_of": extra.pop("as_of", None),
            "source": {"doc": doc, "page": page}, "quote": quote, "null_reason": None, **extra}


def verified(value, quote="q", page=1, doc="om.pdf", **extra) -> dict:
    """A field record as the verifier outputs it when verified."""
    return {"value": value, "unit": None, "as_of": extra.pop("as_of", None), "quote": quote,
            "source": {"doc": doc, "page": page, "bbox": [[0.1, 0.1, 0.5, 0.12]], "match": "exact"},
            "status": "verified", "reason": None, **extra}


class StubClient:
    """ModelClient stub: returns canned tool inputs per stage and records the requests."""

    def __init__(self, responses: dict[str, dict | list[dict]]):
        self.responses = responses
        self.requests: list[dict] = []

    def call_tool(self, *, stage, model, system, content, tools, tool_name=None, max_tokens=0) -> ToolResult:
        self.requests.append({"stage": stage, "content": content, "tools": tools, "tool_name": tool_name})
        key = stage if stage in self.responses else stage.rstrip("_0123456789")
        data = self.responses[key]
        if isinstance(data, list):
            data = data.pop(0)
        name = tool_name or tools[0]["name"]
        rec = CallRecord(stage=stage, model=model, input_tokens=10, output_tokens=5,
                         cache_creation_input_tokens=0, cache_read_input_tokens=0, cost_usd=0.0,
                         duration_s=0.0, stop_reason="tool_use", tool=name)
        return ToolResult(tool=name, data=data, call=rec)


# ---------------------------------------------------------------------------- synthetic deal for rule tests

JVC_REF_1BR = 105.0   # areas.yaml JVC market_rent_aed_psf_1br at the time of writing; tests read it from the file


def rr_unit(unit, unit_type="1br", area=750.0, rent=75_000.0, status="occupied", lease_end="2027-06-30",
            ejari="E1", asking=None, row=5) -> dict:
    return {"unit": unit, "unit_type": unit_type, "unit_type_text": unit_type, "floor": None, "area_sqft": area,
            "area_original": None, "tenant": None if status == "vacant" else f"Tenant {unit}", "tenant_type": None,
            "ejari_no": None if status == "vacant" else ejari, "lease_start": None,
            "lease_end": None if status == "vacant" else lease_end,
            "annual_rent_aed": None if status == "vacant" else rent, "asking_rent_aed": asking,
            "cheques": 4, "deposit_aed": None, "status": status, "status_text": status, "chiller": None,
            "source": {"doc": "rr.xlsx", "sheet": "RR", "row": row, "range": f"RR!A{row}:K{row}", "cells": {},
                       "page": None, "bbox": None}, "notes": []}


def make_rr(units: list[dict], as_of="2026-10-31", stated_totals=(), master_lease=None) -> dict:
    from pipeline.rentroll import summarise
    import datetime as dt

    return {"doc": "rr.xlsx", "units": units, "skipped_rows": [], "master_lease": master_lease,
            "stated_totals": list(stated_totals), "as_of_source": None,
            "layout": {"tables": [{"sheet": "RR", "role": "unit_leases", "first_data_row": 5,
                                   "last_data_row": 4 + len(units), "columns": [{"column": "K"}]}]},
            "summary": summarise(units, dt.date.fromisoformat(as_of) if as_of else None)}


def standard_units(n=40, rent=75_000.0, vacant=2, start=0) -> list[dict]:
    """n 1BR units of 750 sq ft (JVC reference rent 78,750), expiries spread over 2027."""
    out = []
    for i in range(n):
        month = 1 + (i % 12)
        status = "vacant" if i < vacant else "occupied"
        out.append(rr_unit(str(101 + start + i), rent=rent, status=status,
                           lease_end=f"2027-{month:02d}-28", row=5 + i))
    return out


def make_om(**fields) -> dict:
    """Verified OM fields for a JVC deal; pass name=value to override, or name=None to drop."""
    base = {
        "asking_price_aed": verified(32_000_000.0, "Asking price AED 32,000,000"),
        "market_area": verified("JVC", "Location: Jumeirah Village Circle"),
        "asset_type": verified("residential_building", "Residential building"),
        "title_type": verified({"tenure": "freehold", "ownership": "single_title"}, "Freehold, single title deed"),
        "completion_year": verified(2015, "Completed 2015"),
        "chiller_arrangement": verified("tenant_pays", "Chiller paid by tenants (Empower)"),
        "lease_structure": verified({"type": "direct_leases", "master_tenant": None}, "Direct leases, Ejari registered"),
        "upside_claims": [],
    }
    for k, v in fields.items():
        if v is None:
            base.pop(k, None)
        else:
            base[k] = v
    return base


def make_opex(totals: dict, months=12, presented=True, absent=(), rental_income=None) -> dict:
    t = dict(totals)
    if rental_income is not None:
        t["rental_income"] = rental_income
    return {"doc": "st.xlsx", "period": {"months_used": months, "presented_as_annual": presented, "annualised": False,
                                         "evidence": [], "annualisation": {"factor": 1.0, "note": "n"}},
            "amount_basis": "period_total", "vat_basis": "unstated",
            "lines": [{"label": k, "category": k, "status": "verified", "amount_aed": v,
                       "source": {"doc": "st.xlsx", "cell": "S!B2"}} for k, v in t.items()],
            "totals_by_category": t, "absent_standard_categories": list(absent), "notes": None,
            "total_deductions_aed": 0.0, "prior_period": None,
            "noi_aed": sum(v for k, v in t.items() if k in ("rental_income", "other_income"))
            - sum(v for k, v in t.items() if k not in ("rental_income", "other_income"))}


FULL_OPEX = {"maintenance_repairs": 120_000.0, "insurance": 36_000.0, "security_cleaning": 90_000.0,
             "utilities_common": 60_000.0, "admin_other": 24_000.0, "sinking_fund": 60_000.0,
             "property_management": 140_000.0}


def make_context(om=None, rr=None, opex=None):
    """A reconcile Context with a real engine run."""
    import engine
    from pipeline.reconcile import Context
    from pipeline.underwriting import build_deal_inputs, underwrite

    mandate, market = engine.load_mandate(), engine.load_market()
    om = om if om is not None else make_om()
    rr = rr if rr is not None else make_rr(standard_units())
    opex = opex if opex is not None else make_opex(FULL_OPEX, rental_income=rr["summary"]["in_place_rent_aed"])
    deal_inputs, _, _ = build_deal_inputs("t", om, rr, opex, market)
    uw = underwrite(deal_inputs, mandate, market)
    return Context(om=om, rr=rr, opex=opex, uw=uw, deal_inputs=deal_inputs, mandate=mandate, market=market)
