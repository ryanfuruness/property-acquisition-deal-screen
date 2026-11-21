"""Ground truth per deal, and the engine's answer on the true building.

``expected_verdict`` in truth.json is null by design: the expected verdict and the expected
underwriting numbers are computed here by running the deterministic engine on
``true_building.engine_inputs`` (which carry ``rent_roll_date``) and ``mandate_fit`` on
``true_building.deal_facts``. The scorer never reads expected numbers from the run.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .common import DEALS_DIR

UW_METRICS = ("noi_year1", "going_in_net_yield_on_cost", "levered_irr_pre_tax", "walk_away_price_aed")


def load_truth(deal_id: str, deals_dir: Path = DEALS_DIR) -> dict:
    t = json.loads((deals_dir / deal_id / "truth.json").read_text())
    t["_package_dir"] = str(deals_dir / deal_id / "package")
    return t


def list_truth_deals(deals_dir: Path = DEALS_DIR) -> list[str]:
    return sorted(p.parent.name for p in deals_dir.glob("*/truth.json"))


@lru_cache(maxsize=None)
def _mandate_market() -> tuple[dict, dict]:
    import engine
    return engine.load_mandate(), engine.load_market()


def engine_on_truth(truth: dict) -> dict:
    """Run engine.underwrite and engine.mandate_fit on the truth; returns the expected numbers."""
    import engine
    mandate, market = _mandate_market()
    tb = truth["true_building"]
    uw = engine.underwrite(tb["engine_inputs"], mandate, market)
    fit = engine.mandate_fit(tb["deal_facts"], uw, mandate)
    return {
        "metrics": {k: uw["metrics"][k]["value"] for k in UW_METRICS},
        "verdict": fit["verdict"],
        "reason": fit["reason"],
        "hard_fails": sorted(t["name"] for t in fit["tests"] if t["kind"] == "hard" and t["status"] == "fail"),
        "soft_fails": sorted(t["name"] for t in fit["tests"] if t["kind"] == "soft" and t["status"] == "fail"),
        "unknown": sorted(t["name"] for t in fit["tests"] if t["status"] == "unknown"),
        "tests": {t["name"]: {"kind": t["kind"], "status": t["status"], "actual": t.get("actual")} for t in fit["tests"]},
        "engine_version": uw.get("engine_version"),
        "warnings": uw.get("warnings", []),
    }
