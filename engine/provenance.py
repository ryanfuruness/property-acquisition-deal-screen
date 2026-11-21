"""Provenance bookkeeping for engine inputs and outputs.

Every number the engine produces must be traceable to the inputs it was computed
from (docs/DESIGN.md, "Principle" and "Engine interface"). The engine records every
input it uses in an :class:`InputRegistry` under a dotted name, tagged with where the
value came from:

``document``
    stated in the deal package (offering memorandum, rent roll, operating statement).
``default``
    not in the package; filled in from a mandate default (for example a missing
    opex line priced per sq ft of NSA).
``mandate``
    a firm assumption or rule from ``data/mandate.yaml``.
``market``
    area reference data from ``data/market/areas.yaml``.

Outputs then refer to registry entries by name via :func:`metric` and :func:`series`.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

PROVENANCE_TAGS = ("document", "default", "mandate", "market")


class InputRegistry:
    """Ordered collection of the inputs one underwriting run used."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def add(self, name: str, value: Any, unit: str, provenance: str,
            note: str | None = None) -> str:
        """Record an input and return its name, for use in ``depends_on`` lists."""
        if provenance not in PROVENANCE_TAGS:
            raise ValueError(f"unknown provenance tag {provenance!r} for {name}")
        entry: dict[str, Any] = {"value": value, "unit": unit, "provenance": provenance}
        if note:
            entry["note"] = note
        self._items[name] = entry
        return name

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def provenance(self, name: str) -> str:
        return self._items[name]["provenance"]

    def refs(self, names: Iterable[str]) -> list[dict[str, str]]:
        """Turn input names into ``depends_on`` records, de-duplicated in order."""
        out: list[dict[str, str]] = []
        seen: set[str] = set()
        for name in names:
            if name in seen:
                continue
            if name not in self._items:
                raise KeyError(f"depends_on refers to unregistered input {name!r}")
            seen.add(name)
            out.append({"input": name, "provenance": self._items[name]["provenance"]})
        return out

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._items)


def metric(value: Any, unit: str, depends_on: list[dict[str, str]],
           note: str | None = None) -> dict[str, Any]:
    """A single numeric output: ``{"value", "unit", "depends_on", "note"?}``."""
    out: dict[str, Any] = {"value": value, "unit": unit, "depends_on": depends_on}
    if note:
        out["note"] = note
    return out


def series(values: list[Any], depends_on: list[dict[str, str]],
           note: str | None = None) -> dict[str, Any]:
    """A row of a year-by-year table: ``{"values", "depends_on", "note"?}``."""
    out: dict[str, Any] = {"values": values, "depends_on": depends_on}
    if note:
        out["note"] = note
    return out
