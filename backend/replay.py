"""Replay clock (SPEC 9.4). Positions are indices into `bars`. A 4-beat count-in starts every Mac; then each free-runs."""
from datetime import datetime, timezone

from backend import config
from backend.contracts import Bar, ClockStatus, Tick

MAX_CATCHUP_BARS = 200  # SPEC 4.7: one tick may return up to 200 bars


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


class Clock:
    def __init__(self, bars: list[Bar], conductor: bool) -> None:
        self._bars = bars
        self._conductor = conductor
        start, end = _stamp(config.REPLAY_START), _stamp(config.REPLAY_END)
        # bars before REPLAY_START are warm-up, not part of the replay
        self._first = next((k for k, b in enumerate(bars) if _utc(b.time) >= start), len(bars) - 1)
        self._last = max((k for k, b in enumerate(bars) if _utc(b.time) <= end), default=self._first)
        self._pos = self._first  # next bar to emit
        self._paused = True
        self._step = config.DEFAULT_SPEED_STEP
        self._acc = 0.0
        self._reset_pending = False
        self._count = 0.0  # conductor: seconds until beat 4
        self._count_due = False  # conductor: clicks not yet handed to the speaker

    @property
    def status(self) -> ClockStatus:
        return "conductor" if self._conductor else "free"

    @property
    def speed_step(self) -> int:
        return self._step

    @property
    def position(self) -> int:
        return self._pos

    def start(self) -> None:
        """From REPLAY_START at DEFAULT_SPEED_STEP. The conductor counts in first (see take_count_in); a follower
        calls this on hearing beat 4 (on_count_in)."""
        self.reset()
        self._step = config.DEFAULT_SPEED_STEP
        if self._conductor:
            self._count, self._count_due = (config.COUNT_IN_CLICKS - 1) * config.COUNT_IN_INTERVAL_S, True
        else:
            self._paused = False

    def take_count_in(self, lead: float = 0.0) -> bool:
        """True once per conductor start(): play the clicks now. `lead` = seconds of audio queued ahead of them."""
        due, self._count_due = self._count_due, False
        if due:
            self._count += lead
        return due

    def on_count_in(self, lag: float = 0.0) -> None:
        """A follower heard beat 4 `lag` seconds ago: start now, already `lag` seconds in."""
        if not self._conductor:
            self.start()
            self._acc = config.SPEED_BARS_PER_S[self._step] * lag

    def pause(self) -> None:
        self._paused, self._count, self._count_due = True, 0.0, False

    def reset(self) -> None:
        """Back to REPLAY_START, paused; the next tick reports reset=True."""
        self._pos, self._acc, self._reset_pending = self._first, 0.0, True
        self.pause()

    def set_speed(self, step: int) -> None:
        self._step = max(0, min(step, len(config.SPEED_BARS_PER_S) - 1))

    def tick(self, dt: float) -> Tick:
        reset, self._reset_pending = self._reset_pending, False
        if self._count > 0:
            self._count -= dt
            if self._count <= 0:  # beat 4: run, with the part of this tick past the beat already banked
                self._paused, self._acc = False, config.SPEED_BARS_PER_S[self._step] * -self._count
            return Tick([], reset)
        if reset or self._paused:
            return Tick([], reset)
        self._acc += float(config.SPEED_BARS_PER_S[self._step]) * dt
        n = int(self._acc)
        self._acc -= n
        n = max(0, min(n, MAX_CATCHUP_BARS, self._last + 1 - self._pos))
        out = self._bars[self._pos : self._pos + n]
        self._pos += n
        return Tick(out, False)
