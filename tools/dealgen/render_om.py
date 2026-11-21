"""Broker offering memoranda. Five fictional brokerages, each with its own look and vocabulary.

Every rendered OM field is recorded with the exact text drawn (`quote`); after the build the page
of each quote is found in the PDF text, so truth.json citations are correct by construction.
"""
from __future__ import annotations

import html
import random
from datetime import date

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from .analysis import OCC_LIKE
from .refdata import BROKERS, FOOTER, LOCATION, UNIT_LABELS

_FONTS_DONE = False


def _fonts():
    global _FONTS_DONE
    if _FONTS_DONE:
        return
    base = "/usr/share/fonts/truetype/"
    for name, f in [("DejaVu", "dejavu/DejaVuSans.ttf"), ("DejaVu-Bold", "dejavu/DejaVuSans-Bold.ttf"),
                    ("Arial", "liberation/LiberationSans-Regular.ttf"), ("Arial-Bold", "liberation/LiberationSans-Bold.ttf"),
                    ("Narrow", "liberation/LiberationSansNarrow-Regular.ttf"), ("Narrow-Bold", "liberation/LiberationSansNarrow-Bold.ttf")]:
        pdfmetrics.registerFont(TTFont(name, base + f))
    _FONTS_DONE = True


def aed(x):
    return f"AED {x:,.0f}"


def aedm(x, dp=2):
    return f"AED {x / 1e6:,.{dp}f} Million"


def pct(x, dp=1):
    return f"{x * 100:.{dp}f}%"


def esc(s):
    return html.escape(str(s), quote=False)


ASSET = {True: ("mixed_use_ground_floor_retail", "Residential building with ground-floor retail"),
         False: ("residential_building", "Residential building")}


class OM:
    def __init__(self, ctx):
        self.ctx = ctx
        self.fields = {}

    def rec(self, field, value, quote, **extra):
        self.fields[field] = {"value": value, "quote": quote, **extra}
        return quote


# --------------------------------------------------------------------------- cover illustration
def draw_elevation(c, x, y, w, h, b, palette, seed):
    rng = random.Random(seed)
    sky_top, sky_bot, facade, glass, frame = palette
    # sky
    steps = 30
    for i in range(steps):
        t = i / (steps - 1)
        col = colors.Color(sky_bot.red + (sky_top.red - sky_bot.red) * t, sky_bot.green + (sky_top.green - sky_bot.green) * t,
                           sky_bot.blue + (sky_top.blue - sky_bot.blue) * t)
        c.setFillColor(col)
        c.rect(x, y + h * i / steps, w, h / steps + 0.5, stroke=0, fill=1)
    floors = b["residential_floors"]
    lbl = b["floors"]
    pod = 1 + lbl.count("P") + (int(lbl.split("+")[1][0]) - 1 if "P" in lbl.split("+")[1] and lbl.split("+")[1][0].isdigit() else 0)
    pod = min(pod, 5)
    total = floors + pod
    bw = w * (0.42 if floors >= 10 else 0.62)
    bx = x + (w - bw) / 2
    fh = min((h * 0.86) / total, 16)
    by = y + 4
    # ground
    c.setFillColor(colors.HexColor("#B9B3A6"))
    c.rect(x, y, w, 6, stroke=0, fill=1)
    # podium
    c.setFillColor(facade.clone(alpha=1) if hasattr(facade, "clone") else facade)
    c.setFillColor(colors.Color(facade.red * 0.85, facade.green * 0.85, facade.blue * 0.85))
    c.rect(bx - 8, by, bw + 16, fh * pod, stroke=0, fill=1)
    # podium openings
    c.setFillColor(colors.Color(0.25, 0.27, 0.3))
    for k in range(pod):
        for s in range(6):
            c.rect(bx - 4 + s * (bw + 8) / 6 + 3, by + k * fh + fh * 0.3, (bw + 8) / 6 - 6, fh * 0.45, stroke=0, fill=1)
    # shopfronts on ground floor
    c.setFillColor(glass)
    for s in range(5):
        c.rect(bx - 4 + s * (bw + 8) / 5 + 2, by + 1, (bw + 8) / 5 - 4, fh * 0.75, stroke=0, fill=1)
    # tower
    ty = by + fh * pod
    c.setFillColor(facade)
    c.rect(bx, ty, bw, fh * floors, stroke=0, fill=1)
    cols_ = 8 if floors >= 10 else 10
    cw = bw / cols_
    for f in range(floors):
        for k in range(cols_):
            lit = rng.random()
            c.setFillColor(colors.Color(glass.red + 0.12 * lit, glass.green + 0.12 * lit, glass.blue + 0.08 * lit))
            c.rect(bx + k * cw + cw * 0.14, ty + f * fh + fh * 0.18, cw * 0.72, fh * 0.62, stroke=0, fill=1)
        c.setFillColor(frame)
        c.rect(bx - 1.5, ty + f * fh, bw + 3, 1.2, stroke=0, fill=1)  # balcony slab
    c.setFillColor(frame)
    c.rect(bx - 3, ty + fh * floors, bw + 6, 3.5, stroke=0, fill=1)  # parapet
    # trees
    for tx in (x + 12, x + w - 26, bx - 22, bx + bw + 8):
        c.setFillColor(colors.HexColor("#5B7F4A"))
        c.circle(tx + 7, y + 18, 9, stroke=0, fill=1)
        c.setFillColor(colors.HexColor("#5A4632"))
        c.rect(tx + 6, y + 5, 2, 6, stroke=0, fill=1)


class Elevation(Flowable):
    """Illustrative building frontage used where a broker would place a photograph."""

    def __init__(self, b, w, h, palette, seed, caption, font="Helvetica", cap_color=colors.HexColor("#666666")):
        super().__init__()
        self.b, self.w, self.h, self.palette, self.seed, self.caption = b, w, h, palette, seed, caption
        self.font, self.cap_color = font, cap_color

    def wrap(self, aw, ah):
        return self.w, self.h + 12

    def draw(self):
        c = self.canv
        draw_elevation(c, 0, 12, self.w, self.h, self.b, self.palette, self.seed + 7)
        c.setFont(self.font, 7)
        c.setFillColor(self.cap_color)
        c.drawString(0, 2, self.caption)


def location_plan(loc, w, h, accent, font="Helvetica", fontb="Helvetica-Bold", seed=0):
    """Schematic location plan: two named arterial roads, nearby landmarks, subject pin. Not to scale."""
    rng = random.Random(seed)
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor("#EEF0EC"), strokeColor=colors.HexColor("#C8CCC4"), strokeWidth=0.6))
    for i in range(1, 9):
        x = w * i / 9 + rng.uniform(-8, 8)
        d.add(Line(x, 0, x + rng.uniform(-20, 20), h, strokeColor=colors.white, strokeWidth=2.2))
    for i in range(1, 5):
        y = h * i / 5 + rng.uniform(-6, 6)
        d.add(Line(0, y, w, y + rng.uniform(-12, 12), strokeColor=colors.white, strokeWidth=2.2))
    roads = [a for a, _ in loc["access"] if "Road" in a][:2]
    d.add(Line(0, h * 0.22, w, h * 0.30, strokeColor=colors.HexColor("#F2C14E"), strokeWidth=7))
    d.add(Line(w * 0.18, 0, w * 0.30, h, strokeColor=colors.HexColor("#F2C14E"), strokeWidth=7))
    if roads:
        d.add(String(w * 0.62, h * 0.22 - 2, roads[0], fontName=fontb, fontSize=7, fillColor=colors.HexColor("#5A4A10")))
    if len(roads) > 1:
        d.add(String(w * 0.31, h * 0.90, roads[1], fontName=fontb, fontSize=7, fillColor=colors.HexColor("#5A4A10")))
    marks = [a for a, _ in loc["access"] if "Road" not in a][:3]
    pos = [(w * 0.72, h * 0.70), (w * 0.08, h * 0.55), (w * 0.82, h * 0.42)]
    for (x, y), m in zip(pos, marks):
        d.add(Circle(x, y, 3.2, fillColor=colors.HexColor("#7A8A99"), strokeColor=None))
        d.add(String(x + 5, y - 2.5, m + " \u2192" if x > w * 0.7 else m, fontName=font, fontSize=6.8, fillColor=colors.HexColor("#333333")))
    px, py = w * 0.50, h * 0.55
    d.add(Circle(px, py, 7, fillColor=accent, strokeColor=colors.white, strokeWidth=1.5))
    d.add(String(px + 10, py - 3, "Subject property", fontName=fontb, fontSize=7.5, fillColor=accent))
    d.add(String(4, 4, "Location plan - schematic, not to scale", fontName=font, fontSize=6.5, fillColor=colors.HexColor("#666666")))
    return d


# --------------------------------------------------------------------------- shared content
def asset_info(b):
    return ASSET["retail" in b["unit_mix"]]


def location_name(b):
    return {"JVC": "Jumeirah Village Circle (JVC), Dubai", "Dubai Silicon Oasis": "Dubai Silicon Oasis (DSO), Dubai",
            "International City": "International City, Dubai", "Business Bay": "Business Bay, Dubai",
            "Al Barsha South": "Arjan, Al Barsha South, Dubai", "Al Barsha 1": "Al Barsha 1, Dubai",
            "Dubai Sports City": "Dubai Sports City, Dubai"}[b["area"]]


