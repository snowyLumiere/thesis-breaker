"""Numeric validation shared by the audit and valuation engines."""

from __future__ import annotations

import math
from typing import Any


def finite_float(value: Any, name: str) -> float:
    """Return a finite number, or explain which input/result is invalid."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Invalid numeric value for {name}: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Invalid numeric value for {name}: must be finite (got {value!r})")
    return number
