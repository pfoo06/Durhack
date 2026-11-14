"""Finance engine: hedge ratio, hedged return and score (SPEC.md §6.3).

Every adviser runs exactly this maths. Only the half-life differs (D6).
The output MUST match the reference `run()` in SPEC.md §6.4 to within 1e-9.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING

from backend.config import H_CLAMP, SCORE_WINDOW

if TYPE_CHECKING:
    from backend.contracts import Bar

# Thresholds written into SPEC.md §6.3 but not listed in config.py (§4.5).
VAR_EPSILON = 1e-12  # below this, the proxy variance is too small to divide by (§6.3 step 3)
SCORE_EPSILON = 1e-16  # below this, there's nothing to hedge and E is 1.0 (§6.3 step 5)
RESUM_EVERY = 1000  # recompute the running sums from scratch this often (§6.3)


class Hedger:
    """EWMA minimum-variance hedge ratio for one adviser."""

    def __init__(self, half_life_bars: float) -> None:
        self.cov = 0.0
        self.var = 0.0
        self.h = 1.0  # the ratio that will be used on the NEXT bar
        self.set_half_life(half_life_bars)

    @property
    def half_life_bars(self) -> float:
        return self._half_life_bars

    def set_half_life(self, bars: float) -> None:
        """Change the reaction speed from the next bar on. Keeps `cov`, `var` and `h` (§6.2)."""
        if bars <= 0:
            raise ValueError(f"half-life must be positive, got {bars}")
        self._half_life_bars = float(bars)
        self._lam = 0.5 ** (1.0 / bars)

    def update(self, bar: Bar) -> tuple[float, float]:
        """Process one bar. Returns `(h_used, rH)`.

        `rH` is judged with the ratio decided before this bar, so the adviser never
        sees the future (§6.3 step 1). `self.h` then holds the ratio for the next bar.
        """
        rS = bar.rS
        rF = bar.rF

        h_used = self.h
        rH = rS - h_used * rF

        lam = self._lam
        self.cov = lam * self.cov + (1 - lam) * rS * rF
        self.var = lam * self.var + (1 - lam) * rF * rF

        h = self.cov / self.var if self.var > VAR_EPSILON else self.h
        low, high = H_CLAMP
        self.h = min(max(h, low), high)

        return h_used, rH


class Effectiveness:
    """Rolling hedge effectiveness E over a plain window of the last `window` bars."""

    def __init__(self, window: int = SCORE_WINDOW) -> None:
        if window < 1:
            raise ValueError(f"window must be at least 1, got {window}")
        self._hedged_sq: deque[float] = deque(maxlen=window)
        self._exposure_sq: deque[float] = deque(maxlen=window)
        self._sum_hedged = 0.0
        self._sum_exposure = 0.0
        self._updates = 0

    def update(self, rS: float, rH: float) -> float:
        """Add one bar and return E = 1 − Σ rH² / Σ rS² over the window, clipped to [0, 1]."""
        hedged_sq = rH * rH
        exposure_sq = rS * rS

        if len(self._hedged_sq) == self._hedged_sq.maxlen:
            self._sum_hedged -= self._hedged_sq[0]
            self._sum_exposure -= self._exposure_sq[0]
        self._hedged_sq.append(hedged_sq)
        self._exposure_sq.append(exposure_sq)
        self._sum_hedged += hedged_sq
        self._sum_exposure += exposure_sq

        self._updates += 1
        if self._updates % RESUM_EVERY == 0:
            self._sum_hedged = math.fsum(self._hedged_sq)
            self._sum_exposure = math.fsum(self._exposure_sq)

        # Compared as a sum, not a mean, to match the reference run() (see the PR's spec gap note).
        if self._sum_exposure <= SCORE_EPSILON:
            return 1.0
        e = 1.0 - max(self._sum_hedged, 0.0) / self._sum_exposure
        return min(max(e, 0.0), 1.0)
