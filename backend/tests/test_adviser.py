"""Adviser tests (SPEC.md §13): move, no move, snap, revert, lost, alone, hysteresis."""

from datetime import datetime, timedelta, timezone

import numpy as np

from backend import config as C
from backend.adviser import PACKET_S, Adviser, next_step
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


def lead(adviser: Adviser, channel: int, score: float, dial: float, at: float) -> float:
    """A peer leads on two decisions: heard and decided at `at` (it becomes the candidate), then a fresh
    packet is heard and the adviser decides again. Returns the time of the second decision."""
    hear(adviser, channel, score, dial, at)
    adviser.decide(at)
    t2 = at + max(C.DECISION_PERIOD_S, PACKET_S) + 0.1
    hear(adviser, channel, score, dial, t2)
    adviser.decide(t2)
    return t2


def advance(adviser: Adviser, n: int) -> None:
    """Process n bars while holding the adviser's own score fixed, so tests control the gap."""
    score = adviser.score
    for bar in bars(n):
        adviser.on_bar(bar)
    adviser.score = score


def test_move() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    lead(a, 1, 0.6, 5.0, at=100.0)
    assert a.dial == FIRST  # 0 + STEP_FRACTION · (5 − 0)
    assert a.trial is not None and a.state().in_trial


def test_move_changes_half_life() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    lead(a, 1, 0.6, 5.0, at=100.0)
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
    lead(a, 1, 0.6, 3.05, at=100.0)
    assert a.dial == 3.05


def test_revert_and_blacklist() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    lead(a, 1, 0.6, 5.0, at=100.0)
    assert a.dial == FIRST

    advance(a, C.TRIAL_BARS)
    a.score = 0.4  # gap was 0.1, now 0.2: worse by 0.1 > REVERT_MARGIN
    hear(a, 1, 0.6, 5.0, at=105.0)
    a.decide(105.0)
    assert a.dial == 0.0 and a.trial is None
    assert a._hedger.half_life_bars == C.H_MIN_BARS

    # Blacklisted for BLACKLIST_S: its packets are ignored and it can't lead.
    hear(a, 1, 0.9, 5.0, at=108.0)
    a.decide(108.0)
    assert a.dial == 0.0
    assert a.state().leader_channel == 0

    # After the blacklist expires it can lead again (confirmed on a fresh packet, like any lead).
    lead(a, 1, 0.9, 5.0, at=105.0 + C.BLACKLIST_S + 1)
    assert a.dial == FIRST


def test_trial_kept_when_gap_holds() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    lead(a, 1, 0.6, 5.0, at=100.0)
    advance(a, C.TRIAL_BARS)
    a.score = 0.3  # the market fell for both: the gap is unchanged (D12)
    hear(a, 1, 0.4, 5.0, at=105.0)
    a.decide(105.0)
    # Kept, and the trial ended. The confirmed leader is still 0.1 ahead, so the same decide moves again (§7.3).
    assert a.dial == FIRST + C.STEP_FRACTION * (5.0 - FIRST)
    assert a.trial is not None and a.trial.old_dial == FIRST


def test_no_decision_during_trial() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    lead(a, 1, 0.6, 5.0, at=100.0)
    advance(a, C.TRIAL_BARS - 1)
    a.decide(105.0)
    assert a.dial == FIRST and a.trial is not None


def test_decide_rate_limited() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    a.decide(100.0)  # nothing heard yet
    hear(a, 1, 0.6, 5.0, at=100.5)
    a.decide(100.5)  # within DECISION_PERIOD_S: no action
    assert a.dial == 0.0
    a.decide(100.0 + C.DECISION_PERIOD_S)  # the leader becomes the candidate: no move yet
    assert a.dial == 0.0 and a.candidate == (1, 100.0 + C.DECISION_PERIOD_S)
    fresh = 100.0 + 2 * C.DECISION_PERIOD_S + 0.1
    hear(a, 1, 0.6, 5.0, at=fresh)
    a.decide(fresh)
    assert a.dial == FIRST


