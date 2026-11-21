"""Access to a deal package, and nothing else.

The pipeline sees a deal only through :class:`PackageLoader`, which resolves every path
inside ``data/deals/<deal_id>/package/`` and refuses anything outside it. This is what keeps
ground truth (``truth.json``, one level up) out of the pipeline; ``tests/pipeline/test_loader.py``
enforces it.
"""

from __future__ import annotations

from pathlib import Path

from .config import DEALS_DIR

SUPPORTED_SUFFIXES = {".pdf", ".xlsx", ".xlsm", ".csv"}


class PackageAccessError(PermissionError):
    """A path outside the deal's package/ folder was requested."""


class PackageLoader:
    """Read-only, sandboxed view of one deal's ``package/`` folder."""

    def __init__(self, deal_id: str, deals_dir: Path = DEALS_DIR):
        if not deal_id or any(sep in deal_id for sep in ("/", "\\")) or deal_id.startswith("."):
            raise PackageAccessError(f"invalid deal id {deal_id!r}")
        self.deal_id = deal_id
        self.root = (Path(deals_dir) / deal_id / "package").resolve()
        if not self.root.is_dir():
            raise FileNotFoundError(f"no package folder for deal {deal_id!r}: {self.root}")

    def resolve(self, name: str | Path) -> Path:
        """Return the absolute path of a package file, refusing anything outside package/."""
        candidate = Path(name)
        path = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if path != self.root and self.root not in path.parents:
            raise PackageAccessError(f"{name!s} is outside the package folder of {self.deal_id}")
        if path.name == "truth.json":
            raise PackageAccessError("truth.json is ground truth and is never read by the pipeline")
        return path

    def documents(self) -> list[Path]:
        """Package files the pipeline can ingest, sorted by name. Symlinks are not followed out."""
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES:
                out.append(self.resolve(p))
        return out

    def read_bytes(self, name: str | Path) -> bytes:
        return self.resolve(name).read_bytes()

    def relative(self, path: Path) -> str:
        """Document id used in citations: the path relative to package/."""
        return self.resolve(path).relative_to(self.root).as_posix()
