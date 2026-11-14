"""Offline simulation: several advisers converging through a VirtualRoom, no audio (SPEC.md §7.6).

    python -m backend.sim [--advisers 4] [--loss 0.1] [--speed 4] [--out sim.png] [--synthetic]

Uses `data/chf2015.csv` through `backend.data.load_bars` when both exist. Otherwise it falls back
to synthetic bars shaped like January 2015 (calm with the floor, one shock bar, a looser
aftermath), so the convergence logic can be tuned before the real data lands.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from backend import config as C
from backend.adviser import Adviser
from backend.contracts import Bar
from backend.mocks import VirtualRoom

log = logging.getLogger(__name__)

DATA_CSV = Path(__file__).resolve().parents[1] / "data" / "chf2015.csv"

# §4.7: a packet is 10 symbols of tone plus gap, then the idle tail. 1.9 s with the default config.
SYMBOLS_PER_PACKET = 10
PACKET_CYCLE_S = ((C.TONE_MS + C.GAP_MS) * SYMBOLS_PER_PACKET + C.IDLE_MS) / 1000

# §7.6 pass criteria.
SPREAD_SHRINK = 0.5  # spread at the end must be under this fraction of the spread at the shock
STORM_BARS = C.SCORE_WINDOW  # the storm phase: the shock to one score window after it (§6.4)


def utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def shock_index(times: list[datetime]) -> int:
    """The bar that CONTAINS SHOCK_TIME. Bars are labelled by their start (§5.2), so with 2-hour
    bars the 09:30 shock is in the 08:00 bar, not the first bar at or after 09:30."""
    shock = utc(C.SHOCK_TIME)
    return max(k for k, t in enumerate(times) if t <= shock)


# ----- data ------------------------------------------------------------------------------------


def synthetic_bars(seed: int = 0) -> list[Bar]:
    """Bars shaped like 2–23 January 2015. For tuning only: the numbers are invented.

    - Calm: the 1.20 floor pins CHF to EUR, so rS ≈ rF.
    - Shock bar at SHOCK_TIME: the franc jumps about 15% while EUR/GBP barely moves.
    - Aftermath: EUR/CHF floats, very volatile at first and settling over the following days.
    """
    rng = np.random.default_rng(seed)
    start, end, shock = utc("2015-01-02T00:00Z"), utc(C.REPLAY_END), utc(C.SHOCK_TIME)
    step = timedelta(minutes=C.BAR_MINUTES)
    times = []
    t = start
    while t <= end:
        # FX trades Sunday 22:00 to Friday 22:00 UTC (§5.3).
        wd, hour = t.weekday(), t.hour
        closed = wd == 5 or (wd == 4 and hour >= 22) or (wd == 6 and hour < 22)
        if not closed:
            times.append(t)
        t += step

    n = len(times)
    rF = rng.normal(0.0, 4e-4, n)
    rEURCHF = rng.normal(0.0, 3e-5, n)  # pinned: barely moves
    k_shock = shock_index(times)
    days_after = np.array([(t - shock).total_seconds() / 86400 for t in times])
    after = days_after > 0
    # After the shock EUR/CHF floats: volatility starts high and decays over a few days.
    vol = 2.5e-3 * np.exp(-np.clip(days_after, 0, None) / 2.0) + 6e-4
    rEURCHF[after] = rng.normal(0.0, 1.0, after.sum()) * vol[after]
    rEURCHF[k_shock] = -0.15  # the franc jumps: EUR buys ~15% fewer francs
    rEURCHF[k_shock + 1 : k_shock + 4] = [0.04, -0.03, 0.02]  # a few wild bars straight after
    rS = rF - rEURCHF  # S = F / EURCHF in GBP per CHF
    rS[0] = rF[0] = 0.0

    F = 0.785 * np.exp(np.cumsum(rF))
    S = 0.785 / 1.2 * np.exp(np.cumsum(rS))
    rho = _rolling_corr(rS, rF, C.RHO_WINDOW)
    return [
        Bar(k, times[k], float(S[k]), float(F[k]), float(F[k] / S[k]), float(rS[k]), float(rF[k]), float(rho[k]))
        for k in range(n)
    ]


def _rolling_corr(a: np.ndarray, b: np.ndarray, window: int) -> np.ndarray:
    out = np.zeros(len(a))
    for k in range(window - 1, len(a)):
        x, y = a[k - window + 1 : k + 1], b[k - window + 1 : k + 1]
        if x.std() > 0 and y.std() > 0:
            out[k] = float(np.corrcoef(x, y)[0, 1])
    return out


def load(synthetic: bool) -> tuple[list[Bar], bool]:
    """(bars, is_synthetic). Real data when it's available and not overridden."""
    if not synthetic and DATA_CSV.exists():
        try:
            from backend.data import load_bars  # lane P1-A
        except ImportError:
            log.warning("%s exists but backend/data.py doesn't yet: using synthetic data", DATA_CSV)
        else:
            return load_bars(str(DATA_CSV)), False
    elif not synthetic:
        log.warning("%s not found: using SYNTHETIC data (invented numbers, for tuning only)", DATA_CSV)
    return synthetic_bars(), True


