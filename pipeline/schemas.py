"""Tool schemas the model fills (structured output via tool use).

Each extracted field shares one envelope: ``value``, ``unit``, ``as_of``, ``source`` (doc and
page), a verbatim ``quote`` and ``null_reason`` when the document does not state it. A few
fields add a ``basis`` (how the OM itself defines the number). Numbers are returned as stated
in the document's own unit; code converts (sq m to sq ft) and checks every value against its
quote, so the model never does arithmetic that reaches the engine.
"""

from __future__ import annotations

from typing import Any

SOURCE = {
    "type": ["object", "null"],
    "properties": {
        "doc": {"type": "string", "description": "Document id exactly as given in the document list."},
        "page": {"type": "integer", "description": "1-based PDF page number where the quote appears."},
    },
    "required": ["doc", "page"],
}


def _field(value_schema: dict, description: str, extra: dict | None = None,
           unit_enum: list[str] | None = None) -> dict:
    props: dict[str, Any] = {
        "value": value_schema,
        "unit": {"type": ["string", "null"], **({"enum": unit_enum + [None]} if unit_enum else {}),
                 "description": "Unit of value as stated in the document."},
        "as_of": {"type": ["string", "null"], "description": "Date or period the document gives for this figure, verbatim; null if none."},
        "source": SOURCE,
        "quote": {"type": ["string", "null"], "description": "Verbatim text copied from the cited page that states the value (label and figure). Null only when value is null."},
        "null_reason": {"type": ["string", "null"], "description": "Why value is null (e.g. 'not stated in the OM'). Null when value is given."},
    }
    if extra:
        props.update(extra)
    return {"type": "object", "description": description, "properties": props,
            "required": ["value", "source", "quote", "null_reason"]}


NUM = {"type": ["number", "null"]}
INT = {"type": ["integer", "null"]}
STR = {"type": ["string", "null"]}


def _enum(values: list[str]) -> dict:
    return {"type": ["string", "null"], "enum": values + [None]}


def om_fields_schema(market_areas: list[str]) -> dict:
    """Properties of the OM extraction tool; ``market_areas`` are the areas.yaml keys."""
    return {
        "building_name": _field(STR, "Name of the building."),
        "asset_type": _field(_enum(["residential_building", "mixed_use_residential_retail", "other"]),
                             "Residential building; residential with ground-floor retail counts as mixed_use_residential_retail."),
        "area": _field(STR, "Location as written (community / district)."),
        "market_area": _field(_enum(market_areas + ["none_of_these"]),
                              "Which of the listed market areas the stated location falls in. Quote the location text. "
                              "none_of_these if it is not one of them."),
        "plot_number": _field(STR, "Plot number as written."),
        "title_type": _field(
            {"type": ["object", "null"], "properties": {
                "tenure": {"type": "string", "enum": ["freehold", "non_freehold", "unstated"]},
                "ownership": {"type": "string", "enum": ["single_title", "strata", "unstated"]}},
             "required": ["tenure", "ownership"]},
            "Tenure and ownership exactly as the OM states them. Use 'unstated' for any part the OM does not say. "
            "Do not infer freehold from the area name."),
        "completion_year": _field(INT, "Year of completion (building completion certificate)."),
        "floors": _field(STR, "Floor description as written, e.g. 'G+P+7'."),
        "unit_count": _field(INT, "Total number of units (apartments plus shops) stated in the OM."),
        "unit_mix": _field(
            {"type": ["object", "null"], "properties": {
                k: {"type": ["integer", "null"]} for k in ("studio", "1br", "2br", "3br", "retail", "other")}},
            "Count of units by type as stated in the OM. Quote must contain the counts (e.g. the unit-mix table row text)."),
        "bua_sqft": _field(NUM, "Built-up area as stated. Return the number in the unit printed (sqft or sqm); code converts.",
                           unit_enum=["sqft", "sqm"]),
        "nsa_sqft": _field(NUM, "Net saleable / leasable area as stated. Return the number in the unit printed (sqft or sqm).",
                           unit_enum=["sqft", "sqm"]),
        "parking_spaces": _field(INT, "Number of parking spaces."),
        "occupancy_stated": _field(NUM, "Occupancy the OM states, as a ratio (96% -> 0.96). as_of is the date the OM gives for it, or null if undated.",
                                   unit_enum=["ratio"]),
        "annual_rent_stated": _field(
            NUM, "Annual rental income the OM states, in AED.",
            extra={"basis": {"type": "string", "enum": ["in_place", "potential", "unstated"],
                             "description": "The OM's own basis: in_place (contracted rent of let units), potential (includes vacant units at asking or projected rents), unstated."}},
            unit_enum=["AED"]),
        "net_income_stated_aed": _field(NUM, "Net operating income the OM states, in AED, if any.", unit_enum=["AED"]),
        "opex_stated_aed": _field(NUM, "Annual operating expenses the OM states, in AED, if any.", unit_enum=["AED"]),
        "yield_stated": _field(
            NUM, "Headline yield / ROI / cap rate the OM states, as a ratio (8.65% -> 0.0865).",
            extra={"basis": {"type": "object", "properties": {
                "measure": {"type": "string", "enum": ["gross", "net", "unstated"],
                            "description": "What the OM calls it. 'ROI' or 'yield' with no qualifier is unstated."},
                "on": {"type": "string", "enum": ["asking_price", "total_cost", "unstated"],
                       "description": "Denominator the OM says it uses; total_cost only if it says acquisition costs / DLD are included."}},
                "required": ["measure", "on"]}},
            unit_enum=["ratio"]),
        "asking_price_aed": _field(NUM, "Asking price in AED (full number, e.g. 48.5m -> 48500000).", unit_enum=["AED"]),
        "price_psf_stated": _field(
            NUM, "Price per square foot the OM quotes, in AED, if any.",
            extra={"basis": {"type": "string", "enum": ["nsa", "bua", "unstated"],
                             "description": "The area the OM says the figure is on. unstated if it does not say."}},
            unit_enum=["AED/sqft"]),
        "chiller_arrangement": _field(_enum(["tenant_pays", "landlord_pays", "unstated"]),
                                      "Who pays district cooling / chiller. 'Chiller-free' means landlord_pays."),
        "lease_structure": _field(
            {"type": ["object", "null"], "properties": {
                "type": {"type": "string", "enum": ["direct_leases", "master_lease", "unstated"]},
                "master_tenant": {"type": ["string", "null"]}},
             "required": ["type", "master_tenant"]},
            "Whether income comes from direct unit leases or a master / bulk lease, and the master tenant's name."),
    }


