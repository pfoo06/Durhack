"""Replay clock (SPEC 9.4). Positions are indices into `bars`. Any Mac can play a 4-beat count-in; every Mac starts on
beat 4, then each free-runs. Running Macs also announce their position, so a Mac that missed the count-in joins the
room, and one that drifts more than RESYNC_BARS away from the room catches up or holds (late join, §9.4a)."""
from statistics import median
from datetime import datetime, timezone

from backend import config
from backend.contracts import Bar, ClockStatus, Tick

MAX_CATCHUP_BARS = 200  # SPEC 4.7: one tick may return up to 200 bars


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _stamp(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


class Clock:
    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars
        start, end = _stamp(config.REPLAY_START), _stamp(config.REPLAY_END)
        # bars before REPLAY_START are warm-up, not part of the replay
        self._first = next((k for k, b in enumerate(bars) if _utc(b.time) >= start), len(bars) - 1)
        self._last = max((k for k, b in enumerate(bars) if _utc(b.time) <= end), default=self._first)
        self._pos = self._first  # next bar to emit
        self._paused = True
        self._step = config.DEFAULT_SPEED_STEP
        self._acc = 0.0
        self._reset_pending = False
        self._count = 0.0  # own count-in: seconds until beat 4
        self._count_due = False  # own clicks not yet handed to the speaker
        self._deaf = 0.0  # seconds left in which a heard count-in is our own echo
        self._t = 0.0  # seconds of tick() time, for ageing the positions we hear
        self._room: dict[int, tuple[float, float]] = {}  # channel -> (its position estimate, our _t when heard)
        self._held = False  # paused by this Mac's own user: don't join the room until Start or Reset

    @property
    def status(self) -> ClockStatus:
        return "free"

    @property
    def speed_step(self) -> int:
        return self._step

    @property
    def position(self) -> int:
        return self._pos

    def start(self) -> None:
        """Play a count-in: from REPLAY_START at DEFAULT_SPEED_STEP, running on beat 4 (see take_count_in)."""
        self.reset()
        self._step = config.DEFAULT_SPEED_STEP
        self._count, self._count_due = (config.COUNT_IN_CLICKS - 1) * config.COUNT_IN_INTERVAL_S, True
        self._deaf = self._count + config.COUNT_IN_DEAF_S

    def take_count_in(self, lead: float = 0.0) -> bool:
        """True once per start(): play the clicks now. `lead` = seconds of audio queued ahead of them."""
        due, self._count_due = self._count_due, False
        if due:
            self._count += lead
            self._deaf += lead
        return due

    def on_count_in(self, lag: float = 0.0) -> bool:
        """Heard beat 4 `lag` seconds ago: start now, already `lag` seconds in. False if ignored: our own echo, or we
        are mid-run (a stray noise must not restart a running replay; Reset or Pause this Mac to take a new count-in)."""
        if self._deaf > 0 or (not self._paused and self._pos <= self._last):
            return False
        self.reset()
        self._step, self._paused = config.DEFAULT_SPEED_STEP, False
        self._acc = config.SPEED_BARS_PER_S[self._step] * lag
        return True

    def pause(self) -> None:
        self._paused, self._count, self._count_due = True, 0.0, False

    def hold(self) -> None:
        """Pause from this Mac's own UI: stays paused even while it hears the room running, until Start or Reset."""
        self.pause()
        self._held = True

    def reset(self) -> None:
        """Back to REPLAY_START, paused; the next tick reports reset=True."""
        self._pos, self._acc, self._reset_pending = self._first, 0.0, True
        self._room, self._held = {}, False
        self.pause()

    def on_heard_bar(self, channel: int, bar: int, speed_step: int, age_s: float) -> bool:
        """Another Mac said it was at `bar`, `age_s` seconds ago, at `speed_step` (§9.4a). Returns True if this
        joins a running room from paused. Ignored while counting in or held."""
        if self._count > 0 or self._held:
            return False
        step = max(0, min(speed_step, len(config.SPEED_BARS_PER_S) - 1))
        self._room[channel] = (bar + config.SPEED_BARS_PER_S[step] * age_s, self._t)
        if self._paused and config.SPEED_BARS_PER_S[step] > 0:
            self._step, self._paused, self._acc = step, False, 0.0
            return True
        return False

    def room_position(self) -> float | None:
        """Median of where the Macs we heard recently should be now, or None if we've heard none."""
        speed = config.SPEED_BARS_PER_S[self._step]
        now = [est + speed * (self._t - at) for est, at in self._room.values() if self._t - at <= config.LOST_AFTER_S]
        return median(now) if now else None

    def set_speed(self, step: int) -> None:
        self._step = max(0, min(step, len(config.SPEED_BARS_PER_S) - 1))

    def tick(self, dt: float) -> Tick:
        reset, self._reset_pending = self._reset_pending, False
        self._t += dt
        self._deaf = max(0.0, self._deaf - dt)
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
        room = self.room_position()
        if room is not None:  # §9.4a: stay within RESYNC_BARS of the room
            if self._pos - room > config.RESYNC_BARS:
                n, self._acc = 0, 0.0  # ahead: hold until the room catches up (bars are never un-processed)
            elif room - self._pos > config.RESYNC_BARS:
                n = max(n, int(room - self._pos))  # behind, or just joined: catch up now
        n = max(0, min(n, MAX_CATCHUP_BARS, self._last + 1 - self._pos))
        out = self._bars[self._pos : self._pos + n]
        self._pos += n
        return Tick(out, False)
