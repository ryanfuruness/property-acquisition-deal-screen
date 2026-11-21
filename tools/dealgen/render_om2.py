"""Held-out brokerage designs.

Qamar & Partners: dense, text-heavy two-column memorandum in small type that quotes several yields.
Tessellate: sparse modern layout whose key tables are embedded as images (no text layer for them).
"""
from __future__ import annotations

import io
from datetime import date

from PIL import Image as PILImage, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

from .analysis import OCC_LIKE
from .refdata import BROKERS, FOOTER, LOCATION, UNIT_LABELS
from .render_om import (aed, aedm, asset_info, chiller_text, draw_elevation, esc, location_name, location_plan, mix_rows,
                        pct, upside_text, Elevation)


# =========================================================================== Qamar & Partners
def build_qamar(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["qamar"]
    W, H = A4
    TEAL, INK = colors.HexColor("#0E4D55"), colors.HexColor("#1A1A1A")
    F, FB = "Narrow", "Narrow-Bold"
    s_h = ParagraphStyle("h", fontName=FB, fontSize=9.6, leading=11.5, textColor=TEAL, spaceBefore=2.6 * mm, spaceAfter=1.2 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=7.9, leading=9.9, textColor=INK, spaceAfter=1.6 * mm, alignment=4)
    s_sm = ParagraphStyle("s", fontName=F, fontSize=6.8, leading=8.4, textColor=colors.HexColor("#555555"), alignment=4)
    master = b["master_lease"]
    month = ctx["om_date"].strftime("%B %Y")
    yl = om["yield"]
    asset_v, asset_t = asset_info(b)

    def deco(c, d, first=False):
        c.saveState()
        c.setStrokeColor(TEAL)
        c.setLineWidth(1.4)
        c.line(14 * mm, H - 13 * mm, W - 14 * mm, H - 13 * mm)
        c.setFillColor(TEAL)
        c.setFont(FB, 8)
        c.drawString(14 * mm, H - 11 * mm, "QAMAR & PARTNERS  |  INVESTMENT ADVISORY")
        c.setFont(F, 7.5)
        c.drawRightString(W - 14 * mm, H - 11 * mm, f"{b['name']}  -  Investment Memorandum  -  {month}  -  p.{d.page}")
        c.setFillColor(colors.HexColor("#777777"))
        c.setFont(F, 6.3)
        c.drawString(14 * mm, 10.5 * mm, br["confidential"])
        c.drawCentredString(W / 2, 6.5 * mm, FOOTER)
        c.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=A4, title=f"{b['name']} - Investment Memorandum", author=br["name"], invariant=1)
    gap = 6 * mm
    cw = (W - 28 * mm - gap) / 2
    fr = [Frame(14 * mm, 15 * mm, cw, H - 32 * mm, id="c1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
          Frame(14 * mm + cw + gap, 15 * mm, cw, H - 32 * mm, id="c2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]
    top = Frame(14 * mm, H - 105 * mm, W - 28 * mm, 88 * mm, id="top", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    fr1 = [top, Frame(14 * mm, 15 * mm, cw, H - 125 * mm, id="d1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
           Frame(14 * mm + cw + gap, 15 * mm, cw, H - 125 * mm, id="d2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]
    doc.addPageTemplates([PageTemplate(id="first", frames=fr1, onPage=lambda c, d: deco(c, d, True)),
                          PageTemplate(id="cols", frames=fr, onPage=deco)])
    st = []
    # ---- masthead block (full width)
    st.append(Paragraph(esc(f"{b['name'].upper()}"), ParagraphStyle("t", fontName=FB, fontSize=21, leading=24, textColor=TEAL)))
    o.rec("building_name", b["name"], b["name"].upper())
    st.append(Paragraph(esc(f"{asset_t} of {om['unit_count']} units  |  {location_name(b)}  |  Investment Memorandum, {month}"),
                        ParagraphStyle("st", fontName=F, fontSize=10, leading=13, textColor=INK, spaceAfter=3 * mm)))
    kf = [
        ["Asking price", o.rec("asking_price_aed", om["asking_price_aed"], aed(om["asking_price_aed"])),
         "Passing rent", o.rec("annual_rent_stated", om["annual_rent"]["value"], f"{aed(om['annual_rent']['value'])} p.a.",
                               basis=om["annual_rent"]["basis"])],
        ["Occupancy", o.rec("occupancy_stated", om["occupancy"]["value"], f"{pct(om['occupancy']['value'], 0)} let", as_of=None),
         "Headline yield", o.rec("yield_stated", yl["value"], f"{pct(yl['value'], 2)} ({yl['label'].lower()})",
                                 basis={"measure": yl["basis"], "on": yl["on"]})],
        ["Units", o.rec("unit_count", om["unit_count"], f"{om['unit_count']} units"),
         "Tenure", o.rec("title_type", om["title_type"], "Freehold, single title")],
    ]
    t = Table(kf, colWidths=[28 * mm, 62 * mm, 28 * mm, 64 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 8.6), ("FONT", (0, 0), (0, -1), FB, 8.6), ("FONT", (2, 0), (2, -1), FB, 8.6),
                           ("TEXTCOLOR", (0, 0), (0, -1), TEAL), ("TEXTCOLOR", (2, 0), (2, -1), TEAL),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C9CB")), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    st.append(t)
    st.append(Spacer(1, 3 * mm))
    st.append(Elevation(b, W - 28 * mm, 44 * mm, (colors.HexColor("#C9D8DA"), colors.HexColor("#F1F4F4"), colors.HexColor("#E2DCD0"),
                                                  colors.HexColor("#4E6A70"), colors.HexColor("#FFFFFF")), spec["seed"],
                        "Illustrative elevation.", font=F))
    st.append(NextPageTemplate("cols"))
    from reportlab.platypus import FrameBreak
    st.append(FrameBreak())
    # ---- 1 summary
    st.append(Paragraph("1. SUMMARY OF THE OPPORTUNITY", s_h))
    st.append(Paragraph(esc(
        f"Qamar & Partners has been appointed on an exclusive basis to market {b['name']}, a {b['floors']} "
        f"{asset_t.lower()} completed in {b['completion_year']} in {b['sub_community']}. The building comprises "
        f"{om['unit_count']} units with a net saleable area of {om['nsa_sqft']:,} sq ft and is offered with the benefit of "
        f"the existing tenancies. The asset is held on one freehold title and has been in the same ownership since completion."), s_b))
    if master:
        st.append(Paragraph(esc(
            f"Income is secured by an income assurance agreement: the building is let in its entirety to "
            f"{master['tenant']}, the property management arm of the Seller's group, at "
            f"{aed(master['annual_rent_aed'])} per annum until {date.fromisoformat(master['end']).strftime('%B %Y')}. "
            f"The Seller, {b['seller']}, and the operator are under common ownership."), s_b))
        o.rec("lease_structure", om["lease_structure"], f"let in its entirety to {master['tenant']}")
        o.rec("seller", b["seller"], f"The Seller, {b['seller']}, and the operator are under common ownership")
    else:
        o.rec("lease_structure", om["lease_structure"], "let on individual tenancy contracts")
        st.append(Paragraph(esc("The units are let on individual tenancy contracts registered with Ejari, typically for "
                                "twelve months, with rent paid by post-dated cheques."), s_b))
    # ---- 2 property
    st.append(Paragraph("2. THE PROPERTY", s_h))
    st.append(Paragraph(esc(
        f"The building occupies plot {b['plot_number']} ({b['plot_area_sqft']:,} sq ft) and rises {b['floors']}. "
        f"Built-up area is {om['bua_sqft']:,} sq ft including parking, plant and circulation, giving an efficiency of "
        f"{om['nsa_sqft'] / om['bua_sqft'] * 100:.0f}% on the net saleable area of {om['nsa_sqft']:,} sq ft. There are "
        f"{b['parking_spaces']} parking spaces and {b['lifts']} lifts. Cooling: {chiller_text(b, 'formal').lower()}."), s_b))
    o.rec("plot_number", b["plot_number"], f"plot {b['plot_number']}")
    o.rec("floors", b["floors"], f"rises {b['floors']}")
    o.rec("bua_sqft", om["bua_sqft"], f"Built-up area is {om['bua_sqft']:,} sq ft")
    o.rec("nsa_sqft", om["nsa_sqft"], f"net saleable area of {om['nsa_sqft']:,} sq ft", original={"value": om["nsa_sqft"], "unit": "sq ft"})
    o.rec("parking_spaces", b["parking_spaces"], f"{b['parking_spaces']} parking spaces")
    o.rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "formal").lower())
    o.rec("completion_year", b["completion_year"], f"completed in {b['completion_year']}")
    o.rec("asset_type", asset_v, asset_t.lower())
    o.rec("area", b["area"], b["sub_community"])
    data = [["Type", "Units", "Avg size", "Avg rent"]]
    for t_, n, lo, hi_, avg, rent in mix_rows(ctx, om):
        data.append([UNIT_LABELS[t_], str(n), f"{avg:,.0f}", f"{rent:,.0f}" if rent else "-"])
    first = mix_rows(ctx, om)[0]
    o.rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[first[0]]} {first[1]}")
    t = Table(data, colWidths=[30 * mm, 14 * mm, 20 * mm, 22 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 7.6), ("FONT", (0, 0), (-1, 0), FB, 7.6), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    st += [t, Spacer(1, 1.5 * mm)]
    # ---- 3 location
    loc = LOCATION[b["loc_key"]]
    st.append(Paragraph("3. LOCATION AND COMMUNITY", s_h))
    st.append(Paragraph(esc(loc["intro"]), s_b))
    st.append(Paragraph(esc("Approximate drive times: " + "; ".join(f"{a} {v}" for a, v in loc["access"]) + "."), s_b))
    # ---- 4 tenancy
    occ = [u for u in b["units"] if u["status"] in OCC_LIKE]
    corp = sum(1 for u in occ if u["tenant_type"] == "company")
    st.append(Paragraph("4. TENANCY", s_h))
    st.append(Paragraph(esc(
        f"The rent roll lists {len(occ)} let units, of which {corp} are let to companies, often for staff accommodation. "
        f"Leases are annual; the expiry profile is spread through the year. Deposits are held at around 5% of annual rent "
        f"and will be transferred to the purchaser on completion. Rents are stated exclusive of VAT; residential rent is "
        f"exempt, while rent from the ground-floor shops carries 5% VAT."), s_b))
    # ---- 5 financial analysis
    st.append(Paragraph("5. FINANCIAL ANALYSIS", s_h))
    stmt = ctx["stmt_truth"]
    st.append(Paragraph(esc(
        f"Passing rent from the current rent roll is {aed(om['annual_rent']['value'])} per annum. The owner's operating "
        f"statement ({stmt['title']}) shows rental income of {aed(stmt['rental_income_aed'])} and operating costs of "
        f"{aed(stmt['total_opex_aed'])}. At the asking price of {aed(om['asking_price_aed'])} the investment shows the "
        f"following returns:"), s_b))
    rows = [[Paragraph(esc(y["label"]), ParagraphStyle("yl", fontName=F, fontSize=7.6, leading=9)),
             (pct(y["value"], 2) if y["measure"] != "psf" else f"AED {y['value']:,}")] for y in om["yields_all"]]
    o.fields["yields_all"] = {"value": om["yields_all"], "quote": om["yields_all"][0]["label"]}
    t = Table(rows, colWidths=[66 * mm, 22 * mm])
    t.setStyle(TableStyle([("FONT", (1, 0), (1, -1), FB, 8), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#B7C9CB")), ("TOPPADDING", (0, 0), (-1, -1), 1.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    st += [t, Spacer(1, 1.5 * mm)]
    if om.get("opex_stated_aed"):
        o.fields["opex_stated_aed"] = {"value": om["opex_stated_aed"], "quote": yl.get("deduction_label", ""),
                                       "label": "deduction in net yield"}
    o.rec("price_psf", om["price_psf"], "Price per sq ft (NSA)")
    st.append(Paragraph(esc(
        "The yields above are calculated on the asking price. Purchasers should allow for Dubai Land Department transfer "
        "fees, agency fees and their own operating assumptions."), s_sm))
    up = upside_text(om)
    if up:
        st.append(Paragraph(esc(o.rec("upside_claims", [up], up)), s_b))
    # ---- tenancy detail: concentration, expiry, floor schedule
    by_t = {}
    for u in occ:
        by_t[u["tenant"]] = by_t.get(u["tenant"], 0) + (u["annual_rent_aed"] or 0)
    tot_r = sum(by_t.values())
    top = sorted(by_t.items(), key=lambda kv: -kv[1])[:5]
    rows = [["Largest tenants by rent", "Units", "AED p.a.", "Share"]]
    for nm, r_ in top:
        n_ = sum(1 for u in occ if u["tenant"] == nm)
        rows.append([Paragraph(esc(nm), ParagraphStyle("tn", fontName=F, fontSize=7, leading=8.2)), str(n_), f"{r_:,}", pct(r_ / tot_r, 1)])
    t = Table(rows, colWidths=[46 * mm, 10 * mm, 18 * mm, 14 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 7.2), ("FONT", (0, 0), (-1, 0), FB, 7.2), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    st += [t, Spacer(1, 2 * mm)]
    rd = b["rent_roll_date"]
    qs = {}
    for u in occ:
        e = max(u["lease_end"], rd)
        k = (e.year, (e.month - 1) // 3 + 1)
        qs[k] = qs.get(k, 0) + (u["annual_rent_aed"] or 0)
    rows = [["Lease expiries by quarter", "AED p.a.", "Share"]] + [[f"Q{k[1]} {k[0]}", f"{v:,}", pct(v / tot_r, 1)] for k, v in sorted(qs.items())[:6]]
    t = Table(rows, colWidths=[46 * mm, 24 * mm, 18 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 7.2), ("FONT", (0, 0), (-1, 0), FB, 7.2), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    st += [t, Spacer(1, 2 * mm)]
    floors = sorted({u["floor"] for u in b["units"]})
    rows = [["Floor", "Units", "Let", "Contract rent AED"]]
    for fl in floors:
        us = [u for u in b["units"] if u["floor"] == fl]
        let = [u for u in us if u["status"] in OCC_LIKE]
        rows.append(["Ground" if fl == 0 else str(fl), str(len(us)), str(len(let)), f"{sum(u['annual_rent_aed'] or 0 for u in let):,}"])
    t = Table(rows, colWidths=[20 * mm, 16 * mm, 16 * mm, 36 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 7.2), ("FONT", (0, 0), (-1, 0), FB, 7.2), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.5, TEAL), ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    st += [Paragraph("Floor-by-floor summary (from the rent roll)", ParagraphStyle("fs", parent=s_b, fontName=FB)), t, Spacer(1, 2 * mm)]
    # ---- specification and title
    st.append(Paragraph("SPECIFICATION AND CONDITION", s_h))
    st.append(Paragraph(esc(
        f"Reinforced concrete frame with block infill and painted render facades. Apartments have porcelain floor tiles, "
        f"fitted kitchens with built-in hobs and hoods, and en-suite bathrooms in larger units. Common areas comprise an "
        f"air-conditioned lobby, {b['lifts']} passenger lifts, a gymnasium and a roof-level water tank enclosure. Fire life "
        f"safety systems are maintained under an annual contract with a Civil Defence approved contractor. The building "
        f"was inspected in September 2026 and is in fair condition commensurate with its age; facade repainting and lift "
        f"modernisation should be budgeted within the next five years."), s_b))
    st.append(Paragraph("TITLE, PLANNING AND LEGAL", s_h))
    st.append(Paragraph(esc(
        f"The property is held on a single freehold title deed issued by the Dubai Land Department for plot "
        f"{b['plot_number']}. A Building Completion Certificate was issued on completion. The sale will be documented by "
        f"a sale and purchase agreement and registered at a DLD trustee office; transfer fees are payable by the "
        f"purchaser in line with market practice. Purchasers should verify the affection plan, title deed, completion "
        f"certificate and the absence of mortgages or caveats."), s_b))
    # ---- 6 market
    st.append(Paragraph("6. MARKET COMMENTARY", s_h))
    st.append(Paragraph(esc(
        "Dubai residential rents eased through 2026 after four years of strong growth, with prime and newly supplied "
        "communities seeing the largest falls. Affordable and mid-market locations with an established tenant base have "
        "been more resilient. New supply remains elevated, and landlords have offered more flexible payment terms, "
        "including additional cheques, to retain tenants. Renewal increases are governed by the RERA Smart Rental Index."), s_b))
    # ---- 7 risks
    st.append(Paragraph("7. CONSIDERATIONS", s_h))
    st.append(Paragraph(esc(
        "Key considerations include the pace of new supply in the wider area, renewal pricing in a softer rental market, "
        "the age-related maintenance profile of the building and the cost of district cooling or plant where applicable. "
        "Prospective purchasers should review the Ejari register, DEWA accounts and service contracts."), s_b))
    # ---- 8 process
    st.append(Paragraph("8. PROCESS AND CONTACTS", s_h))
    st.append(Paragraph(esc(f"Offers are invited on a subject-to-contract basis. A data room is available on request. "
                            f"{br['name']}, {br['orn']}, {br['address']}, T {br['phone']}, {br['web']}."), s_b))
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(esc(f"{nm}, {role} ({brn}) - {mob} - {em}"), s_b))
    st.append(Paragraph(esc("Disclaimer: information has been provided by the Seller and has not been verified. It does not "
                            "constitute an offer or form part of any contract."), s_sm))
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": None}


# =========================================================================== Tessellate (tables as images)
def _table_png(rows, col_mm, *, header=True, font_pt=8.5, dpi=200, zebra=True, accent=(40, 40, 40)):
    reg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", int(font_pt * dpi / 72))
    bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(font_pt * dpi / 72))
    px = [int(w / 25.4 * dpi) for w in col_mm]
    rh = int(font_pt * 2.1 * dpi / 72)
    W_, H_ = sum(px), rh * len(rows)
    img = PILImage.new("RGB", (W_, H_), "white")
    d = ImageDraw.Draw(img)
    for i, row in enumerate(rows):
        y = i * rh
        if header and i == 0:
            d.rectangle([0, y, W_, y + rh], fill=(236, 236, 232))
        elif zebra and i % 2 == 0:
            d.rectangle([0, y, W_, y + rh], fill=(250, 250, 248))
        x = 0
        for j, cell in enumerate(row):
            f = bold if (header and i == 0) or j == 0 else reg
            txt = str(cell)
            tw = d.textlength(txt, font=f)
            tx = x + 12 if j == 0 else x + px[j] - tw - 12
            d.text((tx, y + rh * 0.22), txt, fill=accent if j == 0 else (20, 20, 20), font=f)
            x += px[j]
        d.line([0, y + rh - 1, W_, y + rh - 1], fill=(210, 210, 205), width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return Image(buf, width=sum(col_mm) * mm, height=H_ / dpi * 25.4 * mm)


def build_tessellate(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["tessellate"]
    W, H = A4
    INK, MUTE, ACC = colors.HexColor("#202020"), colors.HexColor("#9A9A9A"), colors.HexColor("#C2502B")
    F, FB = "DejaVu", "DejaVu-Bold"
    s_big = ParagraphStyle("big", fontName=F, fontSize=26, leading=30, textColor=MUTE, spaceAfter=6 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=9, leading=13.5, textColor=INK, spaceAfter=3 * mm)
    s_sm = ParagraphStyle("s", fontName=F, fontSize=7, leading=9.5, textColor=MUTE)
    yl = om["yield"]
    asset_v, asset_t = asset_info(b)
    month = ctx["om_date"].strftime("%B %Y")

    def cover(c, d):
        c.saveState()
        c.setFillColor(colors.HexColor("#F4F2EE"))
        c.rect(0, 0, W, H, stroke=0, fill=1)
        draw_elevation(c, 20 * mm, H * 0.42, W - 40 * mm, H * 0.40, b,
                       (colors.HexColor("#E8E4DC"), colors.HexColor("#F7F5F1"), colors.HexColor("#D9D2C5"),
                        colors.HexColor("#6B6F73"), colors.HexColor("#FFFFFF")), spec["seed"])
        c.setFillColor(ACC)
        c.rect(20 * mm, H * 0.42 - 6 * mm, 8 * mm, 2 * mm, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(FB, 30)
        c.drawString(20 * mm, H * 0.42 - 22 * mm, o.rec("building_name", b["name"], b["name"]))
        c.setFont(F, 12)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(20 * mm, H * 0.42 - 32 * mm, f"{location_name(b)}   /   {month}")
        c.setFont(FB, 9)
        c.setFillColor(INK)
        c.drawString(20 * mm, 30 * mm, "TESSELLATE")
        c.setFont(F, 7)
        c.setFillColor(MUTE)
        c.drawString(20 * mm, 25 * mm, f"{br['division']}  /  {br['orn']}  /  {br['confidential']}")
        c.drawCentredString(W / 2, 8 * mm, FOOTER)
        c.restoreState()

    def page(c, d):
        c.saveState()
        c.setFillColor(MUTE)
        c.setFont(F, 7)
        c.drawString(20 * mm, H - 12 * mm, f"TESSELLATE   /   {b['name']}")
        c.drawRightString(W - 20 * mm, H - 12 * mm, f"{d.page:02d}")
        c.drawCentredString(W / 2, 8 * mm, FOOTER)
        c.restoreState()

    doc = BaseDocTemplate(str(path), pagesize=A4, title=f"{b['name']}", author=br["name"], invariant=1)
    doc.addPageTemplates([PageTemplate(id="cover", frames=[Frame(0, 0, W, H, id="cv")], onPage=cover),
                          PageTemplate(id="body", frames=[Frame(20 * mm, 18 * mm, W - 40 * mm, H - 38 * mm, id="bd",
                                                                leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                                       onPage=page)])
    st = [NextPageTemplate("body"), PageBreak()]

    def img_rec(field, value, quote, page, **extra):
        o.fields[field] = {"value": value, "quote": quote, "page": page, "in_image": True, **extra}
        return quote

    # ---- p2 summary
    st.append(Paragraph("Summary", s_big))
    st.append(Paragraph(esc(f"{b['name']} is a {b['floors']} {asset_t.lower()} of {om['unit_count']} units in {b['sub_community']}, "
                            f"completed in {b['completion_year']}. It is offered freehold, subject to the existing tenancies, "
                            "on behalf of a private owner."), s_b))
    rows = [["", ""],
            ["Asking price", img_rec("asking_price_aed", om["asking_price_aed"], aed(om["asking_price_aed"]), 2)],
            ["Passing rent (rent roll)", img_rec("annual_rent_stated", om["annual_rent"]["value"], aed(om["annual_rent"]["value"]), 2,
                                                 basis=om["annual_rent"]["basis"])],
            ["Occupancy", img_rec("occupancy_stated", om["occupancy"]["value"], pct(om["occupancy"]["value"], 1), 2, as_of=om["occupancy"]["as_of"])],
            ["Net operating income", aed(om["noi_stated_aed"])],
            ["Purchaser's costs", aed(om["purchaser_costs_aed"])],
            ["Net initial yield", img_rec("yield_stated", yl["value"], pct(yl["value"], 2), 2, basis={"measure": "net", "on": "total_cost"})]]
    rows[0] = ["Key figures", ""]
    st += [_table_png(rows, [100, 60]), Spacer(1, 4 * mm),
           Paragraph(esc("Net initial yield is net operating income divided by the asking price plus purchaser's costs "
                         "(DLD 4%, agency 2% plus VAT, registration)."), s_sm), PageBreak()]
    # ---- p3 property
    st.append(Paragraph("The building", s_big))
    title_q = "Freehold, single title"
    rows = [["Property", ""],
            ["Plot", img_rec("plot_number", b["plot_number"], b["plot_number"], 3)],
            ["Asset", img_rec("asset_type", asset_v, asset_t, 3)],
            ["Community", img_rec("area", b["area"], b["sub_community"], 3)],
            ["Tenure", img_rec("title_type", om["title_type"], title_q, 3)],
            ["Configuration", img_rec("floors", b["floors"], b["floors"], 3)],
            ["Completed", img_rec("completion_year", b["completion_year"], str(b["completion_year"]), 3)],
            ["BUA (sq ft)", img_rec("bua_sqft", om["bua_sqft"], f"{om['bua_sqft']:,}", 3)],
            ["NSA (sq ft)", img_rec("nsa_sqft", om["nsa_sqft"], f"{om['nsa_sqft']:,}", 3, original={"value": om["nsa_sqft"], "unit": "sq ft"})],
            ["Units", img_rec("unit_count", om["unit_count"], str(om["unit_count"]), 3)],
            ["Parking", img_rec("parking_spaces", b["parking_spaces"], str(b["parking_spaces"]), 3)],
            ["Cooling", img_rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "mid"), 3)],
            ["Leases", img_rec("lease_structure", om["lease_structure"], "Direct, Ejari registered", 3)],
            ["Price per sq ft NSA", img_rec("price_psf", om["price_psf"], f"AED {om['price_psf']['value']:,}", 3)]]
    st += [_table_png(rows, [70, 90]), PageBreak()]
    # ---- p4 accommodation
    st.append(Paragraph("Accommodation", s_big))
    rows = [["Type", "Units", "Avg sq ft", "Avg rent AED"]]
    for t_, n, lo, hi_, avg, rent in mix_rows(ctx, om):
        rows.append([UNIT_LABELS[t_], n, f"{avg:,.0f}", f"{rent:,.0f}" if rent else "-"])
    rows.append(["Total", om["unit_count"], "", ""])
    first = mix_rows(ctx, om)[0]
    img_rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[first[0]]} {first[1]}", 4)
    st += [_table_png(rows, [55, 30, 35, 40]), Spacer(1, 6 * mm),
           Paragraph(esc("Unit mix and average rents from the rent roll. Leases are generally twelve months, paid by "
                         "post-dated cheques."), s_b), PageBreak()]
    # ---- p5 income and costs
    st.append(Paragraph("Income and costs", s_big))
    stmt = ctx["stmt_truth"]
    rows = [["AED", ""], ["Passing rent", f"{om['annual_rent']['value']:,}"], ["Other income", f"{om['other_income_stated_aed']:,}"],
            ["Operating costs", f"({om['opex_stated_aed']:,})"], ["Net operating income", f"{om['noi_stated_aed']:,}"],
            ["Asking price", f"{om['asking_price_aed']:,}"], ["Purchaser's costs", f"{om['purchaser_costs_aed']:,}"],
            ["Net initial yield", pct(yl["value"], 2)]]
    img_rec("opex_stated_aed", om["opex_stated_aed"], f"({om['opex_stated_aed']:,})", 5, period=stmt["title"])
    st += [_table_png(rows, [100, 60]), Spacer(1, 4 * mm),
           Paragraph(esc(f"Operating costs per the owner's {stmt['title']}. Before vacancy and collection allowances."), s_sm), PageBreak()]
    # ---- p6 location and contacts
    loc = LOCATION[b["loc_key"]]
    st += [Paragraph("Location", s_big), Paragraph(esc(loc["intro"]), s_b),
           location_plan(loc, W - 40 * mm, 70 * mm, ACC, font=F, fontb=FB, seed=spec["seed"]), Spacer(1, 8 * mm)]
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(esc(f"{nm}  /  {role}  /  {brn}  /  {mob}  /  {em}"), s_b))
    st.append(Paragraph(esc(f"{br['name']}  /  {br['address']}  /  {br['phone']}  /  {br['web']}"), s_sm))
    st.append(Paragraph(esc("Information supplied by the vendor and not verified by Tessellate. Not an offer or contract."), s_sm))
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": None}