UPSIDE_CLAIMS = {
    "type": "array",
    "description": "Every claim of rental upside, reversion or rent growth, verbatim. Empty if none.",
    "items": {
        "type": "object",
        "properties": {
            "quote": {"type": "string", "description": "Verbatim claim."},
            "source": SOURCE,
            "claimed_uplift": {"type": ["number", "null"],
                               "description": "Uplift the claim states as a ratio (15% -> 0.15), only if a figure is printed in the quote."},
            "applies_to": {"type": ["string", "null"], "description": "What the claim applies to as stated (e.g. '2027 renewals')."},
        },
        "required": ["quote", "source", "claimed_uplift"],
    },
}


def om_extraction_tool(market_areas: list[str]) -> dict:
    return {
        "name": "record_om_fields",
        "description": "Record the fields stated in the offering memorandum, each with its page and verbatim quote.",
        "input_schema": {
            "type": "object",
            "properties": {**om_fields_schema(market_areas), "upside_claims": UPSIDE_CLAIMS},
            "required": list(om_fields_schema(market_areas)) + ["upside_claims"],
        },
    }


EVIDENCE = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "doc": {"type": "string"},
            "page": {"type": ["integer", "null"], "description": "PDF page (1-based); null for a spreadsheet."},
            "cell": {"type": ["string", "null"], "description": "Sheet!A1 cell or range for a spreadsheet; null for a PDF."},
            "quote": {"type": "string", "description": "Verbatim text from that page or cell."},
        },
        "required": ["doc", "quote"],
    },
}

REVIEW_TOOL = {
    "name": "record_review_findings",
    "description": "Record discrepancies the deterministic checks cannot test, each backed by verbatim quotes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": [
                            "master_lease_related_party", "title_check", "upside_exceeds_rera_cap",
                            "potential_rent_as_income", "other_om_claim"]},
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                        "title": {"type": "string", "description": "One line, plain English."},
                        "evidence": EVIDENCE,
                        "why": {"type": "string", "description": "Why this matters to a buyer, citing the evidence."},
                        "analyst_action": {"type": "string", "description": "The concrete document or check to request."},
                        "related_party": {"type": ["boolean", "null"], "description": "master_lease_related_party only: does the evidence say the master tenant is related to the seller?"},
                    },
                    "required": ["id", "severity", "title", "evidence", "why", "analyst_action"],
                },
            },
            "lease_structure_conclusion": {
                "type": "string", "enum": ["direct_leases", "master_lease_related_party", "master_lease_third_party", "unclear"],
                "description": "What the documents together say about how income is earned."},
        },
        "required": ["findings", "lease_structure_conclusion"],
    },
}