# ----- simulation ------------------------------------------------------------------------------


@dataclass
class Run:
    """What happened to every adviser on every replay bar."""

    times: list[datetime] = field(default_factory=list)
    dials: list[list[float]] = field(default_factory=list)  # [bar][adviser]
    scores: list[list[float]] = field(default_factory=list)


def simulate(
    bars: list[Bar], n_advisers: int, speed_step: int, loss: float | None, seed: int = 0
) -> Run:
    """Warm up, then replay. `loss=None` means nobody hears anybody (dials stay fixed)."""
    advisers = [Adviser(ch, C.START_DIALS[ch % len(C.START_DIALS)]) for ch in range(n_advisers)]
    start = utc(C.REPLAY_START)
    warm = [b for b in bars if b.time < start]
    replay = [b for b in bars if start <= b.time <= utc(C.REPLAY_END)]
    for bar in warm:
        for a in advisers:
            a.on_bar(bar)

    speed = C.SPEED_BARS_PER_S[speed_step]
    if speed <= 0:
        raise ValueError("speed step 0 is paused: nothing would happen")
    room = VirtualRoom(loss=loss, channels=range(n_advisers), seed=seed) if loss is not None else None
    # Stagger transmit and decide times, as real Macs wouldn't start in lockstep.
    next_send = [ch * PACKET_CYCLE_S / n_advisers for ch in range(n_advisers)]
    next_decide = [C.DECISION_PERIOD_S + ch * C.DECISION_PERIOD_S / n_advisers for ch in range(n_advisers)]

    run = Run()
    for k, bar in enumerate(replay):
        t = (k + 1) / speed  # simulated seconds since the replay started
        for a in advisers:
            a.on_bar(bar)
        if room is not None:
            for ch, a in enumerate(advisers):
                while next_send[ch] <= t:
                    room.send(a.packet(), next_send[ch])
                    next_send[ch] += PACKET_CYCLE_S
            for ch, heard in room.receive(t):
                advisers[ch].on_heard(heard)
        for ch, a in enumerate(advisers):
            while next_decide[ch] <= t:
                a.decide(next_decide[ch])
                next_decide[ch] += C.DECISION_PERIOD_S
        run.times.append(bar.time)
        run.dials.append([a.dial for a in advisers])
        run.scores.append([a.score for a in advisers])
    return run


# ----- summary ---------------------------------------------------------------------------------


