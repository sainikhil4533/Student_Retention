"""
Centralised 4-tier risk classification.

Uses fixed, semantically-grounded thresholds based on what
the probability represents — the likelihood of dropout:

    HIGH   ≥ 0.50  →  more likely to drop out than not (decision boundary)
    MEDIUM ≥ 0.30  →  ~1 in 3 chance, meaningful risk
    LOW    ≥ 0.15  →  ~1 in 7 chance, minor indicators
    SAFE   < 0.15  →  negligible risk

These thresholds are universal and dataset-independent.
They do NOT change based on the current cohort's distribution.
"""

from __future__ import annotations

# ── fixed thresholds (semantically grounded) ────────────────────
HIGH_THRESHOLD = 0.50   # decision boundary: more likely than not
MEDIUM_THRESHOLD = 0.30  # meaningful risk: ~1 in 3
LOW_THRESHOLD = 0.15    # minor indicators: ~1 in 7

RISK_TIERS = ("HIGH", "MEDIUM", "LOW", "SAFE")


def classify_risk_level(probability: float) -> str:
    """Return one of HIGH / MEDIUM / LOW / SAFE."""
    if probability >= HIGH_THRESHOLD:
        return "HIGH"
    if probability >= MEDIUM_THRESHOLD:
        return "MEDIUM"
    if probability >= LOW_THRESHOLD:
        return "LOW"
    return "SAFE"
