"""Tests for backend/finance.py (SPEC.md §13, test_finance.py rows)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from backend.contracts import Bar
from backend.finance import Effectiveness, Hedger

DATA_CSV = Path(__file__).resolve().parents[2] / "data" / "chf2015.csv"
START = datetime(2015, 1, 2, tzinfo=timezone.utc)


def make_bar(i: int, rS: float, rF: float) -> Bar:
    # Only rS and rF matter to the finance engine; the other fields are placeholders.
    return Bar(i=i, time=START + timedelta(minutes=15 * i), S=1.0, F=1.0, eurchf=1.2, rS=rS, rF=rF, rho=0.0)


def run_engine(rS: np.ndarray, rF: np.ndarray, half_life: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Feed the series through Hedger + Effectiveness. Returns (rH, h after each bar, E)."""
    hedger = Hedger(half_life)
    score = Effectiveness()
    rH = np.empty(len(rS))
    h_after = np.empty(len(rS))
    E = np.empty(len(rS))
    for t in range(len(rS)):
        _, rH[t] = hedger.update(make_bar(t, float(rS[t]), float(rF[t])))
        h_after[t] = hedger.h
        E[t] = score.update(float(rS[t]), rH[t])
    return rH, h_after, E


def reference_run(rS: np.ndarray, rF: np.ndarray, H: float, W: int = 96) -> np.ndarray:
    """Verbatim copy of the reference implementation in SPEC.md §6.4."""
    lam = 0.5 ** (1 / H)
    cov = var = 0.0
    h = 1.0
    rH = np.empty_like(rS)
    for t in range(len(rS)):
        rH[t] = rS[t] - h * rF[t]
        cov = lam * cov + (1 - lam) * rS[t] * rF[t]
        var = lam * var + (1 - lam) * rF[t] ** 2
        if var > 1e-12:
            h = cov / var
        h = min(max(h, 0.0), 2.0)
    k = np.ones(W)
    num = np.convolve(rH**2, k)[: len(rH)]
    den = np.convolve(rS**2, k)[: len(rS)]
    with np.errstate(divide="ignore", invalid="ignore"):
        E = np.where(den > 1e-16, 1 - num / den, 1.0)
    return np.clip(E, 0.0, 1.0)


def synthetic(n: int = 3000) -> tuple[np.ndarray, np.ndarray]:
    """§13: rF ~ N(0, 1e-3), rS = 0.6·rF + N(0, 0.8e-3), seed 0. True slope 0.6, ρ² = 0.36."""
    rng = np.random.default_rng(0)
    rF = rng.normal(0.0, 1e-3, n)
    rS = 0.6 * rF + rng.normal(0.0, 0.8e-3, n)
    return rS, rF


def test_converges_to_regression_slope() -> None:
    rS, rF = synthetic()
    _, h_after, E = run_engine(rS, rF, half_life=64)
    assert np.mean(h_after[-1000:]) == pytest.approx(0.6, rel=0.05)
    assert np.mean(E[-1000:]) == pytest.approx(0.36, abs=0.06)


def test_no_look_ahead() -> None:
    rS, rF = synthetic(500)
    rH, h_after, _ = run_engine(rS, rF, half_life=4)
    h_before = np.concatenate(([1.0], h_after[:-1]))  # the initial ratio is 1.0
    for t in range(len(rS)):
        assert rH[t] == rS[t] - h_before[t] * rF[t]


def test_identical_series_scores_one() -> None:
    rS, _ = synthetic(300)
    _, _, E = run_engine(rS, rS.copy(), half_life=16)
    assert E[-1] == pytest.approx(1.0)


def test_zero_hedge_scores_zero() -> None:
    score = Effectiveness()
    rS, _ = synthetic(200)
    for r in rS:
        e = score.update(float(r), float(r))  # h = 0 means rH = rS
    assert e == 0.0


def test_outlier_keeps_ratio_in_clamp() -> None:
    hedger = Hedger(4)
    rS, rF = synthetic(200)
    for t in range(200):
        hedger.update(make_bar(t, float(rS[t]), float(rF[t])))
    for t, (big_s, tiny_f) in enumerate([(0.2, 1e-6), (-0.2, 1e-6), (0.2, -1e-6)], start=200):
        hedger.update(make_bar(t, big_s, tiny_f))
        assert 0.0 <= hedger.h <= 2.0


def test_nothing_to_hedge_scores_one() -> None:
    score = Effectiveness()
    assert score.update(0.0, 0.0) == 1.0


def test_set_half_life_keeps_memory() -> None:
    hedger = Hedger(4)
    rS, rF = synthetic(100)
    for t in range(100):
        hedger.update(make_bar(t, float(rS[t]), float(rF[t])))
    cov, var, h = hedger.cov, hedger.var, hedger.h
    hedger.set_half_life(256)
    assert (hedger.cov, hedger.var, hedger.h) == (cov, var, h)
    assert hedger.half_life_bars == 256


@pytest.mark.parametrize("step", [0, 3, 6])
def test_matches_reference_on_synthetic_data(step: int) -> None:
    rS, rF = synthetic()
    _, _, E = run_engine(rS, rF, half_life=4 * 2**step)
    assert np.max(np.abs(E - reference_run(rS, rF, H=4 * 2**step))) < 1e-9


@pytest.mark.skipif(not DATA_CSV.exists(), reason="data/chf2015.csv not prepared yet (lane P1-A)")
@pytest.mark.parametrize("step", [0, 3, 6])
def test_matches_reference_on_real_data(step: int) -> None:
    import pandas as pd

    df = pd.read_csv(DATA_CSV)
    rS = df["rS"].to_numpy(dtype=float)
    rF = df["rF"].to_numpy(dtype=float)
    _, _, E = run_engine(rS, rF, half_life=4 * 2**step)
    assert np.max(np.abs(E - reference_run(rS, rF, H=4 * 2**step))) < 1e-9
