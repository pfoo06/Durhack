"""Run each of the 7 strategies alone through warm-up and replay (SPEC.md §6.4).

Usage:
    python tools/sweep.py [--out sweep.png]

Prints mean score E per dial step for three phases (calm, storm, aftermath), checks the
§6.4 pass criteria for START_DIALS, and saves E over time for every step.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import BAR_MINUTES, H_MIN_BARS, MOVE_THRESHOLD, SCORE_WINDOW, SHOCK_TIME, START_DIALS  # noqa: E402
from backend.data import load_bars, replay_range  # noqa: E402
from backend.finance import Effectiveness, Hedger  # noqa: E402

STEPS = range(7)


def scores(bars, step: int) -> np.ndarray:
    """Score E after every bar for one strategy that never moves its dial."""
    hedger = Hedger(H_MIN_BARS * 2**step)
    judge = Effectiveness(SCORE_WINDOW)
    out = np.empty(len(bars))
    for k, bar in enumerate(bars):
        _, rH = hedger.update(bar)
        out[k] = judge.update(bar.rS, rH)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="sweep.png")
    args = parser.parse_args()

    bars = load_bars()
    first, last = replay_range(bars)
    shock_time = datetime.fromisoformat(SHOCK_TIME)
    bar_length = timedelta(minutes=BAR_MINUTES)
    shock = next(b.i for b in bars if b.time <= shock_time < b.time + bar_length)  # the bar containing the shock
    phases = {
        "calm": slice(first, shock),
        "storm": slice(shock, shock + SCORE_WINDOW),
        "aftermath": slice(shock + SCORE_WINDOW, last + 1),
    }

    E = {step: scores(bars, step) for step in STEPS}
    means = {step: {name: float(E[step][sl].mean()) for name, sl in phases.items()} for step in STEPS}

    print(f"bars {len(bars)}, replay {first}-{last}, shock bar {shock}")
    print(f"{'step':>4} {'H (bars)':>8} {'calm':>7} {'storm':>7} {'aftermath':>9}")
    for step in STEPS:
        m = means[step]
        mark = "  *" if step in START_DIALS else ""
        print(f"{step:>4} {H_MIN_BARS * 2**step:>8} {m['calm']:>7.3f} {m['storm']:>7.3f} {m['aftermath']:>9.3f}{mark}")
    print("* = START_DIALS")

    def gap(phase: str) -> float:
        values = [means[s][phase] for s in START_DIALS]
        return max(values) - min(values)

    calm_gap, after_gap = gap("calm"), gap("aftermath")
    best_calm = max(STEPS, key=lambda s: means[s]["calm"])
    best_after = max(STEPS, key=lambda s: means[s]["aftermath"])
    print()
    print(f"MUST  aftermath gap among START_DIALS {after_gap:.3f} >= {2 * MOVE_THRESHOLD:.3f}: "
          f"{'PASS' if after_gap >= 2 * MOVE_THRESHOLD else 'FAIL'}")
    print(f"MUST  calm gap among START_DIALS {calm_gap:.3f} < {MOVE_THRESHOLD:.3f}: "
          f"{'PASS' if calm_gap < MOVE_THRESHOLD else 'FAIL'}")
    print(f"SHOULD leader changes: best calm step {best_calm}, best aftermath step {best_after}: "
          f"{'PASS' if best_calm != best_after else 'FAIL'}")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    times = [b.time for b in bars[first : last + 1]]
    fig, ax = plt.subplots(figsize=(11, 5))
    for step in STEPS:
        ax.plot(times, E[step][first : last + 1], label=f"step {step} (H={H_MIN_BARS * 2**step})", linewidth=1)
    ax.axvline(bars[shock].time, color="black", linestyle="--", linewidth=1, label="shock")
    ax.set_ylabel("score E")
    ax.set_ylim(-0.02, 1.02)
    ax.set_title("Each strategy alone through the replay")
    ax.legend(loc="lower left", fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