def chiller_text(b, style):
    ch = b["chiller_arrangement"]
    if ch == "landlord_district":
        return {"formal": "Chiller-free: district cooling paid by the landlord", "punchy": "CHILLER FREE",
                "plain": "Chiller free", "mid": "Chiller free (district cooling included in rent)"}[style]
    if ch == "landlord_plant":
        return {"formal": "Chiller-free: central A/C plant operated by the landlord", "punchy": "CHILLER FREE (CENTRAL A/C)",
                "plain": "Chiller free (central AC)", "mid": "Chiller free - central A/C"}[style]
    if ch == "tenant_district":
        return {"formal": "District cooling, tenants contract directly with the provider", "punchy": "TENANT PAYS CHILLER",
                "plain": "Chiller paid by tenant", "mid": "District cooling - paid by tenants"}[style]
    return {"formal": "Split / package A/C units on tenants' DEWA accounts", "punchy": "A/C ON TENANT DEWA",
            "plain": "Split AC - DEWA by tenant", "mid": "Split A/C (tenant DEWA)"}[style]


def mix_rows(ctx, om, with_rent=True):
    b = ctx["b"]
    rows = []
    for t in ["studio", "1br", "2br", "3br", "retail"]:
        if t not in om["unit_mix"]:
            continue
        us = [u for u in b["units"] if u["type"] == t]
        sizes = [u["area_sqft"] for u in us]
        occ = [u for u in us if u["status"] in OCC_LIKE]
        avg_rent = sum(u["annual_rent_aed"] for u in occ) / len(occ) if occ else None
        rows.append((t, om["unit_mix"][t], min(sizes), max(sizes), sum(sizes) / len(sizes), avg_rent))
    return rows


def upside_text(om):
    up = om["_upside"]
    if not up:
        return None
    if up["kind"] == "compliant":
        return (f"Reversion: {up['units_more_than_20pct_below_index']} tenancies are let more than 20% below the RERA Smart "
                f"Rental Index reference and are eligible for increases of 5-10% at renewal, subject to 90 days' notice. "
                f"No uplift has been assumed in the pricing.")
    return (f"Reversionary potential: passing rents sit c.{round(up['comparables_gap_claimed'] * 100)}% below asking rents for "
            f"comparable new lettings in the community. As leases renew and re-let through 2027, we expect gross income to "
            f"rise by c.AED {up['claimed_uplift_aed'] / 1e6:.2f}m (+{round(up['claimed_uplift_pct'] * 100)}%) within 12 months.")


def nsa_label(broker):
    return {"harbour_crest": "Net saleable area (NSA)", "marwah_stone": "Net leasable area", "dunecrest": "SALEABLE AREA",
            "meridian_gate": "Saleable area", "saffron_key": "Total saleable area"}[broker]


# --------------------------------------------------------------------------- document assembly
def build_om(path, ctx):
    _fonts()
    om = ctx["om"]
    broker = ctx["spec"]["broker"]
    from .render_om2 import build_qamar, build_tessellate
    builder = {"harbour_crest": _harbour, "marwah_stone": _marwah, "dunecrest": _dunecrest, "meridian_gate": _meridian,
               "saffron_key": _saffron, "qamar": build_qamar, "tessellate": build_tessellate}[broker]
    o = OM(ctx)
    builder(path, ctx, o)
    return o.fields


def _doc(path, pagesize, cover_fn, page_fn, margins, title, author):
    doc = BaseDocTemplate(str(path), pagesize=pagesize, leftMargin=margins[0], rightMargin=margins[1], topMargin=margins[2],
                          bottomMargin=margins[3], title=title, author=author, invariant=1)
    W, H = pagesize
    frame_cover = Frame(0, 0, W, H, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame = Frame(margins[0], margins[3], W - margins[0] - margins[1], H - margins[2] - margins[3], id="body",
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame_cover], onPage=cover_fn),
                          PageTemplate(id="body", frames=[frame], onPage=page_fn)])
    return doc


def _kv_table(rows, widths, font, bold, size, label_color, line_color, zebra=None):
    t = Table([[Paragraph(esc(a), ParagraphStyle("l", fontName=bold, fontSize=size, leading=size * 1.25, textColor=label_color)),
                Paragraph(esc(v), ParagraphStyle("v", fontName=font, fontSize=size, leading=size * 1.25))] for a, v in rows],
              colWidths=widths)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, line_color),
          ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2)]
    if zebra:
        for i in range(0, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), zebra))
    t.setStyle(TableStyle(st))
    return t


def _footer(c, W, color=colors.grey, font="Helvetica", y=7 * mm):
    c.setFont(font, 6.8)
    c.setFillColor(color)
    c.drawCentredString(W / 2, y, FOOTER)


