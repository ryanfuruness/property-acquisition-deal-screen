"""Evaluation harness for Deal Screen: scores runs/<deal_id>/run.json against data/deals/<deal_id>/truth.json.

Independent of the pipeline's builder; reads the pipeline only to reuse its memo checker. See evals/README.md.
"""

from .scorer import score_deal, score_runs, write_results  # noqa: F401