def test_stale_packet_at_shock_does_not_move() -> None:
    """At the shock our own score collapses while the last packet heard still carries the leader's
    pre-shock score. The next fresh packet shows the leader collapsed too, so nobody moves."""
    a = Adviser(0, 0.0)
    a.score = 0.0  # our own score, just after the shock bar
    hear(a, 1, 0.99, 3.0, at=100.0)  # sent before the shock
    a.decide(100.0)
    assert a.dial == 0.0 and a.candidate == (1, 100.0)
    fresh = 100.0 + max(C.DECISION_PERIOD_S, PACKET_S) + 0.1
    hear(a, 1, 0.0, 3.0, at=fresh)  # sent after: the leader crashed too
    a.decide(fresh)
    assert a.dial == 0.0 and a.trial is None and a.candidate is None


def test_lead_needs_a_packet_started_after_it_was_first_seen() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.6, 5.0, at=100.0)
    a.decide(100.0)
    # Heard after the first decision, but it started before it (heard_at − PACKET_S ≤ 100): not fresh.
    hear(a, 1, 0.6, 5.0, at=100.0 + PACKET_S - 0.1)
    a.decide(100.0 + C.DECISION_PERIOD_S)
    assert a.dial == 0.0
    fresh = 100.0 + 2 * C.DECISION_PERIOD_S  # a full packet after the first decision, and outside the rate limit
    hear(a, 1, 0.6, 5.0, at=fresh)
    a.decide(fresh)
    assert a.dial == FIRST


def test_confirmation_is_needed_again_after_the_lead_ends() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    t = lead(a, 1, 0.6, 5.0, at=100.0)
    assert a.dial == FIRST and a.confirmed == 1
    advance(a, C.TRIAL_BARS)
    t += C.DECISION_PERIOD_S
    hear(a, 1, 0.52, 5.0, at=t)  # the lead shrinks under MOVE_THRESHOLD
    a.decide(t)
    assert a.confirmed is None
    t += C.DECISION_PERIOD_S
    hear(a, 1, 0.9, 5.0, at=t)  # ahead again: a new candidate, not an immediate move
    a.decide(t)
    assert a.dial == FIRST and a.candidate == (1, t)


def test_lost_peer_is_not_leader() -> None:
    a = Adviser(0, 0.0)
    a.score = 0.5
    hear(a, 1, 0.9, 5.0, at=100.0)
    a.decide(100.0 + C.LOST_AFTER_S + 1)  # silent for longer than LOST_AFTER_S
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


# ----- exploration (§7.5a) -----------------------------------------------------------------


def test_explores_when_struggling_with_nobody_to_follow(monkeypatch) -> None:
    monkeypatch.setattr(C, "EXPLORE_PROB", 1.0)
    a = Adviser(1, 3.0)
    a.score = 0.0
    hear(a, 2, 0.0, 4.0, at=100.0)  # a peer, but nobody is ahead
    a.decide(100.0)
    assert abs(abs(a.dial - 3.0) - C.EXPLORE_STEP) < 1e-9
    assert a.trial is not None and a.trial.explore and a.trial.leader == 2


def test_no_exploration_while_scoring_well(monkeypatch) -> None:
    monkeypatch.setattr(C, "EXPLORE_PROB", 1.0)
    a = Adviser(1, 3.0)
    a.score = C.EXPLORE_BELOW
    hear(a, 2, C.EXPLORE_BELOW, 4.0, at=100.0)
    a.decide(100.0)
    assert a.dial == 3.0 and a.trial is None


def test_no_exploration_alone(monkeypatch) -> None:
    monkeypatch.setattr(C, "EXPLORE_PROB", 1.0)
    a = Adviser(1, 3.0)
    a.score = 0.0
    a.decide(100.0)
    assert a.dial == 3.0 and a.trial is None


def test_bad_exploration_reverts_without_blacklisting(monkeypatch) -> None:
    monkeypatch.setattr(C, "EXPLORE_PROB", 1.0)
    a = Adviser(1, 3.0)
    a.score = 0.0
    hear(a, 2, 0.0, 4.0, at=100.0)
    a.decide(100.0)
    monkeypatch.setattr(C, "EXPLORE_PROB", 0.0)
    advance(a, C.TRIAL_BARS)
    hear(a, 2, 0.2, 4.0, at=102.5)  # the peer is now 0.2 ahead: the try made us fall behind
    a.decide(102.5)
    assert a.dial == 3.0 and a.trial is None
    assert 2 in a.peers and not a.blacklist
