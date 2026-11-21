"""AI pipeline for the Dubai residential-building deal screen.

The model reads, maps and judges; code computes and verifies. See pipeline/README.md and
docs/DESIGN.md. Entry point: ``python -m pipeline run <deal_id>``.
"""

from .config import PIPELINE_VERSION

__all__ = ["PIPELINE_VERSION"]