@dataclass
class Summary:
    spread_at_shock: float
    spread_at_end: float
    final_steps: list[int]
    final_dials: list[float]
    aftermath_score: float
    aftermath_score_fixed: float
    calm_moves: int

    @property
    def converged(self) -> bool:
        return self.spread_at_end < SPREAD_SHRINK * self.spread_at_shock

    @property
    def helped(self) -> bool:
        return self.aftermath_score >= self.aftermath_score_fixed

    @property
    def calm_held(self) -> bool:
        return self.calm_moves == 0

    @property
    def passed(self) -> bool:
        return self.converged and self.helped and self.calm_held


def summarise(run: Run, fixed: Run) -> Summary:
    k_shock = shock_index(run.times)
    k_after = min(k_shock + STORM_BARS, len(run.times) - 1)
    dials = np.array(run.dials)
    spread = dials.max(axis=1) - dials.min(axis=1)
    calm = dials[:k_shock]  # every bar before the shock bar
    calm_moves = int(np.sum(np.any(np.diff(calm, axis=0) != 0, axis=1)))
    final = [float(d) for d in dials[-1]]
    return Summary(
        spread_at_shock=float(spread[k_shock - 1]),  # just before the shock bar
        spread_at_end=float(spread[-1]),
        final_steps=[int(round(d)) for d in final],
        final_dials=final,
        aftermath_score=float(np.mean(np.array(run.scores)[k_after:])),
        aftermath_score_fixed=float(np.mean(np.array(fixed.scores)[k_after:])),
        calm_moves=calm_moves,
    )


def report(s: Summary, synthetic: bool) -> str:
    def mark(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    lines = [
        "SYNTHETIC DATA: invented numbers, for tuning only" if synthetic else "Real data: data/chf2015.csv",
        f"Spread at shock {s.spread_at_shock:.2f}, at end {s.spread_at_end:.2f}",
        f"Final dials {[round(d, 2) for d in s.final_dials]}, steps {s.final_steps}",
        f"Mean aftermath score: converging {s.aftermath_score:.3f}, fixed dials {s.aftermath_score_fixed:.3f}",
        f"[{mark(s.converged)}] spread at end < {SPREAD_SHRINK} x spread at shock",
        f"[{mark(s.helped)}] aftermath score with convergence >= without",
        f"[{mark(s.calm_held)}] no adviser moves during calm ({s.calm_moves} bars with a move)",
    ]
    return "\n".join(lines)


def plot(run: Run, synthetic: bool, out: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    shock = utc(C.SHOCK_TIME)
    dials = np.array(run.dials)
    scores = np.array(run.scores)
    spread = dials.max(axis=1) - dials.min(axis=1)
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for ch in range(dials.shape[1]):
        axes[0].plot(run.times, dials[:, ch], label=f"ch {ch}")
        axes[1].plot(run.times, scores[:, ch], label=f"ch {ch}")
    axes[2].plot(run.times, spread, color="black")
    for ax, name in zip(axes, ("Dial (0 fast … 6 slow)", "Score E", "Spread of dials")):
        ax.axvline(shock, color="red", linestyle="--", linewidth=1)
        ax.set_ylabel(name)
        ax.grid(alpha=0.3)
    axes[0].legend(loc="upper left", ncol=4, fontsize=8)
    title = "Adviser convergence (SYNTHETIC DATA)" if synthetic else "Adviser convergence"
    axes[0].set_title(title)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--advisers", type=int, default=len(C.START_DIALS))
    p.add_argument("--loss", type=float, default=0.1)
    p.add_argument("--speed", type=int, default=C.DEFAULT_SPEED_STEP, help="speed step 1–7")
    p.add_argument("--out", default="sim.png")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--synthetic", action="store_true", help="use synthetic data even if the CSV exists")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    bars, synthetic = load(args.synthetic)
    run = simulate(bars, args.advisers, args.speed, args.loss, args.seed)
    fixed = simulate(bars, args.advisers, args.speed, None, args.seed)
    summary = summarise(run, fixed)
    log.info(report(summary, synthetic))
    plot(run, synthetic, args.out)
    log.info("Saved %s", args.out)
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
