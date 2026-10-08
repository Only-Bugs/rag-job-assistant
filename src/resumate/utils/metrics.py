"""
Number/metric helpers shared by generation guards and the eval checks.
"""

from __future__ import annotations

import re

# A number with an optional unit: 50%, 5,000+, 3x, 2 hours. Not part of a
# word or hyphenated token, so "3-tier", "Q2" and "Llama 3," behave sensibly.
METRIC_RE = re.compile(r"(?<![\w-])\d[\d,.]*(?:\s?%|\+|x\b)?(?![\w-])")


def metric_key(token: str) -> str:
    """Digits plus unit, so "10%" is only grounded by a percentage, not by any "10"."""
    unit = "%" if "%" in token else "+" if "+" in token else "x" if token.endswith("x") else ""
    return re.sub(r"[^\d]", "", token) + unit


def metric_keys(text: str) -> set[str]:
    return {metric_key(m.group(0)) for m in METRIC_RE.finditer(text)}


def is_grounded(token: str, grounded: set[str]) -> bool:
    """True if a number token is backed by `grounded` keys. A bare number is
    backed by the same number with a "+" ("over 12,000" vs "12,000+")."""
    k = metric_key(token)
    return k in grounded or (k.isdigit() and k + "+" in grounded)


__all__ = ["METRIC_RE", "metric_key", "metric_keys", "is_grounded"]
