"""Load the mandate and the screen reference data (areas.yaml).

The engine itself takes plain dicts so that callers (pipeline, tests, the CLI) can
pass reference data from anywhere; these helpers read the repo's YAML files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANDATE_PATH = REPO_ROOT / "data" / "mandate.yaml"
DEFAULT_MARKET_PATH = REPO_ROOT / "data" / "market" / "areas.yaml"


def _load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def load_mandate(path: str | Path = DEFAULT_MANDATE_PATH) -> dict[str, Any]:
    """Read ``mandate.yaml`` and check the sections the engine needs are present."""
    data = _load_yaml(path)
    for key in ("buy_box", "verdict_rules", "underwriting"):
        if key not in data:
            raise ValueError(f"{path}: missing top-level section {key!r}")
    return data


def load_market(path: str | Path = DEFAULT_MARKET_PATH) -> dict[str, Any]:
    """Read ``areas.yaml`` and check it has ``areas`` and ``unit_type_factors``."""
    data = _load_yaml(path)
    for key in ("areas", "unit_type_factors"):
        if key not in data:
            raise ValueError(f"{path}: missing top-level section {key!r}")
    return data