# =========================================================================== Harbour & Crest
def _harbour(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["harbour_crest"]
    W, H = A4
    NAVY, TEAL, GREY = colors.HexColor("#1F3A5F"), colors.HexColor("#2A9D8F"), colors.HexColor("#5F6B7A")
    F, FB = "Helvetica", "Helvetica-Bold"
    s_h = ParagraphStyle("h", fontName=FB, fontSize=17, leading=21, textColor=NAVY, spaceAfter=3 * mm)
    s_k = ParagraphStyle("k", fontName=FB, fontSize=8, leading=10, textColor=TEAL, spaceAfter=1 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=9.6, leading=13.4, textColor=colors.HexColor("#222222"), spaceAfter=2.6 * mm)
    s_sm = ParagraphStyle("s", fontName=F, fontSize=7.6, leading=10, textColor=GREY)
    s_bul = ParagraphStyle("bu", parent=s_b, leftIndent=10, bulletIndent=0, spaceAfter=1.6 * mm)
    month = ctx["om_date"].strftime("%B %Y")

    def cover(c, d):
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        draw_elevation(c, 0, H * 0.36, W, H * 0.46, b,
                       (colors.HexColor("#9CC3E0"), colors.HexColor("#E9F0F5"), colors.HexColor("#E6DFD3"),
                        colors.HexColor("#5C7A93"), colors.HexColor("#FFFFFF")), spec["seed"])
        c.setFillColor(colors.white)
        c.setFont(FB, 11)
        c.drawString(18 * mm, H - 16 * mm, "HARBOUR & CREST")
        c.setFont(F, 7.5)
        c.drawString(18 * mm, H - 20.5 * mm, br["division"].upper())
        c.setFillColor(TEAL)
        c.rect(18 * mm, H * 0.36 - 12 * mm, 22 * mm, 1.6 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(F, 10)
        c.drawString(18 * mm, H * 0.36 - 22 * mm, "INVESTMENT OPPORTUNITY")
        c.setFont(FB, 28)
        c.drawString(18 * mm, H * 0.36 - 35 * mm, o.rec("building_name", b["name"], b["name"]))
        c.setFont(F, 12)
        c.drawString(18 * mm, H * 0.36 - 44 * mm, location_name(b))
        c.setFont(F, 9.5)
        c.drawString(18 * mm, H * 0.36 - 54 * mm, f"Freehold residential building  |  {b['unit_count']} units  |  Offering Memorandum, {month}")
        c.setFont(F, 7)
        c.setFillColor(colors.HexColor("#C9D3DD"))
        c.drawString(18 * mm, 18 * mm, br["confidential"])
        c.drawString(18 * mm, 14 * mm, "Image: illustrative elevation, not to scale.")
        _footer(c, W, colors.HexColor("#C9D3DD"))
        c.restoreState()

    def page(c, d):
        c.saveState()
        c.setFillColor(NAVY)
        c.rect(0, H - 12 * mm, W, 12 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 8)
        c.drawString(18 * mm, H - 7.6 * mm, "HARBOUR & CREST")
        c.setFont(F, 8)
        c.drawRightString(W - 18 * mm, H - 7.6 * mm, f"{b['name']}  |  Offering Memorandum  |  {d.page}")
        c.setFillColor(GREY)
        c.setFont(F, 6.8)
        c.drawString(18 * mm, 11 * mm, br["confidential"])
        _footer(c, W)
        c.restoreState()

    doc = _doc(path, A4, cover, page, (18 * mm, 18 * mm, 22 * mm, 20 * mm), f"{b['name']} - Offering Memorandum", br["name"])
    st = [NextPageTemplate("body"), PageBreak()]
    asset_v, asset_t = asset_info(b)
    yl = om["yield"]
    # ---- 01 executive summary
    st += [Paragraph("01  EXECUTIVE SUMMARY", s_k), Paragraph("The opportunity", s_h)]
    st.append(Paragraph(esc(
        f"Harbour & Crest is instructed by the Owner to seek offers for the freehold interest in {b['name']}, a "
        f"{b['floors']} {asset_t.lower()} of {om['unit_count']} units in {location_name(b).replace(', Dubai', '')}, "
        f"completed in {b['completion_year']}. The building is held on a single title and let on direct tenancies registered with Ejari."), s_b))
    hi = [
        o.rec("occupancy_stated", om["occupancy"]["value"],
              f"Occupancy of {pct(om['occupancy']['value'])} by units as at {om['occupancy']['as_of']}", as_of=om["occupancy"]["as_of"]),
        o.rec("annual_rent_stated", om["annual_rent"]["value"],
              f"Passing rent of {aed(om['annual_rent']['value'])} per annum (in-place)", basis=om["annual_rent"]["basis"]),
        o.rec("yield_stated", yl["value"], f"Net initial yield of {pct(yl['value'], 2)} after purchaser's costs",
              basis={"measure": "net", "on": "total_cost"}),
        o.rec("asking_price_aed", om["asking_price_aed"], f"Guide price {aed(om['asking_price_aed'])}"),
    ]
    for h in hi:
        st.append(Paragraph(esc(h), s_bul, bulletText="•"))
    st.append(Spacer(1, 3 * mm))
    st.append(Paragraph(esc("The asset offers an investor a stabilised, granular income stream in an established rental "
                            "location, with professional third-party management in place and a full operating history."), s_b))
    up = upside_text(om)
    if up:
        st.append(Paragraph(esc(o.rec("upside_claims", [up], up)), s_b))
    st.append(PageBreak())
    # ---- 02 property
    st += [Paragraph("02  THE PROPERTY", s_k), Paragraph("Property overview", s_h)]
    rows = [
        ("Building", b["name"]),
        ("Asset type", o.rec("asset_type", asset_v, asset_t)),
        ("Location", o.rec("area", b["area"], location_name(b))),
        ("Plot number", o.rec("plot_number", b["plot_number"], b["plot_number"])),
        ("Title", o.rec("title_type", om["title_type"], "Freehold, single title deed (whole building)")),
        ("Configuration", o.rec("floors", b["floors"], b["floors"])),
        ("Completion", o.rec("completion_year", b["completion_year"], f"{b['completion_year']} (DM completion certificate available)")),
        ("Plot area", f"{b['plot_area_sqft']:,} sq ft"),
        ("Built-up area (BUA)", o.rec("bua_sqft", om["bua_sqft"], f"{om['bua_sqft']:,} sq ft")),
        (nsa_label("harbour_crest"), o.rec("nsa_sqft", om["nsa_sqft"], f"{om['nsa_sqft']:,} sq ft", original={"value": om["nsa_sqft"], "unit": "sq ft"})),
        ("Units", o.rec("unit_count", om["unit_count"], f"{om['unit_count']} units")),
        ("Parking", o.rec("parking_spaces", b["parking_spaces"], f"{b['parking_spaces']} covered spaces")),
        ("Lifts", f"{b['lifts']} passenger lifts"),
        ("Cooling", o.rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "formal"))),
        ("Tenancy", o.rec("lease_structure", om["lease_structure"], "Direct tenancies, registered with Ejari")),
    ]
    st.append(_kv_table(rows, [52 * mm, 122 * mm], F, FB, 9.2, NAVY, colors.HexColor("#D5DCE3"), colors.HexColor("#F3F6F8")))
    st.append(Spacer(1, 4 * mm))
    st.append(Paragraph(esc(f"Efficiency (NSA / BUA) is {om['nsa_sqft'] / om['bua_sqft'] * 100:.0f}%; BUA includes podium parking, "
                            "plant and common areas. Areas are taken from the Owner's records and should be verified against the title deed and affection plan."), s_sm))
    st.append(Spacer(1, 5 * mm))
    st.append(Elevation(b, 174 * mm, 72 * mm, (colors.HexColor("#9CC3E0"), colors.HexColor("#E9F0F5"), colors.HexColor("#E6DFD3"),
                                               colors.HexColor("#5C7A93"), colors.HexColor("#FFFFFF")), spec["seed"],
                        "Building frontage (illustrative)."))
    st.append(PageBreak())
    # ---- 03 location
    loc = LOCATION[b["loc_key"]]
    st += [Paragraph("03  LOCATION", s_k), Paragraph(esc(location_name(b).replace(", Dubai", "")), s_h),
           Paragraph(esc(loc["intro"]), s_b), Paragraph(esc(f"The building is located in {b['sub_community']}."), s_b), Spacer(1, 3 * mm)]
    t = Table([["Destination", "Drive time"]] + [list(x) for x in loc["access"]], colWidths=[110 * mm, 40 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), FB, 9), ("FONT", (0, 1), (-1, -1), F, 9),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#D5DCE3")), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    st += [t, Spacer(1, 2 * mm), Paragraph("Drive times are indicative, outside peak hours.", s_sm), Spacer(1, 6 * mm),
           location_plan(loc, 174 * mm, 88 * mm, TEAL, seed=spec["seed"]), PageBreak()]
    # ---- 04 accommodation & tenancy
    st += [Paragraph("04  ACCOMMODATION AND TENANCY", s_k), Paragraph("Unit mix", s_h)]
    data = [["Unit type", "Units", "Size range (sq ft)", "Average size (sq ft)", "Average passing rent (AED p.a.)"]]
    mix = mix_rows(ctx, om)
    for t_, n, lo, hi_, avg, rent in mix:
        data.append([UNIT_LABELS[t_], str(n), f"{lo:,.0f} - {hi_:,.0f}", f"{avg:,.0f}", f"{rent:,.0f}" if rent else "-"])
    data.append(["Total", str(om["unit_count"]), "", "", ""])
    o.rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[mix[0][0]]} {mix[0][1]}")
    data[0] = [Paragraph(f"<font color='white'><b>{h}</b></font>", ParagraphStyle("th", fontName=FB, fontSize=8.2, leading=10, alignment=2 if i else 0))
               for i, h in enumerate(data[0])]
    t = Table(data, colWidths=[34 * mm, 18 * mm, 38 * mm, 38 * mm, 46 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), FB, 8.6), ("FONT", (0, 1), (-1, -1), F, 9),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                           ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("FONT", (0, -1), (-1, -1), FB, 9),
                           ("LINEABOVE", (0, -1), (-1, -1), 0.8, NAVY), ("LINEBELOW", (0, 1), (-1, -2), 0.4, colors.HexColor("#D5DCE3")),
                           ("TOPPADDING", (0, 0), (-1, -1), 3.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.2), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    st += [t, Spacer(1, 6 * mm), Paragraph("Lease expiry profile (share of passing rent by quarter)", ParagraphStyle("hh", parent=s_b, fontName=FB, textColor=NAVY))]
    # expiry chart by quarter
    occ = [u for u in b["units"] if u["status"] in OCC_LIKE]
    tot = sum(u["annual_rent_aed"] for u in occ)
    qs = {}
    rd = b["rent_roll_date"]
    for u in occ:
        e = max(u["lease_end"], rd)
        key = f"Q{(e.month - 1) // 3 + 1} {e.year % 100:02d}"
        qs[(e.year, (e.month - 1) // 3)] = qs.get((e.year, (e.month - 1) // 3), 0) + u["annual_rent_aed"]
    keys = sorted(qs)[:6]
    dr = Drawing(170 * mm, 52 * mm)
    bc = VerticalBarChart()
    bc.x, bc.y, bc.width, bc.height = 12 * mm, 8 * mm, 150 * mm, 38 * mm
    bc.data = [[qs[k] / tot * 100 for k in keys]]
    bc.categoryAxis.categoryNames = [f"Q{k[1] + 1} {k[0]}" for k in keys]
    bc.categoryAxis.labels.fontName = F
    bc.categoryAxis.labels.fontSize = 7.5
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max(60, int(max(bc.data[0]) / 10 + 1) * 10)
    bc.valueAxis.valueStep = 10
    bc.valueAxis.labels.fontName = F
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labelTextFormat = "%d%%"
    bc.bars[0].fillColor = TEAL
    bc.bars[0].strokeColor = None
    dr.add(bc)
    st.append(dr)
    n_corp = sum(1 for u in occ if u["tenant_type"] == "company")
    st.append(Paragraph(esc(f"{len(occ)} tenancies, {n_corp} to corporate tenants. Leases are typically 12 months, renewing annually; "
                            f"rents are paid by post-dated cheques (1-12 per year)."), s_b))
    st.append(PageBreak())
    # ---- 05 income and costs
    st += [Paragraph("05  INCOME AND OPERATING COSTS", s_k), Paragraph("Financial summary", s_h)]
    stmt = ctx["stmt_truth"]
    per = stmt["period"]
    per_txt = ("FY2026 (annualised)" if per["annualised"] else f"T-12 to {date.fromisoformat(per['end']).strftime('%b %Y')}")
    rows = [
        ("Passing rent (in-place, per rent roll)", aed(om["annual_rent"]["value"])),
        ("Other income (parking, fees)", aed(om["other_income_stated_aed"])),
        (f"Operating expenses ({per_txt})", f"({aed(om['opex_stated_aed'])})"),
        ("Net operating income", aed(om["noi_stated_aed"])),
        ("Guide price", aed(om["asking_price_aed"])),
        (f"Purchaser's costs ({om['purchaser_costs_pct'] * 100:.1f}%: DLD 4%, agency 2% + VAT, registration)", aed(om["purchaser_costs_aed"])),
        ("Total acquisition cost", aed(om["asking_price_aed"] + om["purchaser_costs_aed"])),
        ("Net initial yield", pct(yl["value"], 2)),
    ]
    o.fields["opex_stated_aed"] = {"value": om["opex_stated_aed"], "quote": f"({aed(om['opex_stated_aed'])})", "period": per_txt}
    tt = Table([[Paragraph(esc(a), ParagraphStyle("x", fontName=FB if i in (3, 7) else F, fontSize=9.4, leading=12)), v]
                for i, (a, v) in enumerate(rows)], colWidths=[120 * mm, 54 * mm])
    tt.setStyle(TableStyle([("FONT", (1, 0), (1, -1), F, 9.4), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("FONT", (1, 3), (1, 3), FB, 9.4), ("FONT", (1, 7), (1, 7), FB, 10.5),
                            ("LINEABOVE", (0, 3), (-1, 3), 0.8, NAVY), ("LINEABOVE", (0, 7), (-1, 7), 0.8, NAVY),
                            ("BACKGROUND", (0, 7), (-1, 7), colors.HexColor("#E8F4F2")),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#D5DCE3")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3.4), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.4), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    st += [tt, Spacer(1, 4 * mm)]
    st.append(Paragraph(esc(f"Operating expenses are taken from the Owner's {spec['stmt']['title']} and include facilities management, "
                            "utilities for common areas, insurance, management, community charges and a reserve contribution. "
                            "No allowance has been made for vacancy or collection loss."), s_sm))
    st.append(Spacer(1, 3 * mm))
    st.append(Paragraph(esc(f"Price per sq ft: AED {om['price_psf']['value']:,} on NSA."), s_b))
    o.rec("price_psf", om["price_psf"], f"AED {om['price_psf']['value']:,} on NSA")
    st.append(PageBreak())
    # ---- 06 process & contacts
    st += [Paragraph("06  PROCESS AND CONTACTS", s_k), Paragraph("Offers and contacts", s_h),
           Paragraph(esc(f"Offers are invited for the freehold interest at a guide price of {aed(om['asking_price_aed'])}, "
                         "subject to contract. The sale is of the property; a share sale of the owning entity may be considered. "
                         "A data room containing the rent roll, operating statements, title deed, completion certificate and "
                         "Ejari register is available on signing of a non-disclosure agreement."), s_b), Spacer(1, 4 * mm)]
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(f"<b>{esc(nm)}</b><br/>{esc(role)} | {brn}<br/>M {mob}<br/>{esc(em)}", s_b))
    st.append(Spacer(1, 6 * mm))
    st.append(Paragraph(esc(f"{br['name']} | {br['orn']} | {br['address']} | T {br['phone']} | {br['web']}"), s_sm))
    st.append(Spacer(1, 3 * mm))
    st.append(Paragraph(esc("Disclaimer: this memorandum is provided for information only and does not constitute an offer or contract. "
                            "Information is supplied by the Owner and has not been independently verified. Prospective purchasers "
                            "must satisfy themselves by inspection and their own due diligence."), s_sm))
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": br["name"]}


# =========================================================================== Marwah & Stone
def _marwah(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["marwah_stone"]
    W, H = A4
    GREEN, GOLD, CREAM = colors.HexColor("#1E3D33"), colors.HexColor("#B08D57"), colors.HexColor("#FBF8F1")
    F, FB, FI = "Times-Roman", "Times-Bold", "Times-Italic"
    s_t = ParagraphStyle("t", fontName=FB, fontSize=19, leading=23, textColor=GREEN, alignment=TA_CENTER, spaceAfter=2 * mm)
    s_sub = ParagraphStyle("su", fontName=FI, fontSize=10.5, leading=13, textColor=GOLD, alignment=TA_CENTER, spaceAfter=6 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=10.6, leading=14.6, spaceAfter=3 * mm)
    s_sm = ParagraphStyle("s", fontName=FI, fontSize=8.4, leading=11, textColor=colors.HexColor("#555555"))
    month = ctx["om_date"].strftime("%B %Y")
    non_free = b["tenure"] == "non_freehold"
    sq_m = non_free  # older Al Barsha 1 building: areas quoted from title deed in sq m

    def bg(c):
        c.setFillColor(CREAM)
        c.rect(0, 0, W, H, stroke=0, fill=1)

    def cover(c, d):
        c.saveState()
        bg(c)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1.2)
        c.rect(12 * mm, 12 * mm, W - 24 * mm, H - 24 * mm, stroke=1, fill=0)
        c.setLineWidth(0.4)
        c.rect(14 * mm, 14 * mm, W - 28 * mm, H - 28 * mm, stroke=1, fill=0)
        c.setFillColor(GREEN)
        c.setFont(FB, 15)
        c.drawCentredString(W / 2, H - 34 * mm, "MARWAH & STONE")
        c.setFont(F, 8.5)
        c.setFillColor(GOLD)
        c.drawCentredString(W / 2, H - 40 * mm, "C A P I T A L   ·   I N V E S T M E N T   S A L E S")
        draw_elevation(c, 34 * mm, H * 0.40, W - 68 * mm, H * 0.36, b,
                       (colors.HexColor("#D9E4E1"), colors.HexColor("#F6F1E6"), colors.HexColor("#D8CCB4"),
                        colors.HexColor("#6E8279"), colors.HexColor("#F7F4EC")), spec["seed"])
        c.setFillColor(GREEN)
        c.setFont(FI, 12)
        c.drawCentredString(W / 2, H * 0.40 - 16 * mm, "Confidential Information Memorandum")
        c.setFont(FB, 26)
        c.drawCentredString(W / 2, H * 0.40 - 30 * mm, o.rec("building_name", b["name"], b["name"]))
        c.setFont(F, 12)
        c.drawCentredString(W / 2, H * 0.40 - 39 * mm, location_name(b))
        c.setFont(F, 10)
        c.drawCentredString(W / 2, H * 0.40 - 48 * mm, month)
        c.setFont(FI, 7.8)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawCentredString(W / 2, 22 * mm, br["confidential"])
        _footer(c, W, font="Times-Roman", y=17 * mm)
        c.restoreState()

    def page(c, d):
        c.saveState()
        bg(c)
        c.setStrokeColor(GOLD)
        c.setLineWidth(0.6)
        c.line(20 * mm, H - 16 * mm, W - 20 * mm, H - 16 * mm)
        c.setFillColor(GREEN)
        c.setFont(FB, 8.5)
        c.drawString(20 * mm, H - 13.5 * mm, "MARWAH & STONE")
        c.setFont(FI, 8.5)
        c.drawRightString(W - 20 * mm, H - 13.5 * mm, b["name"])
        c.line(20 * mm, 14 * mm, W - 20 * mm, 14 * mm)
        c.setFont(F, 8)
        c.drawCentredString(W / 2, 10.5 * mm, f"- {d.page} -")
        _footer(c, W, font="Times-Roman", y=6.5 * mm)
        c.restoreState()

    doc = _doc(path, A4, cover, page, (22 * mm, 22 * mm, 26 * mm, 22 * mm), f"{b['name']} - Information Memorandum", br["name"])
    st = [NextPageTemplate("body"), PageBreak()]
    asset_v, asset_t = asset_info(b)
    # ---- the investment
    st += [Paragraph("The Investment", s_t), Paragraph("A summary of the offer", s_sub)]
    occ_txt = (f"{pct(om['occupancy']['value'], 0)} occupied (as at {om['occupancy']['as_of']})")
    st.append(Paragraph(esc(f"Marwah & Stone Capital has been retained to sell {b['name']}, a {asset_t.lower()} in "
                            f"{location_name(b).replace(', Dubai', '')} completed in {b['completion_year']}. The building comprises "
                            f"{om['unit_count']} units over {b['floors']} and is offered with the benefit of its existing tenancies."), s_b))
    rows = [
        ("Occupancy", o.rec("occupancy_stated", om["occupancy"]["value"], occ_txt, as_of=om["occupancy"]["as_of"])),
        ("Gross rental income", o.rec("annual_rent_stated", om["annual_rent"]["value"], f"{aed(om['annual_rent']['value'])} per annum (contracted)",
                                      basis=om["annual_rent"]["basis"])),
        ("Asking price", o.rec("asking_price_aed", om["asking_price_aed"], aed(om["asking_price_aed"]))),
        ("Net yield on total acquisition cost", o.rec("yield_stated", om["yield"]["value"], pct(om["yield"]["value"], 2),
                                                      basis={"measure": "net", "on": "total_cost"})),
    ]
    st.append(_kv_table(rows, [70 * mm, 96 * mm], F, FB, 10.5, GREEN, GOLD))
    st.append(Spacer(1, 5 * mm))
    if spec.get("motivated"):
        st.append(Paragraph(esc("The Owner is rebalancing a private portfolio and is seeking a prompt sale. The building has been "
                                "priced accordingly, below recent unit-level values in the community, for a transaction capable of "
                                "completing within 60 days."), s_b))
    st.append(Paragraph(esc("Key attributes: established location with good road access; granular tenant base of individuals and "
                            "companies; twelve months of operating history, rent roll and Ejari register available to bidders."), s_b))
    st.append(PageBreak())
    # ---- the property
    st += [Paragraph("The Property", s_t), Paragraph("Description and specification", s_sub)]
    if sq_m:
        bua_q = f"{om['bua_sqft'] / 10.7639:,.0f} sq m"
        nsa_q = f"{om['nsa_sqft'] / 10.7639:,.0f} sq m"
        plot_q = f"{b['plot_area_sqft'] / 10.7639:,.0f} sq m"
        o.rec("bua_sqft", round(round(om["bua_sqft"] / 10.7639) * 10.7639), bua_q, original={"value": round(om["bua_sqft"] / 10.7639), "unit": "sq m"})
        o.rec("nsa_sqft", round(round(om["nsa_sqft"] / 10.7639) * 10.7639), nsa_q, original={"value": round(om["nsa_sqft"] / 10.7639), "unit": "sq m"})
    else:
        bua_q, nsa_q, plot_q = f"{om['bua_sqft']:,} sq ft", f"{om['nsa_sqft']:,} sq ft", f"{b['plot_area_sqft']:,} sq ft"
        o.rec("bua_sqft", om["bua_sqft"], bua_q, original={"value": om["bua_sqft"], "unit": "sq ft"})
        o.rec("nsa_sqft", om["nsa_sqft"], nsa_q, original={"value": om["nsa_sqft"], "unit": "sq ft"})
    title_q = ("Title deed in the name of the Seller (land and building)" if non_free
               else "Freehold - one title deed for the entire building")
    rows = [
        ("Asset type", o.rec("asset_type", asset_v, asset_t)),
        ("Address", o.rec("area", b["area"], f"{b['sub_community']}, Dubai")),
        ("Plot no.", o.rec("plot_number", b["plot_number"], b["plot_number"])),
        ("Tenure", o.rec("title_type", om["title_type"], title_q)),
        ("Floors", o.rec("floors", b["floors"], b["floors"])),
        ("Year of completion", o.rec("completion_year", b["completion_year"], str(b["completion_year"]))),
        ("Plot area", plot_q),
        ("Built-up area", bua_q),
        (nsa_label("marwah_stone"), nsa_q),
        ("Number of units", o.rec("unit_count", om["unit_count"], str(om["unit_count"]))),
        ("Car parking", o.rec("parking_spaces", b["parking_spaces"], f"{b['parking_spaces']} spaces (basement and surface)")),
        ("Air conditioning", o.rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "formal"))),
        ("Leases", o.rec("lease_structure", om["lease_structure"], "Individual tenancy contracts, Ejari registered")),
    ]
    st.append(_kv_table(rows, [58 * mm, 108 * mm], F, FB, 10.2, GREEN, GOLD))
    if sq_m:
        st.append(Spacer(1, 3 * mm))
        st.append(Paragraph(esc("Areas are quoted as shown on the title deed and affection plan (square metres)."), s_sm))
    st.append(Spacer(1, 6 * mm))
    st.append(Elevation(b, 166 * mm, 70 * mm, (colors.HexColor("#D9E4E1"), colors.HexColor("#F6F1E6"), colors.HexColor("#D8CCB4"),
                                               colors.HexColor("#6E8279"), colors.HexColor("#F7F4EC")), spec["seed"],
                        "The building (illustrative).", font="Times-Italic"))
    st.append(PageBreak())
    # ---- location
    loc = LOCATION[b["loc_key"]]
    intro = loc["intro"]
    st += [Paragraph("Location", s_t), Paragraph(esc(location_name(b)), s_sub), Paragraph(esc(intro), s_b)]
    if non_free:
        st.append(Paragraph(esc("Al Barsha 1 is an established, largely owner-built district of mid-rise residential buildings and villas "
                                "close to Mall of the Emirates, with strong demand from families and hotel and retail staff."), s_b))
    rows = [(a, v) for a, v in loc["access"]]
    st.append(_kv_table(rows, [110 * mm, 40 * mm], F, F, 10, colors.black, GOLD))
    st.append(Spacer(1, 8 * mm))
    st.append(location_plan(loc, 166 * mm, 86 * mm, GREEN, font="Times-Roman", fontb="Times-Bold", seed=spec["seed"]))
    st.append(PageBreak())
    # ---- accommodation and income
    st += [Paragraph("Accommodation and Income", s_t), Paragraph("Unit mix and operating summary", s_sub)]
    data = [["Type", "Units", "Avg. size (sq ft)", "Avg. rent (AED)"]]
    mix = mix_rows(ctx, om)
    for t_, n, lo, hi_, avg, rent in mix:
        data.append([UNIT_LABELS[t_], str(n), f"{avg:,.0f}", f"{rent:,.0f}" if rent else "-"])
    data.append(["Total", str(om["unit_count"]), "", ""])
    o.rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[mix[0][0]]} {mix[0][1]}")
    t = Table(data, colWidths=[46 * mm, 26 * mm, 42 * mm, 42 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), FB, 10), ("FONT", (0, 1), (-1, -1), F, 10), ("FONT", (0, -1), (-1, -1), FB, 10),
                           ("LINEBELOW", (0, 0), (-1, 0), 0.8, GOLD), ("LINEABOVE", (0, -1), (-1, -1), 0.8, GOLD),
                           ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    st += [t, Spacer(1, 6 * mm)]
    stmt = ctx["stmt_truth"]
    rows = [
        ("Contracted rent", aed(om["annual_rent"]["value"])),
        ("Other income", aed(om["other_income_stated_aed"])),
        ("Operating expenses (last 12 months)", f"({aed(om['opex_stated_aed'])})"),
        ("Net operating income", aed(om["noi_stated_aed"])),
        ("Asking price", aed(om["asking_price_aed"])),
        ("Acquisition costs (DLD 4%, brokerage 2% + VAT, fees)", aed(om["purchaser_costs_aed"])),
        ("Net yield on total acquisition cost", pct(om["yield"]["value"], 2)),
    ]
    o.fields["opex_stated_aed"] = {"value": om["opex_stated_aed"], "quote": f"({aed(om['opex_stated_aed'])})", "period": "last 12 months"}
    st.append(_kv_table(rows, [108 * mm, 50 * mm], F, F, 10.2, colors.black, GOLD))
    st.append(Spacer(1, 3 * mm))
    st.append(Paragraph(esc(f"Price per sq ft of net leasable area: AED {om['price_psf']['value']:,}."), s_b))
    o.rec("price_psf", om["price_psf"], f"AED {om['price_psf']['value']:,}")
    st.append(Paragraph(esc(f"Source: Owner's {stmt['title'].lower()} and rent roll. Figures before vacancy and collection allowances."), s_sm))
    st.append(PageBreak())
    # ---- terms
    st += [Paragraph("Terms of Sale", s_t), Paragraph("Process and contacts", s_sub),
           Paragraph(esc(f"Offers are invited at {aed(om['asking_price_aed'])} for the land and building, subject to contract and "
                         "satisfactory due diligence. Security deposits held will be transferred to the purchaser on completion."), s_b)]
    if non_free:
        st.append(Paragraph(esc("Transfer is subject to the purchaser meeting Dubai Land Department ownership eligibility for the plot. "
                                "Purchasers should take their own legal advice on eligibility before making an offer."), s_b))
    st.append(Spacer(1, 4 * mm))
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(f"<b>{esc(nm)}</b>, {esc(role)} ({brn})<br/>{mob} | {esc(em)}", s_b))
    st.append(Spacer(1, 4 * mm))
    st.append(Paragraph(esc(f"{br['name']} | {br['orn']} | {br['address']} | {br['phone']}"), s_sm))
    st.append(Paragraph(esc("This memorandum does not form part of any offer or contract. All information is believed to be correct "
                            "but is not guaranteed; interested parties should rely on their own inspection and enquiries."), s_sm))
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": br["name"]}