def om_tools(market_areas: list[str]) -> list[dict]:
    """Both tools used with the cached OM. They are sent together on every OM call so the cache prefix matches."""
    return [om_extraction_tool(market_areas), REVIEW_TOOL]


RENT_ROLL_FIELDS = ["unit", "unit_type", "area", "tenant", "tenant_type", "ejari_no", "lease_start", "lease_end",
                    "annual_rent", "cheques", "deposit", "status", "chiller", "floor", "asking_rent", "monthly_rent",
                    "remarks", "ignore"]

RENT_ROLL_MAP_TOOL = {
    "name": "record_rent_roll_layout",
    "description": "Describe the layout of the rent roll so code can parse every unit row.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tables": {
                "type": "array",
                "description": "One entry per block of unit rows that shares a header (usually one per sheet).",
                "items": {
                    "type": "object",
                    "properties": {
                        "sheet": {"type": "string", "description": "Sheet name exactly as given."},
                        "role": {"type": "string", "enum": ["unit_leases", "sub_leases", "other"],
                                 "description": "unit_leases for a normal rent roll; sub_leases for an operator's sub-lettings under a master lease."},
                        "header_rows": {"type": "array", "items": {"type": "integer"}, "description": "Row number(s) of the header (several if merged/two-line)."},
                        "first_data_row": {"type": "integer"},
                        "last_data_row": {"type": "integer", "description": "Last row of this block that can hold a unit (inclusive)."},
                        "columns": {
                            "type": "array",
                            "items": {"type": "object", "properties": {
                                "column": {"type": "string", "description": "Column letter, e.g. 'C'."},
                                "header_text": {"type": "string", "description": "Header text as it appears."},
                                "field": {"type": "string", "enum": RENT_ROLL_FIELDS},
                                "unit_of_measure": {"type": ["string", "null"], "enum": ["sqft", "sqm", "AED_per_year", "AED_per_month", "count", None]},
                            }, "required": ["column", "header_text", "field"]},
                        },
                        "exclude_rows": {
                            "type": "array",
                            "description": "Rows inside the block that are not units: totals, subtotals, section headings, blanks, notes.",
                            "items": {"type": "object", "properties": {
                                "row": {"type": "integer"},
                                "kind": {"type": "string", "enum": ["total", "subtotal", "section", "blank", "note", "other"]},
                            }, "required": ["row", "kind"]},
                        },
                    },
                    "required": ["sheet", "role", "header_rows", "first_data_row", "last_data_row", "columns", "exclude_rows"],
                },
            },
            "date_format": {"type": "string", "enum": ["DMY", "MDY", "YMD", "excel_dates"], "description": "How dates in text cells are written."},
            "as_of": {"type": ["object", "null"], "properties": {
                "value": {"type": "string", "description": "Rent roll date as written."},
                "cell": {"type": "string", "description": "Sheet!A1 where it is written."}},
                "description": "The date of the rent roll, if stated."},
            "status_vocabulary": {
                "type": "array",
                "description": "Every distinct status value in the status column, mapped to the standard status.",
                "items": {"type": "object", "properties": {
                    "text": {"type": "string"},
                    "status": {"type": "string", "enum": ["occupied", "vacant", "notice_served", "under_renewal", "legal_case"]}},
                    "required": ["text", "status"]},
            },
            "unit_type_vocabulary": {
                "type": "array",
                "description": "Every distinct unit-type value mapped to studio, 1br, 2br, 3br or retail.",
                "items": {"type": "object", "properties": {
                    "text": {"type": "string"},
                    "unit_type": {"type": "string", "enum": ["studio", "1br", "2br", "3br", "retail", "other"]}},
                    "required": ["text", "unit_type"]},
            },
            "summary_rows": {
                "type": "array",
                "description": "Rows that state totals for the whole roll, so code can check they foot. Give the cells holding each total.",
                "items": {"type": "object", "properties": {
                    "sheet": {"type": "string"},
                    "row": {"type": "integer"},
                    "label": {"type": "string"},
                    "cells": {"type": "array", "items": {"type": "object", "properties": {
                        "cell": {"type": "string", "description": "A1 address in that sheet."},
                        "measure": {"type": "string", "enum": ["annual_rent", "area", "unit_count", "occupied_units", "vacant_units", "occupancy", "deposit", "other"]}},
                        "required": ["cell", "measure"]}}},
                    "required": ["sheet", "row", "label", "cells"]},
            },
            "master_lease": {
                "type": ["object", "null"],
                "description": "Only if the building is let under a master / bulk lease: the cells (Sheet!A1) that hold its terms. Null otherwise.",
                "properties": {k: {"type": ["string", "null"]} for k in
                               ("tenant_cell", "annual_rent_cell", "lease_start_cell", "lease_end_cell", "cheques_cell")},
                "required": ["tenant_cell", "annual_rent_cell", "lease_end_cell"]},
            "notes": {"type": ["string", "null"], "description": "Anything about the layout a parser must know (e.g. vacant rows show asking rent)."},
        },
        "required": ["tables", "date_format", "status_vocabulary", "unit_type_vocabulary", "summary_rows", "master_lease"],
    },
}

