"""Stage 5, operating statement: the model maps lines to the chart of accounts, code totals.

The model points to the cell (or, on a PDF page without a grid, the quoted line) holding each
amount; code reads and parses the amount, totals the categories, annualises a partial period
when it has to (and says so), cross-checks the statement's own totals and lists the standard
costs that are absent.
"""

from __future__ import annotations

import base64
import datetime as dt
from typing import Any

from . import config
from .ingest import Document, a1, parse_a1, sheet_as_text, split_cell_ref
from .llm import ModelClient, ToolResult, load_prompt
from .numbers import parse_number, parse_numbers, close
from .schemas import OPEX_MAP_TOOL
from .verify import locate, verify_evidence

INCOME = ("rental_income", "other_income")
DEDUCTIONS = ("vacancy_loss", "collection_loss")
EXPENSES = ("service_charge", "district_cooling", "utilities_common", "property_management",
            "maintenance_repairs", "insurance", "security_cleaning", "marketing_leasing", "admin_other",
            "sinking_fund")


def map_statement(client: ModelClient, model: str, doc: Document) -> ToolResult:
    """Ask the model to map the statement. PDFs go as document blocks plus any table grids."""
    content: list[dict] = []
    if doc.kind == "pdf":
        data = base64.standard_b64encode(doc.path.read_bytes()).decode()
        content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                       "data": data}, "title": doc.doc_id})
    grids = "\n\n".join(sheet_as_text(s) for s in doc.sheets)
    text = f"Operating statement document `{doc.doc_id}`."
    if grids:
        text += ("\n\nCell grids" + (" read from the PDF's tables (cite these cells where the line is in a grid)"
                                      if doc.kind == "pdf" else "") + ":\n\n" + grids)
    content.append({"type": "text", "text": text})
    return client.call_tool(stage="opex_map", model=model, system=load_prompt("opex_map"), content=content,
                            tools=[OPEX_MAP_TOOL], tool_name=OPEX_MAP_TOOL["name"])


def _cell_values(doc: Document, ref: str) -> tuple[list[tuple[str, Any]], str | None]:
    """Values of a cell or a one-row/one-column range, with their addresses."""
    sheet_name, addr = split_cell_ref(ref)
    sheet = doc.sheet(sheet_name) if sheet_name else (doc.sheets[0] if len(doc.sheets) == 1 else None)
    if sheet is None:
        return [], f"sheet {sheet_name!r} not found"
    try:
        if ":" in addr:
            (r1, c1), (r2, c2) = (parse_a1(x) for x in addr.split(":", 1))
        else:
            r1, c1 = r2, c2 = parse_a1(addr)
    except ValueError as exc:
        return [], str(exc)
    return [(f"{sheet.name}!{a1(r, c)}", sheet.value(r, c))
            for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)], None


def _cell_box(doc: Document, ref: str) -> tuple[int | None, list | None]:
    sheet_name, addr = split_cell_ref(ref)
    sheet = doc.sheet(sheet_name) if sheet_name else None
    if sheet is None or sheet.page is None:
        return None, None
    try:
        r, c = parse_a1(addr.split(":")[0])
    except ValueError:
        return None, None
    cell = sheet.cell(r, c)
    return sheet.page, (list(cell.bbox) if cell is not None and cell.bbox else None)


def read_line(doc: Document, docs: list[Document], line: dict) -> dict:
    """Read one mapped line's amount from its cell(s) or verified quote. Never from the model."""
    rec: dict[str, Any] = {"label": line.get("label"), "category": line.get("category"), "sign": line.get("sign"),
                           "note": line.get("note"), "amount_aed": None, "status": "unverified", "reason": None,
                           "source": {"doc": doc.doc_id}}
    if line.get("amount_cell"):
        vals, err = _cell_values(doc, line["amount_cell"])
        nums = [parse_number(v) for _, v in vals]
        if err or not vals or nums[0] is None:
            rec["reason"] = err or f"cell {line['amount_cell']} holds no number ({vals[0][1] if vals else None!r})"
        else:
            rec.update(amount_aed=nums[0], status="verified")
        rec["source"].update(cell=vals[0][0] if vals else line["amount_cell"], label_cell=line.get("label_cell"))
        page, box = _cell_box(doc, line["amount_cell"])
        if page:
            rec["source"].update(page=page, bbox=[box] if box else [])
    elif line.get("month_cells"):
        vals, err = _cell_values(doc, line["month_cells"])
        nums = [parse_number(v) for _, v in vals]
        if err or not vals:
            rec["reason"] = err or "empty range"
        else:
            rec.update(amount_aed=sum(n for n in nums if n is not None), status="verified",
                       months_with_data=sum(1 for n in nums if n is not None))
            rec["reason"] = f"sum of {len(vals)} monthly cells"
        rec["source"].update(cells=line["month_cells"], label_cell=line.get("label_cell"))
    elif line.get("quote"):
        d, qm, page = locate(docs, doc.doc_id, line.get("page"), line.get("quote"))
        rec["source"].update(page=page, quote=line.get("quote"), bbox=qm.bboxes or [], match=qm.method)
        printed = line.get("amount_as_printed") or ""
        nums = parse_numbers(printed) if printed else []
        if not qm.found:
            rec["reason"] = qm.reason
        elif not nums or loose_digits(printed) not in loose_digits(line["quote"]):
            rec["reason"] = f"amount {printed!r} not in the quoted line"
        else:
            rec.update(amount_aed=nums[-1].value, status="verified")
    else:
        rec["reason"] = "no cell or quote given for the amount"
    if rec["amount_aed"] is not None:
        rec["amount_aed"] = abs(rec["amount_aed"])   # sign comes from the category, not the print
    return rec