# =========================================================================== Dunecrest (landscape deck)
def _dunecrest(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["dunecrest"]
    W, H = landscape(A4)
    BLACK, GOLD = colors.HexColor("#111111"), colors.HexColor("#C9A227")
    F, FB = "Helvetica", "Helvetica-Bold"
    s_h = ParagraphStyle("h", fontName=FB, fontSize=22, leading=26, textColor=BLACK, spaceAfter=5 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=10.5, leading=14.5, spaceAfter=2.5 * mm)
    s_sm = ParagraphStyle("s", fontName=F, fontSize=7.4, leading=9.5, textColor=colors.HexColor("#666666"))
    master = b["master_lease"]
    strata = b["title"] == "strata"
    month = ctx["om_date"].strftime("%B %Y").upper()

    def cover(c, d):
        c.saveState()
        c.setFillColor(BLACK)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        draw_elevation(c, W * 0.52, 18 * mm, W * 0.44, H - 36 * mm, b,
                       (colors.HexColor("#3A3F4B"), colors.HexColor("#C98E5A"), colors.HexColor("#E8E2D6"),
                        colors.HexColor("#33475B"), colors.HexColor("#FFFFFF")), spec["seed"])
        c.setFillColor(GOLD)
        c.setFont(FB, 20)
        c.drawString(18 * mm, H - 26 * mm, "DUNECREST")
        c.setFont(F, 8)
        c.drawString(18 * mm, H - 31 * mm, "REAL ESTATE BROKERS")
        c.setFillColor(colors.white)
        c.setFont(F, 12)
        c.drawString(18 * mm, H * 0.58, "EXCLUSIVE INVESTMENT OPPORTUNITY")
        c.setFont(FB, 34)
        c.drawString(18 * mm, H * 0.58 - 15 * mm, o.rec("building_name", b["name"], b["name"].upper()).upper())
        c.setFont(F, 13)
        c.drawString(18 * mm, H * 0.58 - 25 * mm, location_name(b).upper())
        c.setFillColor(GOLD)
        c.rect(18 * mm, H * 0.58 - 32 * mm, 40 * mm, 1.4 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 13)
        tag = ("GUARANTEED INCOME  |  5-YEAR MASTER LEASE" if master else
               f"{om['unit_count']} UNITS  |  {'FULLY TENANTED' if om['occupancy']['value'] >= 0.95 else 'TENANTED'}  |  {b['floors']}")
        c.drawString(18 * mm, H * 0.58 - 44 * mm, tag)
        c.setFont(F, 7.5)
        c.setFillColor(colors.HexColor("#AAAAAA"))
        c.drawString(18 * mm, 18 * mm, br["confidential"])
        c.drawString(18 * mm, 14 * mm, month)
        _footer(c, W, colors.HexColor("#AAAAAA"))
        c.restoreState()

    def page(c, d):
        c.saveState()
        c.setFillColor(BLACK)
        c.rect(0, 0, 12 * mm, H, stroke=0, fill=1)
        c.setFillColor(GOLD)
        c.rect(12 * mm, 0, 1.2 * mm, H, stroke=0, fill=1)
        c.setFont(FB, 8)
        c.drawRightString(W - 14 * mm, H - 11 * mm, "DUNECREST")
        c.setFillColor(colors.HexColor("#888888"))
        c.setFont(F, 7.5)
        c.drawRightString(W - 14 * mm, 12 * mm, f"{b['name'].upper()}  |  {d.page}")
        _footer(c, W)
        c.restoreState()

    doc = _doc(path, landscape(A4), cover, page, (26 * mm, 16 * mm, 18 * mm, 20 * mm), f"{b['name']} - Investment Opportunity", br["name"])
    st = [NextPageTemplate("body"), PageBreak()]
    asset_v, asset_t = asset_info(b)

    def tile(label, value, sub=""):
        return [Paragraph(esc(label), ParagraphStyle("tl", fontName=F, fontSize=8.5, textColor=colors.HexColor("#777777"), leading=11)),
                Paragraph(esc(value), ParagraphStyle("tv", fontName=FB, fontSize=17, leading=21, textColor=BLACK)),
                Paragraph(esc(sub), ParagraphStyle("ts", fontName=F, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#777777")))]

    # ---- highlights
    st.append(Paragraph("INVESTMENT HIGHLIGHTS", s_h))
    yl = om["yield"]
    occ_q = ("100% LEASED" if master else f"{round(om['occupancy']['value'] * 100)}% OCCUPIED")
    rent_lbl = "MASTER LEASE RENT" if master else "ANNUAL RENTAL INCOME"
    rent_q = aedm(om["annual_rent"]["value"])
    tiles = [
        tile("ASKING PRICE", o.rec("asking_price_aed", om["asking_price_aed"], aedm(om["asking_price_aed"], 1)), "Negotiable for serious buyers"),
        tile(rent_lbl, o.rec("annual_rent_stated", om["annual_rent"]["value"], rent_q, basis=om["annual_rent"]["basis"]),
             "Fixed, no vacancy risk" if master else "Annual"),
        tile(yl["label"].upper(), o.rec("yield_stated", yl["value"], pct(yl["value"], 2), basis={"measure": "gross", "on": "asking_price"}),
             "On asking price"),
        tile("OCCUPANCY", o.rec("occupancy_stated", om["occupancy"]["value"], occ_q, as_of=None), "Master lease" if master else ""),
    ]
    t = Table([tiles], colWidths=[60 * mm] * 4)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, GOLD), ("INNERGRID", (0, 0), (-1, -1), 0.6, GOLD),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                           ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
    st += [t, Spacer(1, 8 * mm)]
    bullets = []
    if master:
        bullets += ["Entire building let to an experienced operator on a 5-year master lease - hands-free, guaranteed income",
                    "No vacancy, no collection risk, no management headaches",
                    "Tenant responsible for FM, utilities, cleaning and security"]
    elif strata:
        bullets += [f"Rare opportunity to acquire an entire Business Bay tower - all {b['unit_count']} units under one owner",
                    "Walking distance to Business Bay Metro and Dubai Canal", "Strong rental demand from Downtown and DIFC professionals",
                    "Individual title deeds allow flexible exit - sell in bulk or unit by unit"]
    else:
        short = location_name(b).replace(", Dubai", "")
        bullets += [f"{'Brand new' if b['completion_year'] >= 2023 else 'Well maintained'} {b['floors']} building, "
                    f"completed {b['completion_year']}, high specification",
                    f"{short} - one of Dubai's most in-demand rental communities", "Strong tenant profile, mostly 1 and 2 bedroom units"]
        if "retail" in b["unit_mix"]:
            bullets.append(f"{b['unit_mix']['retail']} ground-floor retail units serving the building and neighbourhood")
    for x in bullets:
        st.append(Paragraph(esc(x), ParagraphStyle("bl", parent=s_b, leftIndent=10, fontSize=11.5, leading=16), bulletText="■"))
    st.append(PageBreak())
    # ---- property details
    st.append(Paragraph("PROPERTY DETAILS", s_h))
    title_q = ("FREEHOLD - SINGLE TITLE DEED" if not strata else f"FREEHOLD - {b['unit_count']} TITLE DEEDS, SINGLE OWNER")
    left = [
        ("Building", b["name"]), ("Type", o.rec("asset_type", asset_v, asset_t)),
        ("Location", o.rec("area", b["area"], location_name(b))), ("Plot No.", o.rec("plot_number", b["plot_number"], b["plot_number"])),
        ("Title", o.rec("title_type", om["title_type"], title_q)), ("Floors", o.rec("floors", b["floors"], b["floors"])),
        ("Completion", o.rec("completion_year", b["completion_year"], str(b["completion_year"]))),
    ]
    right = [
        ("Total units", o.rec("unit_count", om["unit_count"], str(om["unit_count"]))),
        ("BUA", o.rec("bua_sqft", om["bua_sqft"], f"{om['bua_sqft']:,} sq.ft")),
        (nsa_label("dunecrest").title(), o.rec("nsa_sqft", om["nsa_sqft"], f"{om['nsa_sqft']:,} sq.ft", original={"value": om["nsa_sqft"], "unit": "sq ft"})),
        ("Parking", o.rec("parking_spaces", b["parking_spaces"], f"{b['parking_spaces']} bays")),
        ("A/C", o.rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "punchy"))),
        ("Price / sq.ft", o.rec("price_psf", om["price_psf"], f"AED {om['price_psf']['value']:,} (on BUA)")),
        ("Leases", o.rec("lease_structure", om["lease_structure"],
                         f"Master lease - {master['tenant']}" if master else "Direct with tenants (Ejari)")),
    ]
    if master:
        left.append(("Seller", o.rec("seller", b["seller"], f"{b['seller']} (Silverline Group)")))
        right.append(("Master tenant", o.rec("master_tenant_group", master["tenant"], f"{master['tenant']} (Silverline Group)")))
    kv = lambda rows: _kv_table(rows, [36 * mm, 82 * mm], F, FB, 10, colors.HexColor("#555555"), colors.HexColor("#DDDDDD"))
    t = Table([[kv(left), kv(right)]], colWidths=[124 * mm, 124 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    st.append(t)
    if strata:
        st.append(Spacer(1, 4 * mm))
        st.append(Paragraph(esc("Building managed by a RERA-registered owners association; service charges paid through Mollak."), s_sm))
    st.append(PageBreak())
    # ---- unit mix / income
    st.append(Paragraph("UNIT MIX & INCOME", s_h))
    data = [["UNIT TYPE", "NO. OF UNITS", "SIZE (SQ.FT)", "AVG. RENT (AED)"]]
    mix = mix_rows(ctx, om)
    for t_, n, lo, hi_, avg, rent in mix:
        data.append([UNIT_LABELS[t_].upper(), str(n), f"{lo:,.0f} - {hi_:,.0f}", f"{rent:,.0f}" if rent else "-"])
    data.append(["TOTAL", str(om["unit_count"]), "", ""])
    o.rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[mix[0][0]].upper()} {mix[0][1]}")
    t = Table(data, colWidths=[60 * mm, 40 * mm, 50 * mm, 50 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), FB, 9.5), ("TEXTCOLOR", (0, 0), (-1, 0), GOLD), ("BACKGROUND", (0, 0), (-1, 0), BLACK),
                           ("FONT", (0, 1), (-1, -1), F, 10.5), ("FONT", (0, -1), (-1, -1), FB, 10.5), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#DDDDDD")), ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5)]))
    st += [t, Spacer(1, 7 * mm)]
    fin = [["ANNUAL RENTAL INCOME" if not master else "MASTER LEASE RENT (FIXED)", rent_q],
           [yl["label"].upper(), pct(yl["value"], 2)], ["ASKING PRICE", aedm(om["asking_price_aed"], 1)]]
    if master:
        fin.insert(1, ["LEASE EXPIRY", date.fromisoformat(master["end"]).strftime("%B %Y")])
    t = Table(fin, colWidths=[90 * mm, 70 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (0, -1), FB, 11), ("FONT", (1, 0), (1, -1), FB, 13), ("TEXTCOLOR", (1, 0), (1, -1), BLACK),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.6, GOLD), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    st.append(t)
    if master:
        st.append(Spacer(1, 4 * mm))
        st.append(Paragraph(esc(f"Master tenant: {master['tenant']}, the building's operator since handover and, like the Seller, a "
                                "Silverline Group company. The rent is fixed and payable quarterly in advance with no escalation. "
                                "The operator sub-lets the apartments and pays all running costs (FM, utilities, cleaning, "
                                "security and leasing), so the owner's income is unaffected by vacancy."), s_sm))
    st.append(PageBreak())
    # ---- location
    loc = LOCATION[b["loc_key"]]
    st += [Paragraph("LOCATION", s_h), Paragraph(esc(loc["intro"]), s_b), Spacer(1, 3 * mm)]
    t = Table([[a.upper(), v] for a, v in loc["access"]], colWidths=[82 * mm, 24 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (0, -1), F, 9.5), ("FONT", (1, 0), (1, -1), FB, 9.5), ("LINEBELOW", (0, 0), (-1, -1), 0.4, GOLD),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    lay = Table([[t, location_plan(loc, 130 * mm, 82 * mm, GOLD, seed=spec["seed"])]], colWidths=[112 * mm, 136 * mm])
    lay.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    st += [lay, PageBreak()]
    # ---- contact
    st.append(Paragraph("CONTACT US", s_h))
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(f"<b>{esc(nm.upper())}</b><br/>{esc(role)}  |  {brn}<br/>Mobile / WhatsApp: {mob}<br/>{esc(em)}",
                            ParagraphStyle("c", parent=s_b, fontSize=12, leading=17)))
    st += [Spacer(1, 6 * mm), Paragraph(esc(f"{br['name']}  |  {br['orn']}  |  {br['address']}  |  {br['phone']}"), s_b), Spacer(1, 8 * mm),
           Paragraph(esc("All information is provided by the owner and is believed to be accurate but is not guaranteed. ROI is calculated "
                         "on annual rental income and asking price. Buyer to carry out own due diligence. Prices subject to change."), s_sm)]
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": br["name"]}


# =========================================================================== Meridian Gate
def _meridian(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["meridian_gate"]
    W, H = A4
    MAROON, GREY, LIGHT = colors.HexColor("#7B1E2B"), colors.HexColor("#4D4D4D"), colors.HexColor("#F2ECEC")
    F, FB = "DejaVu", "DejaVu-Bold"
    s_h = ParagraphStyle("h", fontName=FB, fontSize=15, leading=19, textColor=MAROON, spaceAfter=4 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=9.2, leading=13.2, textColor=GREY, spaceAfter=2.4 * mm)
    s_sm = ParagraphStyle("s", fontName=F, fontSize=7, leading=9.2, textColor=colors.HexColor("#777777"))
    month = ctx["om_date"].strftime("%B %Y")
    yl = om["yield"]

    def cover(c, d):
        c.saveState()
        c.setFillColor(colors.white)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        draw_elevation(c, 0, H * 0.30, W, H * 0.58, b,
                       (colors.HexColor("#A9C6DE"), colors.HexColor("#F4EDE4"), colors.HexColor("#DCD6CF"),
                        colors.HexColor("#3E5A70"), colors.HexColor("#FFFFFF")), spec["seed"])
        c.setFillColor(MAROON)
        c.rect(0, 0, W, H * 0.30, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 26)
        c.drawString(16 * mm, H * 0.30 - 22 * mm, o.rec("building_name", b["name"], b["name"]))
        c.setFont(F, 11.5)
        c.drawString(16 * mm, H * 0.30 - 31 * mm, f"Whole building for sale  |  {location_name(b)}")
        c.setFont(F, 9)
        c.drawString(16 * mm, H * 0.30 - 41 * mm, f"Investment brochure  |  {month}")
        c.setFont(FB, 12)
        c.drawString(16 * mm, 24 * mm, "MERIDIAN GATE PROPERTIES")
        c.setFont(F, 7.2)
        c.drawString(16 * mm, 19 * mm, f"{br['division']}  |  {br['orn']}  |  {br['confidential']}")
        _footer(c, W, colors.HexColor("#E8C9CD"), font=F)
        c.restoreState()

    def page(c, d):
        c.saveState()
        c.setFillColor(MAROON)
        c.rect(0, H - 9 * mm, W, 9 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 7.6)
        c.drawString(16 * mm, H - 6 * mm, "MERIDIAN GATE PROPERTIES")
        c.setFont(F, 7.6)
        c.drawRightString(W - 16 * mm, H - 6 * mm, f"{b['name']}  •  page {d.page}")
        _footer(c, W, font=F)
        c.restoreState()

    doc = _doc(path, A4, cover, page, (16 * mm, 16 * mm, 18 * mm, 18 * mm), f"{b['name']} - Investment Brochure", br["name"])
    st = [NextPageTemplate("body"), PageBreak()]
    asset_v, asset_t = asset_info(b)

    def box(label, value):
        return Table([[Paragraph(esc(label), ParagraphStyle("bl", fontName=F, fontSize=7.8, leading=10, textColor=colors.white))],
                      [Paragraph(esc(value), ParagraphStyle("bv", fontName=FB, fontSize=12.5, leading=15.5, textColor=colors.white))]],
                     colWidths=[57 * mm], style=[("BACKGROUND", (0, 0), (-1, -1), MAROON), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 6)])

    # ---- key facts
    st.append(Paragraph("Key Facts", s_h))
    price_psf_q = (f"AED {om['price_psf']['value']:,}" if not om["price_psf"]["basis_labelled"] else
                   f"AED {om['price_psf']['value']:,} (saleable)")
    boxes = [
        box("Asking price", o.rec("asking_price_aed", om["asking_price_aed"], aed(om["asking_price_aed"]))),
        box(spec.get("om_rent_label", "Annual Rental Income"), o.rec("annual_rent_stated", om["annual_rent"]["value"], aed(om["annual_rent"]["value"]),
                                          basis=om["annual_rent"]["basis"])),
        box(yl["label"], o.rec("yield_stated", yl["value"], pct(yl["value"], 2),
                               basis={"measure": yl["basis"], "on": "asking_price"})),
        box("Occupancy", o.rec("occupancy_stated", om["occupancy"]["value"], pct(om["occupancy"]["value"], 0), as_of=None)),
        box("Total units", o.rec("unit_count", om["unit_count"], str(om["unit_count"]))),
        box("Price per sq ft", o.rec("price_psf", om["price_psf"], price_psf_q)),
    ]
    g = Table([boxes[0:3], boxes[3:6]], colWidths=[59.5 * mm] * 3, rowHeights=[22 * mm, 22 * mm])
    g.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    st += [g, Spacer(1, 5 * mm), Elevation(b, 178 * mm, 64 * mm, (colors.HexColor("#A9C6DE"), colors.HexColor("#F4EDE4"), colors.HexColor("#DCD6CF"),
                                                         colors.HexColor("#3E5A70"), colors.HexColor("#FFFFFF")), spec["seed"],
                                         "Illustrative image", font=F), Spacer(1, 3 * mm), Paragraph("Property Highlights", s_h)]
    hl = [f"{b['floors']} {asset_t.lower()} completed in {b['completion_year']}",
          f"{om['unit_count']} units: " + ", ".join(f"{n} x {UNIT_LABELS[t].lower()}" for t, n in om["unit_mix"].items()),
          (chiller_text(b, "mid") if b["chiller_arrangement"] != "landlord_district" else
           "Chiller free - a strong selling point for tenants in " + b["area"]), f"{b['parking_spaces']} parking spaces, {b['lifts']} lifts",
          "Professionally managed, all tenancies registered on Ejari"]
    for x in hl:
        st.append(Paragraph(esc(x), ParagraphStyle("hl", parent=s_b, leftIndent=10), bulletText="▸"))
    st.append(PageBreak())
    # ---- building information
    st.append(Paragraph("Building Information", s_h))
    rows = [
        ("Building name", b["name"]), ("Property type", o.rec("asset_type", asset_v, asset_t)),
        ("Community", o.rec("area", b["area"], b["sub_community"])), ("Plot number", o.rec("plot_number", b["plot_number"], b["plot_number"])),
        ("Ownership", o.rec("title_type", om["title_type"], "Freehold (single title)")),
        ("Floors", o.rec("floors", b["floors"], b["floors"])),
        ("Completion year", o.rec("completion_year", b["completion_year"], str(b["completion_year"]))),
        ("BUA", o.rec("bua_sqft", om["bua_sqft"], f"{om['bua_sqft']:,} sq ft")),
        (nsa_label("meridian_gate"), o.rec("nsa_sqft", om["nsa_sqft"], f"{om['nsa_sqft']:,} sq ft", original={"value": om["nsa_sqft"], "unit": "sq ft"})),
        ("Parking", o.rec("parking_spaces", b["parking_spaces"], str(b["parking_spaces"]))),
        ("Chiller", o.rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "mid"))),
        ("Tenancy", o.rec("lease_structure", om["lease_structure"], "Direct leases")),
    ]
    st.append(_kv_table(rows, [52 * mm, 126 * mm], F, FB, 9, MAROON, colors.HexColor("#E0D5D6"), LIGHT))
    st.append(Spacer(1, 6 * mm))
    st.append(Paragraph("Unit Mix", s_h))
    data = [["Type", "Units", "Size (sq ft)"]]
    for t_, n in om["unit_mix"].items():
        us = [u["area_sqft"] for u in b["units"] if u["type"] == t_]
        data.append([UNIT_LABELS[t_], str(n), f"{min(us):,.0f} - {max(us):,.0f}"])
    data.append(["Total", str(om["unit_count"]), ""])
    first = next(iter(om["unit_mix"].items()))
    o.rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[first[0]]} {first[1]}")
    t = Table(data, colWidths=[60 * mm, 30 * mm, 50 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), FB, 9), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), MAROON),
                           ("FONT", (0, 1), (-1, -1), F, 9), ("FONT", (0, -1), (-1, -1), FB, 9), ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                           ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
    st.append(t)
    st.append(PageBreak())
    # ---- financials
    st.append(Paragraph("Financial Summary", s_h))
    if yl["basis"] == "net":
        ded = om["opex_stated_aed"]
        rows = [["Annual Rental Income", aed(om["annual_rent"]["value"])], [yl["deduction_label"], f"({aed(ded)})"],
                ["Net Income", aed(om["annual_rent"]["value"] - ded)], ["Asking Price", aed(om["asking_price_aed"])],
                ["Net Yield", pct(yl["value"], 2)]]
        o.fields["opex_stated_aed"] = {"value": ded, "quote": f"({aed(ded)})", "label": yl["deduction_label"]}
    else:
        rows = [[spec.get("om_rent_label", "Annual Rental Income"), aed(om["annual_rent"]["value"])], ["Asking Price", aed(om["asking_price_aed"])],
                ["Gross Yield", pct(yl["value"], 2)]]
    t = Table(rows, colWidths=[110 * mm, 60 * mm])
    t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), F, 10.5), ("FONT", (0, -1), (-1, -1), FB, 11.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")), ("BACKGROUND", (0, -1), (-1, -1), LIGHT),
                           ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    st += [t, Spacer(1, 5 * mm)]
    st.append(Paragraph(esc("Rental income as per the current rent roll. Yield calculated on the asking price."), s_sm))
    up = upside_text(om)
    if up:
        st.append(Spacer(1, 4 * mm))
        st.append(Paragraph("Rental Upside", s_h))
        st.append(Paragraph(esc(o.rec("upside_claims", [up], up)), s_b))
    st.append(Spacer(1, 8 * mm))
    st.append(Paragraph("Location", s_h))
    loc = LOCATION[b["loc_key"]]
    st.append(Paragraph(esc(loc["intro"]), s_b))
    st.append(Paragraph(esc("  •  ".join(f"{a}: {v}" for a, v in loc["access"][:5])), s_sm))
    st.append(PageBreak())
    # ---- contacts
    st.append(Paragraph("For viewings and further information", s_h))
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(f"<b>{esc(nm)}</b> - {esc(role)} ({brn})<br/>Mob: {mob}<br/>Email: {esc(em)}", s_b))
    st += [Spacer(1, 6 * mm), Paragraph(esc(f"{br['name']}  |  {br['address']}  |  Tel {br['phone']}  |  {br['web']}"), s_b), Spacer(1, 4 * mm),
           Paragraph(esc("Disclaimer: The information in this brochure is indicative and has been supplied by the owner. It does not form "
                         "part of any contract. Meridian Gate Properties accepts no liability for any inaccuracy."), s_sm)]
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": br["name"]}


