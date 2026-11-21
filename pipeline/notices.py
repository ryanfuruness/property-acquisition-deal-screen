"""Notices: facts about the package an analyst should know that are not discrepancies (and are not scored).

Stale or inferred rent-roll date, tenant concentration, the statement's year-on-year trend, security deposits
to credit at closing and the cheque profile. Thresholds are in :data:`pipeline.config.NOTICES`. Also the
standard diligence checklist, read from ``pipeline/data/diligence.yaml``.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

import yaml

from . import config
from .rentroll import LET_STATUSES
from .underwriting import trusted

DILIGENCE_PATH = Path(__file__).resolve().parent / "data" / "diligence.yaml"
_LEGAL_SUFFIX = re.compile(r"\b(l\.?\s?l\.?\s?c|llc|fze|fzco|fz-llc|ltd|limited|co|company|est|establishment|"
                           r"trading|general trading)\b\.?", re.I)


def tenant_key(name: str) -> str:
    """Tenant name normalised for grouping: case, punctuation and legal suffixes removed."""
    s = _LEGAL_SUFFIX.sub(" ", name.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def _notice(id_: str, severity: str, text: str, **values) -> dict:
    return {"id": id_, "severity": severity, "text": text, "values": values}


def _aed(x: float) -> str:
    return f"AED {x / 1e6:.1f}m" if abs(x) >= 1e6 else f"AED {x:,.0f}"


def build_notices(rr: dict | None, opex: dict | None, uw: dict | None, mandate: dict) -> list[dict]:
    t = config.NOTICES
    out: list[dict] = []
    screen_date = dt.date.fromisoformat(str(mandate["as_of"]))
    if rr:
        s = rr["summary"]
        src = rr.get("as_of_source") or {}
        if s.get("as_of"):
            as_of = dt.date.fromisoformat(s["as_of"])
            age = (screen_date - as_of).days
            windows = ((uw or {}).get("expiry_windows") or {}).get("windows") or []
            past = [w for w in windows if dt.date.fromisoformat(w["end"]) < screen_date]
            if age > t.stale_rent_roll_days or past:
                out.append(_notice("stale_rent_roll", "warn",
                                   f"The rent roll is dated {as_of:%d %B %Y}, {age} days before the screen date"
                                   + (f"; {len(past)} expiry window(s) have already passed" if past else "")
                                   + ". Ask for a current roll before relying on occupancy and expiries.",
                                   as_of=s["as_of"], age_days=age, windows_past=len(past)))
            if "file name" in (src.get("how") or "") or "month only" in (src.get("how") or ""):
                out.append(_notice("rent_roll_date_inferred", "warn",
                                   f"The rent roll date {as_of:%d %B %Y} is inferred ({src.get('how')}); the roll "
                                   "itself does not state it.", as_of=s["as_of"], how=src.get("how")))
        else:
            out.append(_notice("rent_roll_date_missing", "warn",
                               "The rent roll date is not stated anywhere; expiry windows start at the analysis start."))
        out += _tenant_concentration(rr, t)
        if s.get("deposits_aed"):
            out.append(_notice("security_deposits", "info",
                               f"Tenants' security deposits of {_aed(s['deposits_aed'])} transfer to the buyer and "
                               "must be credited at closing.", deposits_aed=s["deposits_aed"]))
        out += _cheque_profile(rr)
    if opex and opex.get("prior_period"):
        pp = opex["prior_period"]
        if pp.get("noi_aed") and opex.get("noi_aed"):
            change = opex["noi_aed"] / pp["noi_aed"] - 1
            out.append(_notice("statement_trend", "warn" if change < -t.noi_decline else "info",
                               f"Statement NOI moved {change:+.1%} against the prior period ({pp.get('label')}).",
                               noi_aed=opex["noi_aed"], prior_noi_aed=pp["noi_aed"], change=round(change, 4)))
    return out


def _tenant_concentration(rr: dict, t) -> list[dict]:
    let = [u for u in rr["units"] if u["status"] in LET_STATUSES and u.get("tenant")]
    if not let:
        return []
    rent_total = sum(u["annual_rent_aed"] or 0 for u in let)
    groups: dict[str, dict] = defaultdict(lambda: {"units": 0, "rent": 0.0, "names": set()})
    for u in let:
        g = groups[tenant_key(u["tenant"])]
        g["units"] += 1
        g["rent"] += u["annual_rent_aed"] or 0
        g["names"].add(u["tenant"])
    out = []
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]["rent"]):
        unit_share, rent_share = g["units"] / len(let), (g["rent"] / rent_total if rent_total else 0)
        if g["units"] >= 2 and (unit_share >= t.tenant_unit_share or rent_share >= t.tenant_rent_share):
            name = sorted(g["names"])[0]
            out.append(_notice("tenant_concentration", "warn",
                               f"{name} holds {g['units']} units ({unit_share:.0%} of let units, {rent_share:.0%} of "
                               "in-place rent): one tenant's covenant and renewal decision.",
                               tenant=name, units=g["units"], unit_share=round(unit_share, 4),
                               rent_share=round(rent_share, 4)))
    return out


def _cheque_profile(rr: dict) -> list[dict]:
    let = [u for u in rr["units"] if u["status"] in LET_STATUSES and u.get("cheques") and u.get("annual_rent_aed")]
    if not let:
        return []
    total = sum(u["annual_rent_aed"] for u in let)
    buckets = {"1-2 cheques": (1, 2), "3-4 cheques": (3, 4), "6 or more cheques": (5, 99)}
    shares = {k: sum(u["annual_rent_aed"] for u in let if lo <= u["cheques"] <= hi) / total
              for k, (lo, hi) in buckets.items()}
    text = ", ".join(f"{v:.0%} of rent on {k}" for k, v in shares.items() if v)
    return [_notice("cheque_profile", "info", f"Cheque profile: {text}. More cheques mean more collection risk "
                    "and less post-dated cheque cover.", shares={k: round(v, 4) for k, v in shares.items()})]


def diligence_items(om: dict, rr: dict | None, mandate: dict, path: Path = DILIGENCE_PATH) -> list[dict]:
    """The checklist items whose condition holds for this deal."""
    items = yaml.safe_load(path.read_text())["items"]
    year = trusted(om, "completion_year")
    age = int(str(mandate["as_of"])[:4]) - year["value"] if year else None
    title = trusted(om, "title_type")
    title_value = (title or {}).get("value") or {}
    facts = {
        "strata": title_value.get("ownership") == "strata",
        "master_lease": bool((rr or {}).get("master_lease")),
        "title_not_confirmed": title_value != {"tenure": "freehold", "ownership": "single_title"},
        "retail_units": bool(rr and (rr["summary"]["by_type"].get("retail") or {}).get("units")),
    }
    out = []
    for it in items:
        when = it["when"]
        if when == "always":
            ok = True
        elif isinstance(when, dict) and "building_age_at_least" in when:
            ok = age is None or age >= when["building_age_at_least"]
        else:
            ok = facts.get(when, False)
        if ok:
            out.append({"id": it["id"], "text": it["text"]})
    return out