def loose_digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit() or ch == ".")


def _months_between(start: str | None, end: str | None) -> int | None:
    try:
        s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except (TypeError, ValueError):
        return None
    months = (e.year - s.year) * 12 + (e.month - s.month) + (1 if e.day >= 28 or e.day >= s.day else 0)
    return max(1, months)


def build_opex(doc: Document, docs: list[Document], mapping: dict, chiller_landlord_pays: bool | None) -> dict:
    """Totals by category (annual), period, cross-checks and absent standard costs."""
    lines = [read_line(doc, docs, ln) for ln in mapping.get("lines", [])]
    period = dict(mapping.get("period") or {})
    period["evidence"] = verify_evidence(period.get("evidence"), docs)
    months_from_dates = _months_between(period.get("start"), period.get("end"))
    months = period.get("months_covered") or months_from_dates
    if months_from_dates and period.get("months_covered") and months_from_dates != period["months_covered"]:
        period["months_note"] = (f"model says {period['months_covered']} months; dates span {months_from_dates}; "
                                 f"using the dates")
        months = months_from_dates
    monthly_counts = [ln.get("months_with_data") for ln in lines if ln.get("months_with_data")]
    if mapping.get("amount_basis") == "monthly_columns" and monthly_counts:
        months = max(monthly_counts)
    period["months_used"] = months

    basis = mapping.get("amount_basis", "period_total")
    factor, factor_note = 1.0, "amounts are for a 12-month period"
    if months and months < 12 and basis != "annualised_total":
        factor, factor_note = 12.0 / months, f"{months}-month figures annualised by code (x 12/{months})"
    elif basis == "annualised_total":
        factor_note = f"amounts are already annualised by the seller from {months} months" if months and months < 12 \
            else "amounts are stated as annualised"
    period["annualisation"] = {"factor": round(factor, 6), "note": factor_note}

    totals: dict[str, float] = {}
    for ln in lines:
        cat = ln["category"]
        if ln["status"] != "verified" or cat in ("total_or_subtotal", "non_operating") or ln["amount_aed"] is None:
            continue
        totals[cat] = totals.get(cat, 0.0) + ln["amount_aed"] * factor
    totals = {k: round(v, 2) for k, v in totals.items()}

    income = sum(totals.get(c, 0.0) for c in INCOME)
    deductions = sum(totals.get(c, 0.0) for c in DEDUCTIONS)
    expenses = sum(totals.get(c, 0.0) for c in EXPENSES)
    noi = income - deductions - expenses

    checks = []
    for st in mapping.get("stated_totals", []):
        stated = None
        where: dict[str, Any] = {}
        if st.get("amount_cell"):
            vals, _ = _cell_values(doc, st["amount_cell"])
            stated = parse_number(vals[0][1]) if vals else None
            where = {"cell": st["amount_cell"]}
        elif st.get("quote"):
            d, qm, page = locate(docs, doc.doc_id, st.get("page"), st.get("quote"))
            nums = parse_numbers(st["quote"]) if qm.found else []
            stated = nums[-1].value if nums else None
            where = {"page": page, "quote": st["quote"], "bbox": qm.bboxes or []}
        computed = {"total_income": income - deductions, "total_expenses": expenses, "noi": noi}.get(st.get("measure"))
        if stated is None or computed is None:
            continue
        stated_annual = abs(stated) * factor
        alt = {"total_income": income}.get(st.get("measure"))   # some statements show gross income
        ok = close(stated_annual, abs(computed), rel=0.005, abs_tol=1000) or (
            alt is not None and close(stated_annual, alt, rel=0.005, abs_tol=1000))
        checks.append({"measure": st["measure"], "label": st.get("label"), "stated_aed": stated,
                       "stated_annualised_aed": round(stated_annual, 2), "computed_aed": round(computed, 2),
                       "foots": ok, **where})

    expected = list(config.STANDARD_OPEX_CATEGORIES)
    if chiller_landlord_pays:
        expected.append(config.CHILLER_CATEGORY)
    absent = [c for c in expected if not totals.get(c)]
    return {
        "doc": doc.doc_id,
        "period": period,
        "amount_basis": basis,
        "vat_basis": mapping.get("vat_basis", "unstated"),
        "lines": lines,
        "totals_by_category": totals,
        "total_income_aed": round(income, 2),
        "total_deductions_aed": round(deductions, 2),
        "total_expenses_aed": round(expenses, 2),
        "noi_aed": round(noi, 2),
        "opex_ratio": round(expenses / income, 4) if income else None,
        "stated_total_checks": checks,
        "absent_standard_categories": absent,
        "unverified_lines": [ln["label"] for ln in lines if ln["status"] != "verified"
                             and ln["category"] not in ("total_or_subtotal",)],
        "notes": mapping.get("notes"),
    }


def run_opex(client: ModelClient, model: str, doc: Document, docs: list[Document],
             chiller_landlord_pays: bool | None) -> tuple[dict, ToolResult]:
    result = map_statement(client, model, doc)
    return build_opex(doc, docs, result.data, chiller_landlord_pays), result

