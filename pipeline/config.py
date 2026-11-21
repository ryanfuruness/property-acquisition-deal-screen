"""Pipeline configuration: paths, model settings, prices, budget and reconcile thresholds.

Everything a reviewer might want to tune lives here, in one place. Dubai rules and the
firm's assumptions do NOT live here: they are data in ``data/mandate.yaml`` and
``data/market/areas.yaml`` and are read from there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PIPELINE_VERSION = "0.2.0"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEALS_DIR = REPO_ROOT / "data" / "deals"
RUNS_DIR = REPO_ROOT / "runs"
LEDGER_PATH = RUNS_DIR / "_ledger.json"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

DEFAULT_MODEL = os.environ.get("DEAL_SCREEN_MODEL", "claude-sonnet-5-5")
# Model for the cheap mapping passes (rent-roll layout, operating-statement mapping). Set to
# DEFAULT_MODEL to use one model throughout.
MAPPING_MODEL = os.environ.get("DEAL_SCREEN_MAPPING_MODEL", DEFAULT_MODEL)
MAX_OUTPUT_TOKENS = 8000
REQUEST_TIMEOUT_S = 300
MAX_RETRIES = 3

# USD per million tokens. ASSUMPTIONS: list prices as understood when this was written; update
# them from the provider's pricing page before relying on the cost figures. Cache writes are
# priced at 1.25x input (5-minute TTL), cache reads at 0.1x input.
PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-sonnet-5-5": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku-5-5": {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10},
    "claude-opus-5-5": {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
}
# Used for a model missing from the table, so cost is never silently zero.
FALLBACK_PRICE = PRICES_USD_PER_MTOK["claude-opus-5-5"]

# A run refuses to start when the ledger's cumulative spend is above this.
BUDGET_USD = float(os.environ.get("DEAL_SCREEN_BUDGET_USD", "25"))

# Page images for the site: PyMuPDF zoom (1.0 = 72 dpi). 2.0 = 144 dpi, sharp on a laptop
# screen at full width; pages are then quantised to a 256-colour palette to keep PNGs small.
PAGE_IMAGE_ZOOM = 2.0
PAGE_IMAGE_COLOURS = 256
# Scanned pages: grayscale, 16 levels, near the scan's own resolution (speckle compresses badly).
SCAN_IMAGE_ZOOM = 1.5
SCAN_IMAGE_GREYS = 16

# Ingest: a PDF page with an image and fewer extractable characters than this is treated as scanned.
OCR_MIN_TEXT_CHARS = 25
OCR_DPI = 400
OCR_LANG = "eng"

# Verify: minimum similarity (0-1) for a fuzzy quote match on an OCR'd page.
OCR_FUZZY_MIN_RATIO = 0.85

SQM_TO_SQFT = 10.7639


@dataclass(frozen=True)
class ReconcileThresholds:
    """Explicit thresholds for every rule-detected discrepancy (docs/DESIGN.md catalogue).

    Mandate-derived limits (over-rent share, expiry share, occupancy) are read from
    ``mandate.yaml`` at run time; the numbers here are the screen's own tolerances.
    """

    occupancy_points: float = 0.02            # 1: OM vs rent roll occupancy, absolute
    potential_rent_tolerance: float = 0.01    # 2: OM rent within 1% of roll potential (and above in-place)
    in_place_excess: float = 0.02             # 2: OM rent must exceed in-place by >2% to flag
    net_yield_min_cost_share: float = 0.5     # 3: OM "net" must deduct >= 50% of buyer opex
    net_vs_gross_points: float = 0.001        # 3: OM "net" within 0.1 pt of gross on price is gross
    over_rent_material_share: float | None = None   # 5: None = use mandate max_over_rent_share_of_income
    rera_claim_tolerance_points: float = 0.01       # 6: claimed uplift above RERA-allowed by >1 pt
    sqm_ratio_tolerance: float = 0.03         # 8: OM area / roll area within 3% of 10.7639
    psf_match_tolerance: float = 0.01         # 8: OM psf within 1% of price / BUA
    foot_rel_tolerance: float = 0.002         # 9: summary row vs sum of rows
    foot_abs_tolerance_aed: float = 1000.0    # 9: ignore rounding below AED 1,000
    unit_count_tolerance: int = 0             # 10: any count difference flags
    oa_service_charge_share: float = 0.25     # 7: a service charge >= 25% of stated opex is an OA budget that
                                              #    covers common utilities, security/cleaning and maintenance
    collections_gap: float = 0.06             # 12: statement rent below roll in-place by > 6%
    full_period_months: int = 12              # 13
    expiry_share_limit: float | None = None   # 15: None = use the mandate limit (3-month windows, engine)


THRESHOLDS = ReconcileThresholds()

# Categories the screen expects on a whole-building statement (catalogue item 7). District
# cooling is expected only when the landlord pays chilled water.
STANDARD_OPEX_CATEGORIES = ("property_management", "insurance", "sinking_fund", "maintenance_repairs",
                            "utilities_common", "security_cleaning")
CHILLER_CATEGORY = "district_cooling"


@dataclass
class RunSettings:
    """Per-invocation settings from the CLI."""

    model: str = DEFAULT_MODEL
    mapping_model: str = MAPPING_MODEL
    budget_usd: float = BUDGET_USD
    deals_dir: Path = DEALS_DIR
    runs_dir: Path = RUNS_DIR
    replay: bool = False      # reuse stored model responses for identical requests (development)
