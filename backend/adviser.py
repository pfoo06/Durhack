"""One FX hedging adviser: its strategy dial, what it hears, and when it moves (SPEC.md §7).

The finance maths lives in `finance.py` (P1). This module decides *which* half-life to use:
it remembers the other advisers it hears and steps its dial towards the leader (§7.3),
with trial and revert (§7.4).

Time (`now`, `received_at`) is whatever monotonic clock the caller uses: `time.monotonic()`
in the app, simulated seconds in `sim.py`. The adviser never reads the clock itself.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from backend import config as C
from backend.contracts import AdviserPacket, AdviserState, Bar, Heard
from backend.finance import Effectiveness, Hedger, PnL

# §8.3: the chord changes only when the dial is more than this far from the current step.
STEP_HYSTERESIS = 0.6
SEQ_MODULO = 16  # §9.2: the sequence number is one 4-bit symbol
# §9.2: 10 symbols of tone plus gap. A packet heard at `received_at` started this long before, so it
# carries the sender's state from at least this long ago.
PACKET_S = (C.TONE_MS + C.GAP_MS) * 10 / 1000


@dataclass
class Peer:
    """What this adviser last heard from another one (§7.2)."""

    dial: float
    score: float
    snr_db: float
    heard_at: float  # Heard.received_at of the last packet


@dataclass
class _Trial:
    """A dial move waiting to be judged (§7.4)."""

    old_dial: float
    leader: int
    gap_at_move: float
    bars_at_move: int


def half_life_bars(dial: float) -> float:
    """H = H_MIN_BARS · 2^dial (§6.2)."""
    return C.H_MIN_BARS * 2.0**dial


def next_step(dial: float, step: int) -> int:
    """The chord step for `dial`, given the current `step`, with hysteresis (§8.3)."""
    if abs(dial - step) > STEP_HYSTERESIS:
        return int(round(dial))
    return step


class Adviser:
    """The strategy logic for one Mac. Identified by its channel."""

    def __init__(self, channel: int, start_dial: float) -> None:
        self.channel = channel
        self.dial = self._clamp_dial(start_dial)
        self.step = int(round(self.dial))
        self.score = 1.0  # E; 1.0 until the first bar (nothing to hedge yet)
        self.peers: dict[int, Peer] = {}
        self.blacklist: dict[int, float] = {}  # channel → time the entry expires
        self.trial: _Trial | None = None
        # A leader seen ahead but not yet confirmed on a fresh packet: (channel, time first seen ahead).
        self.candidate: tuple[int, float] | None = None
        self.confirmed: int | None = None  # the leader whose lead was confirmed and still holds
        self.bars = 0  # bars processed so far, warm-up included
        self._now = 0.0  # latest time seen, from decide() or on_heard()
        self._last_decide: float | None = None
        self._seq = 0
        self._hedger = Hedger(half_life_bars(self.dial))
        self._effectiveness = Effectiveness(C.SCORE_WINDOW)
        self._pnl = PnL()
        self._pnl_pct = (0.0, 0.0)

    # ----- per bar -------------------------------------------------------------------------

    def on_bar(self, bar: Bar) -> AdviserState:
        """Process one bar of market data and return this adviser's state after it."""
        _, rH = self._hedger.update(bar)
        self.score = self._effectiveness.update(bar.rS, rH)
        self._pnl_pct = self._pnl.update(bar.rS, rH)
        self.bars += 1
        return self.state()

    def state(self) -> AdviserState:
        """A snapshot for the app, synth and UI, without processing a bar."""
        unhedged, hedged = self._pnl_pct
        return AdviserState(
            channel=self.channel,
            dial=self.dial,
            step=self.step,
            half_life_bars=half_life_bars(self.dial),
            h=self._hedger.h,
            score=self.score,
            pnl_unhedged_pct=unhedged,
            pnl_hedged_pct=hedged,
            leader_channel=self._leader(self._now)[0],
            heard=len(self._usable_peers(self._now)),
            in_trial=self.trial is not None,
        )

    # ----- hearing others ------------------------------------------------------------------

    def on_heard(self, heard: Heard) -> None:
        """Remember another adviser's latest packet (§7.2). Clock packets are not for us."""
        packet = heard.packet
        if not isinstance(packet, AdviserPacket):
            return
        self._now = max(self._now, heard.received_at)
        if packet.channel == self.channel or self._is_blacklisted(packet.channel, heard.received_at):
            return
        self.peers[packet.channel] = Peer(
            dial=packet.dial, score=packet.score, snr_db=heard.snr_db, heard_at=heard.received_at
        )

    def packet(self) -> AdviserPacket:
        """The next packet to transmit. The sequence number wraps at 16."""
        pkt = AdviserPacket(channel=self.channel, seq=self._seq, score=self.score, dial=self.dial)
        self._seq = (self._seq + 1) % SEQ_MODULO
        return pkt

    # ----- deciding ------------------------------------------------------------------------

    def decide(self, now: float) -> None:
        """Maybe move the dial towards the leader (§7.3). Acts at most once per DECISION_PERIOD_S."""
        self._now = max(self._now, now)
        if self._last_decide is not None and now - self._last_decide < C.DECISION_PERIOD_S:
            return
        self._last_decide = now

        if self.trial is not None:
            if self.bars - self.trial.bars_at_move < C.TRIAL_BARS:
                return  # 1. still waiting to judge the last move
            self._judge_trial(now)  # 2. the trial ends either way

        leader, leader_score, leader_dial = self._leader(now)  # 3.
        if leader == self.channel:  # 4.
            self.candidate = self.confirmed = None
            return
        gap = leader_score - self.score
        if gap < C.MOVE_THRESHOLD:  # 5. not worth moving
            self.candidate = self.confirmed = None
            return

        # 5b. A new leader's lead must hold on a packet it started sending after we first saw it ahead.
        # One packet can predate a market move: at the shock, our own score is already ~0 while the
        # packet we heard still carries the leader's pre-shock ~0.99. Once confirmed, keep following
        # that leader while it stays ahead.
        if leader != self.confirmed:
            if self.candidate is None or self.candidate[0] != leader:
                self.candidate, self.confirmed = (leader, now), None
                return
            if self.peers[leader].heard_at - PACKET_S <= self.candidate[1]:
                return  # no fresh packet from this leader yet: keep waiting
            self.candidate, self.confirmed = None, leader

        if abs(leader_dial - self.dial) <= C.SNAP_DISTANCE:  # 6.
            new_dial = leader_dial
        else:
            new_dial = self.dial + C.STEP_FRACTION * (leader_dial - self.dial)

        self.trial = _Trial(old_dial=self.dial, leader=leader, gap_at_move=gap, bars_at_move=self.bars)  # 7.
        self._set_dial(new_dial)

    def _judge_trial(self, now: float) -> None:
        """Keep the move unless the gap to the leader got worse by more than REVERT_MARGIN (§7.4, D12)."""
        trial = self.trial
        assert trial is not None
        self.trial = None
        peer = self.peers.get(trial.leader)
        if peer is None or self._is_lost(peer, now):
            return  # the leader went quiet: keep the move
        gap_now = peer.score - self.score
        if gap_now > trial.gap_at_move + C.REVERT_MARGIN:
            self._set_dial(trial.old_dial)
            self.blacklist[trial.leader] = now + C.BLACKLIST_S
            del self.peers[trial.leader]

    # ----- resets --------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Everything needed to come back to this exact point (taken right after warm-up)."""
        return copy.deepcopy(self.__dict__)

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Go back to a snapshot. The snapshot itself is left untouched, so it can be reused."""
        self.__dict__.update(copy.deepcopy(snapshot))

    # ----- helpers -------------------------------------------------------------------------

    def _set_dial(self, dial: float) -> None:
        self.dial = self._clamp_dial(dial)
        self.step = next_step(self.dial, self.step)
        self._hedger.set_half_life(half_life_bars(self.dial))

    @staticmethod
    def _clamp_dial(dial: float) -> float:
        return min(max(float(dial), 0.0), C.DIAL_MAX)

    @staticmethod
    def _is_lost(peer: Peer, now: float) -> bool:
        return now - peer.heard_at > C.LOST_AFTER_S

    def _is_blacklisted(self, channel: int, now: float) -> bool:
        return self.blacklist.get(channel, float("-inf")) > now

    def _usable_peers(self, now: float) -> dict[int, Peer]:
        """Peers that are neither lost nor blacklisted."""
        return {
            ch: p
            for ch, p in self.peers.items()
            if not self._is_lost(p, now) and not self._is_blacklisted(ch, now)
        }

    def _leader(self, now: float) -> tuple[int, float, float]:
        """(channel, score, dial) of the best candidate, self included. Ties → lowest channel."""
        candidates = [(self.channel, self.score, self.dial)]
        candidates += [(ch, p.score, p.dial) for ch, p in self._usable_peers(now).items()]
        return max(candidates, key=lambda c: (c[1], -c[0]))
