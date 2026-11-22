"""Phase-margin acceptance shared by design calculations and reports."""
import math
from numbers import Real


MIN_PHASE_MARGIN_DEG = 45.0


def phase_margin_passes(value):
    return isinstance(value, Real) and math.isfinite(value) and value > MIN_PHASE_MARGIN_DEG