# =========================================================================== Saffron Key (plain)
def _saffron(path, ctx, o):
    b, om, spec = ctx["b"], ctx["om"], ctx["spec"]
    br = BROKERS["saffron_key"]
    W, H = A4
    ORANGE = colors.HexColor("#E07B24")
    F, FB = "Arial", "Arial-Bold"
    s_h = ParagraphStyle("h", fontName=FB, fontSize=13, leading=16, textColor=colors.black, spaceBefore=2 * mm, spaceAfter=3 * mm)
    s_b = ParagraphStyle("b", fontName=F, fontSize=10, leading=14, spaceAfter=2 * mm)
    s_sm = ParagraphStyle("s", fontName=F, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))
    yl = om["yield"]

    def strip(c, d):
        c.setFillColor(ORANGE)
        c.rect(0, H - 14 * mm, W, 14 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont(FB, 12)
        c.drawString(15 * mm, H - 9.2 * mm, "SAFFRON KEY REALTY")
        c.setFont(F, 8)
        c.drawRightString(W - 15 * mm, H - 9.2 * mm, f"{br['orn']}  |  {br['phone']}")

    def cover(c, d):
        c.saveState()
        strip(c, d)
        draw_elevation(c, 15 * mm, H * 0.42, W - 30 * mm, H * 0.40, b,
                       (colors.HexColor("#8DB8DA"), colors.HexColor("#EAF2F8"), colors.HexColor("#E9D9BF"),
                        colors.HexColor("#556E7F"), colors.HexColor("#FFFFFF")), spec["seed"])
        c.setFillColor(colors.black)
        c.setFont(FB, 20)
        c.drawString(15 * mm, H * 0.42 - 14 * mm, f"Building for Sale - {b['sub_community'].split(',')[0]}")
        c.setFont(FB, 15)
        c.setFillColor(ORANGE)
        c.drawString(15 * mm, H * 0.42 - 24 * mm, o.rec("building_name", b["name"], b["name"]))
        c.setFillColor(colors.black)
        c.setFont(F, 11)
        c.drawString(15 * mm, H * 0.42 - 33 * mm, f"{b['sub_community']}, Dubai")
        c.setFont(FB, 13)
        c.drawString(15 * mm, H * 0.42 - 46 * mm, f"Excellent ROI {pct(yl['value'], 1)}  |  {om['unit_count']} units  |  Ready & tenanted")
        if spec.get("motivated"):
            c.setFillColor(colors.HexColor("#C0392B"))
            c.setFont(FB, 12)
            c.drawString(15 * mm, H * 0.42 - 56 * mm, "URGENT SALE - owner relocating, priced below market")
        c.setFont(F, 8)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(15 * mm, 22 * mm, br["confidential"])
        _footer(c, W, font=F)
        c.restoreState()

    def page(c, d):
        c.saveState()
        strip(c, d)
        _footer(c, W, font=F)
        c.setFont(F, 7.5)
        c.drawRightString(W - 15 * mm, 7 * mm, str(d.page))
        c.restoreState()

    doc = _doc(path, A4, cover, page, (15 * mm, 15 * mm, 22 * mm, 16 * mm), f"{b['name']} building for sale", br["name"])
    st = [NextPageTemplate("body"), PageBreak()]
    asset_v, asset_t = asset_info(b)

    def grid(rows, widths):
        t = Table([[Paragraph(esc(a), ParagraphStyle("ga", fontName=FB, fontSize=9.6, leading=12)),
                    Paragraph(esc(v), ParagraphStyle("gv", fontName=F, fontSize=9.6, leading=12))] for a, v in rows], colWidths=widths)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#FBE5D6")),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
        return t

    st.append(Paragraph("Building Details", s_h))
    rows = [
        ("Building Name", b["name"]), ("Property Type", o.rec("asset_type", asset_v, asset_t)),
        ("Location", o.rec("area", b["area"], f"{b['sub_community']}, Dubai")), ("Plot No", o.rec("plot_number", b["plot_number"], b["plot_number"])),
        ("Title", o.rec("title_type", om["title_type"], "Freehold - Single Title Deed")), ("Floors", o.rec("floors", b["floors"], b["floors"])),
        ("Year Built", o.rec("completion_year", b["completion_year"], str(b["completion_year"]))),
        ("Built Up Area", o.rec("bua_sqft", om["bua_sqft"], f"{om['bua_sqft']:,} sq.ft")),
        (nsa_label("saffron_key"), o.rec("nsa_sqft", om["nsa_sqft"], f"{om['nsa_sqft']:,} sq.ft", original={"value": om["nsa_sqft"], "unit": "sq ft"})),
        ("Parking", o.rec("parking_spaces", b["parking_spaces"], f"{b['parking_spaces']} (open parking)")),
        ("AC", o.rec("chiller_arrangement", om["chiller_arrangement"], chiller_text(b, "plain"))),
        ("Total Units", o.rec("unit_count", om["unit_count"], str(om["unit_count"]))),
    ]
    st += [grid(rows, [55 * mm, 125 * mm]), Spacer(1, 5 * mm), Paragraph("Unit Breakdown", s_h)]
    data = [["Type", "Qty", "Size (sq.ft)"]]
    for t_, n in om["unit_mix"].items():
        us = [u["area_sqft"] for u in b["units"] if u["type"] == t_]
        data.append([UNIT_LABELS[t_], str(n), f"{min(us):,.0f} - {max(us):,.0f}"])
    first = next(iter(om["unit_mix"].items()))
    o.rec("unit_mix", om["unit_mix"], f"{UNIT_LABELS[first[0]]} {first[1]}")
    t = Table(data, colWidths=[60 * mm, 30 * mm, 50 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")), ("FONT", (0, 0), (-1, 0), FB, 9.6),
                           ("FONT", (0, 1), (-1, -1), F, 9.6), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FBE5D6")),
                           ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
    st += [t, PageBreak()]
    st.append(Paragraph("Rental Details", s_h))
    occ_q = f"{round(om['occupancy']['value'] * 100)}% occupied"
    rows = [
        ("Total Rent (Yearly)", o.rec("annual_rent_stated", om["annual_rent"]["value"], f"{aed(om['annual_rent']['value'])} per year",
                                      basis=om["annual_rent"]["basis"])),
        ("Occupancy", o.rec("occupancy_stated", om["occupancy"]["value"], occ_q, as_of=None)),
        ("Tenancy", o.rec("lease_structure", om["lease_structure"], "Direct tenants, 1 year contracts with Ejari")),
        ("Payment", "Post-dated cheques, 1 to 12 cheques"),
    ]
    st += [grid(rows, [55 * mm, 125 * mm]), Spacer(1, 5 * mm), Paragraph("Price", s_h)]
    rows = [
        ("Asking Price", o.rec("asking_price_aed", om["asking_price_aed"], f"{aed(om['asking_price_aed'])} (negotiable)")),
        ("ROI", o.rec("yield_stated", yl["value"], pct(yl["value"], 1), basis={"measure": "gross", "on": "asking_price"})),
    ]
    st += [grid(rows, [55 * mm, 125 * mm]), Spacer(1, 3 * mm),
           Paragraph(esc("ROI = total yearly rent / asking price." + (" Owner wants quick transfer, serious offers considered."
                                                                     if spec.get("motivated") else "")), s_sm), Spacer(1, 6 * mm),
           Paragraph("Location", s_h), Paragraph(esc(LOCATION[b["loc_key"]]["intro"]), s_b), PageBreak()]
    st.append(Paragraph("Contact", s_h))
    for nm, role, brn, mob, em in br["contacts"]:
        st.append(Paragraph(f"<b>{esc(nm)}</b> ({esc(role)}, {brn})<br/>Mobile / WhatsApp: {mob}<br/>Email: {esc(em)}", s_b))
    st += [Spacer(1, 3 * mm), Paragraph(esc(f"{br['name']}, {br['address']}. Office: {br['phone']}"), s_b), Spacer(1, 5 * mm),
           Paragraph(esc("Note: All details provided by the owner. Buyer to verify. Commission 2% payable by buyer on transfer."), s_sm)]
    doc.build(st)
    o.fields["broker"] = {"value": br["name"], "quote": br["name"]}
