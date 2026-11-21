"""Stage 2, extract (model), and the OM half of stage 3 (verify).

The OM goes to the model as a native PDF document block, so the model sees the layout (and
the page images of a scanned OM). The same block, marked for prompt caching, is reused by the
review pass in :mod:`pipeline.reconcile`; :func:`om_content` builds the shared prefix.
"""

from __future__ import annotations

import base64

from .ingest import Document
from .llm import ModelClient, ToolResult, load_prompt
from .schemas import om_fields_schema, om_tools
from .verify import verify_field, verify_upside_claims


def document_list(docs: list[Document]) -> str:
    lines = []
    for d in docs:
        what = f"{len(d.pages)} pages" if d.kind == "pdf" else f"sheets {[s.name for s in d.sheets]}"
        scanned = ", scanned (no text layer)" if d.scanned else ""
        lines.append(f"- `{d.doc_id}` ({d.kind}, {what}{scanned}; looks like: {d.role})")
    return "\n".join(lines)


def om_content(om: Document) -> list[dict]:
    """Cached prefix shared by every call about the OM: a label and the PDF itself."""
    data = base64.standard_b64encode(om.path.read_bytes()).decode()
    return [
        {"type": "text", "text": f"Offering memorandum, document id `{om.doc_id}`:"},
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data},
         "title": om.doc_id, "cache_control": {"type": "ephemeral"}},
    ]


def extract_om(client: ModelClient, model: str, docs: list[Document], om: Document,
               market_areas: list[str]) -> tuple[dict, ToolResult]:
    """Ask the model for the OM fields, then verify each one. Returns (verified fields, raw result)."""
    scan_note = ""
    if om.scanned:
        pages = [str(p.number) for p in om.pages if p.ocr]
        scan_note = (f"Pages {', '.join(pages)} are scanned images with no text layer: read them carefully and "
                     "quote exactly what is printed, including figures.")
    instruction = load_prompt("extract_om", document_list=document_list(docs), om_doc=om.doc_id, scan_note=scan_note)
    result = client.call_tool(stage="extract_om", model=model, system=load_prompt("om_system"),
                              content=om_content(om) + [{"type": "text", "text": instruction}],
                              tools=om_tools(market_areas), tool_name="record_om_fields")
    return verify_om_fields(result.data, docs, market_areas), result


def verify_om_fields(data: dict, docs: list[Document], market_areas: list[str]) -> dict:
    """Run the verifier over every OM field; the run.json ``extracted.om`` block."""
    fields = {name: verify_field(name, data.get(name), docs) for name in om_fields_schema(market_areas)}
    fields["upside_claims"] = verify_upside_claims(data.get("upside_claims"), docs)
    return fields
