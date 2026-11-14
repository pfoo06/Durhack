"""Adviser tests (SPEC.md §13): move, no move, snap, revert, lost, alone, hysteresis."""

from datetime import datetime, timedelta, timezone

import numpy as np

from backend import config as C
from backend.adviser import Adviser, next_step
from backend.contracts import AdviserPacket, Bar, ClockPacket, Heard

T0 = datetime(2015, 1, 12, tzinfo=timezone.utc)
FIRST = C.STEP_FRACTION * 5.0  # dial after one move from 0 towards a leader at 5


def bars(n: int, seed: int = 0) -> list[Bar]:
    """Synthetic bars with correlated returns, enough to drive the finance engine."""
    rng = np.random.default_rng(seed)
    rF = rng.normal(0, 1e-3, n)
    rS = 0.9 * rF + rng.normal(0, 3e-4, n)
    return [
        Bar(k, T0 + timedelta(minutes=15 * k), 1.0, 1.0, 1.2, float(rS[k]), float(rF[k]), 0.9)
        for k in range(n)
    ]


def hear(adviser: Adviser, channel: int, score: float, dial: float, at: float) -> None:
    adviser.on_heard(Heard(AdviserPacket(channel, 0, score, dial), snr_db=20.0, received_at=at))


def advance(adviser: Adviser, n: int) -> None:
    """Process n bars while holding the adviser's own score fixed, so tests control the gap."""
    score = adviser.score
    for bar in bars(n):
        adviser.on_bar(bar)
    adviser.score = score


def test_move() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.6, 5.0, at=100.0)
    a.decide(100.0)
    assert a.dial == FIRST  # 0 + STEP_FRACTION · (5 − 0)
    assert a.trial is not None and a.state().in_trial


def test_move_changes_half_life() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.6, 5.0, at=100.0)
    a.decide(100.0)
    assert a.state().half_life_bars == C.H_MIN_BARS * 2.0**FIRST
    assert a._hedger.half_life_bars == C.H_MIN_BARS * 2.0**FIRST


def test_no_move_below_threshold() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.53, 5.0, at=100.0)
    a.decide(100.0)
    assert a.dial == 0.0 and a.trial is None


def test_snap() -> None:
    a = Adviser(0, 3.0)
    a.score = 0.5
    hear(a, 1, 0.6, 3.05, at=100.0)
    a.decide(100.0)
    assert a.dial == 3.05


def test_revert_and_blacklist() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.6, 5.0, at=100.0)
    a.decide(100.0)
    assert a.dial == FIRST

    advance(a, C.TRIAL_BARS)
    a.score = 0.4  # gap was 0.1, now 0.2: worse by 0.1 > REVERT_MARGIN
    hear(a, 1, 0.6, 5.0, at=103.0)
    a.decide(103.0)
    assert a.dial == 0.0 and a.trial is None
    assert a._hedger.half_life_bars == C.H_MIN_BARS

    # Blacklisted for BLACKLIST_S: its packets are ignored and it can't lead.
    hear(a, 1, 0.9, 5.0, at=106.0)
    a.decide(106.0)
    assert a.dial == 0.0
    assert a.state().leader_channel == 0

    # After the blacklist expires it can lead again.
    later = 103.0 + C.BLACKLIST_S + 1
    hear(a, 1, 0.9, 5.0, at=later)
    a.decide(later)
    assert a.dial == FIRST


def test_trial_kept_when_gap_holds() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.6, 5.0, at=100.0)
    a.decide(100.0)
    advance(a, C.TRIAL_BARS)
    a.score = 0.3  # the market fell for both: the gap is unchanged (D12)
    hear(a, 1, 0.4, 5.0, at=103.0)
    a.decide(103.0)
    # Kept, and the trial ended. The leader is still 0.1 ahead, so the same decide moves again (§7.3).
    assert a.dial == FIRST + C.STEP_FRACTION * (5.0 - FIRST)
    assert a.trial is not None and a.trial.old_dial == FIRST


def test_no_decision_during_trial() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.6, 5.0, at=100.0)
    a.decide(100.0)
    advance(a, C.TRIAL_BARS - 1)
    a.decide(103.0)
    assert a.dial == FIRST and a.trial is not None


def test_decide_rate_limited() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    a.decide(100.0)  # nothing heard yet
    hear(a, 1, 0.6, 5.0, at=100.5)
    a.decide(100.5)  # within DECISION_PERIOD_S: no action
    assert a.dial == 0.0
    a.decide(100.0 + C.DECISION_PERIOD_S)
    assert a.dial == FIRST


def test_lost_peer_is_not_leader() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.9, 5.0, at=100.0)
    a.decide(111.0)  # silent for 11 s > LOST_AFTER_S
    assert a.dial == 0.0
    s = a.state()
    assert s.leader_channel == 0 and s.heard == 0


def test_alone_never_moves() -> None:
    a = Adviser(2, 4.0)
    t = 0.0
    for bar in bars(1500):
        a.on_bar(bar)
        t += 1 / 8  # default speed: 8 bars per second
        a.decide(t)
    assert a.dial == 4.0 and a.trial is None


def test_ignores_self_and_clock_packets() -> None:
    a = Adviser(1, 0.0)
    hear(a, 1, 0.9, 5.0, at=100.0)
    a.on_heard(Heard(ClockPacket(0, 0, 500, 4), snr_db=20.0, received_at=100.0))
    assert a.peers == {}


def test_tie_goes_to_lowest_channel() -> None:
    a = Adviser(3, 5.0)
    a.score = 0.5
    hear(a, 2, 0.7, 4.0, at=100.0)
    hear(a, 1, 0.7, 3.0, at=100.0)
    assert a.state().leader_channel == 1


def test_hysteresis() -> None:
    assert next_step(2.55, 2) == 2
    assert next_step(2.61, 2) == 3
    assert next_step(1.39, 2) == 1


def test_packet_sequence_wraps() -> None:
    a = Adviser(0, 3.0)
    seqs = [a.packet().seq for _ in range(17)]
    assert seqs[:3] == [0, 1, 2] and seqs[15] == 15 and seqs[16] == 0
    p = a.packet()
    assert p.channel == 0 and p.dial == 3.0 and p.score == a.score


def test_on_bar_produces_state() -> None:
    a = Adviser(1, 3.0)
    for bar in bars(200):
        s = a.on_bar(bar)
    assert 0.0 <= s.score <= 1.0 and s.score > 0.5  # a correlated proxy hedges well
    assert 0.0 <= s.h <= 2.0
    assert s.step == 3 and s.half_life_bars == C.H_MIN_BARS * 8
    assert a.bars == 200


def test_snapshot_restore() -> None:
    a = Adviser(0, 0.0)
    for bar in bars(100):
        a.on_bar(bar)
    snap = a.snapshot()
    before = a.state()

    a.score = 0.5
    hear(a, 1, 0.9, 5.0, at=100.0)
    a.decide(100.0)
    for bar in bars(50, seed=1):
        a.on_bar(bar)

    a.restore(snap)
    assert a.state() == before
    assert a.peers == {} and a.trial is None
    a.restore(snap)  # reusable
    assert a.state() == before