OPEX_CATEGORIES_ALL = ["rental_income", "other_income", "vacancy_loss", "collection_loss", "service_charge",
                       "district_cooling", "utilities_common", "property_management", "maintenance_repairs",
                       "insurance", "security_cleaning", "marketing_leasing", "admin_other", "sinking_fund",
                       "total_or_subtotal", "non_operating"]

OPEX_MAP_TOOL = {
    "name": "record_statement_mapping",
    "description": "Map every line of the operating statement to the chart of accounts, with cells or quotes, and state the period.",
    "input_schema": {
        "type": "object",
        "properties": {
            "period": {"type": "object", "properties": {
                "start": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "end": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                "months_covered": {"type": ["integer", "null"], "description": "Months of actual data the figures cover."},
                "presented_as_annual": {"type": "boolean", "description": "Does the title or a column present the figures as a full year / FY?"},
                "annualised": {"type": "boolean", "description": "Are the figures scaled up from fewer months (e.g. 'annualised', '9M x 12/9')?"},
                "evidence": EVIDENCE},
                "required": ["start", "end", "months_covered", "presented_as_annual", "annualised", "evidence"]},
            "amount_basis": {"type": "string", "enum": ["period_total", "annualised_total", "monthly_columns"],
                             "description": "period_total: one amount per line for the period; annualised_total: the amount column is already annualised; monthly_columns: one column per month and no total column."},
            "lines": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "label": {"type": "string", "description": "Line label verbatim."},
                    "category": {"type": "string", "enum": OPEX_CATEGORIES_ALL},
                    "label_cell": {"type": ["string", "null"], "description": "Spreadsheet / table: Sheet!A1 of the label."},
                    "amount_cell": {"type": ["string", "null"], "description": "Sheet!A1 of the amount for the whole period (total column). Null if only monthly cells exist."},
                    "month_cells": {"type": ["string", "null"], "description": "Sheet!B5:M5 range of monthly amounts, when there is no total column."},
                    "page": {"type": ["integer", "null"], "description": "PDF page, when citing a quote instead of a cell."},
                    "quote": {"type": ["string", "null"], "description": "PDF: verbatim line text including the amount."},
                    "amount_as_printed": {"type": ["string", "null"], "description": "The amount exactly as printed, e.g. '(12,500)'."},
                    "sign": {"type": "string", "enum": ["income", "expense", "deduction"], "description": "income for income lines, deduction for vacancy/collection losses, expense for costs."},
                    "note": {"type": ["string", "null"]}},
                    "required": ["label", "category", "sign"]},
            },
            "stated_totals": {
                "type": "array",
                "description": "Totals the statement prints (total income, total expenses, NOI), for cross-checking.",
                "items": {"type": "object", "properties": {
                    "label": {"type": "string"},
                    "measure": {"type": "string", "enum": ["total_income", "total_expenses", "noi", "other"]},
                    "amount_cell": {"type": ["string", "null"]},
                    "page": {"type": ["integer", "null"]},
                    "quote": {"type": ["string", "null"]}},
                    "required": ["label", "measure"]},
            },
            "vat_basis": {"type": "string", "enum": ["includes_vat", "excludes_vat", "unstated"]},
            "prior_period": {
                "type": ["object", "null"],
                "description": "Only if the statement also shows an earlier comparable period: where its totals are.",
                "properties": {
                    "label": {"type": "string", "description": "Column or period label, e.g. 'FY2025'."},
                    "noi_cell": {"type": ["string", "null"]},
                    "total_income_cell": {"type": ["string", "null"]},
                    "total_expenses_cell": {"type": ["string", "null"]},
                    "page": {"type": ["integer", "null"]},
                    "noi_quote": {"type": ["string", "null"], "description": "PDF: verbatim NOI line text including the prior-period amount."},
                    "noi_as_printed": {"type": ["string", "null"]}},
                "required": ["label"]},
            "notes": {"type": ["string", "null"]},
        },
        "required": ["period", "amount_basis", "lines", "stated_totals", "vat_basis", "prior_period"],
    },
}

MEMO_TOOL = {
    "name": "submit_memo",
    "description": "Submit the screening memo in markdown, with every number anchored to a fact-sheet key.",
    "input_schema": {
        "type": "object",
        "properties": {"markdown": {"type": "string"}},
        "required": ["markdown"],
    },
}
