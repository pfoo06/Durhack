"""Shared replay clock (SPEC 9.4 / v1 7c). Positions are indices into `bars`."""
from datetime import datetime, timezone

from backend import config
from backend.contracts import Bar, ClockPacket, ClockStatus, Heard, Tick

MAX_CATCHUP_BARS = 200  # SPEC 4.7: one tick may return up to 200 bars
# Packet start to end of the last tone (the "1.54 s latency constant"); Heard.received_at is the latter.
PACKET_S = (config.TONE_MS * 10 + config.GAP_MS * 9) / 1000


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
        self._t = 0.0  # internal time, advanced by tick(dt)
        self._seq = 0
        self._reset_pending = False
        self._heard_at: float | None = None  # internal time of the last clock packet
        self._ref = (0.0, 0.0, 0)  # conductor (bar, internal time, speed step) at the last packet

    @property
    def status(self) -> ClockStatus:
        if self._conductor:
            return "conductor"
        if self._heard_at is not None and self._t - self._heard_at <= config.CLOCK_LOST_S:
            return "following"
        return "free"

    @property
    def speed_step(self) -> int:
        return self._step

    @property
    def position(self) -> int:
        return self._pos

    def start(self) -> None:
        self._paused = False

    def pause(self) -> None:
        self._paused = True

    def reset(self) -> None:
        """Back to REPLAY_START, paused; the next tick reports reset=True."""
        self._pos, self._acc, self._paused, self._reset_pending = self._first, 0.0, True, True

    def set_speed(self, step: int) -> None:
        self._step = max(0, min(step, len(config.SPEED_BARS_PER_S) - 1))

    def on_clock(self, heard: Heard, now: float) -> None:
        pkt = heard.packet
        if self._conductor or not isinstance(pkt, ClockPacket):
            return
        speed = config.SPEED_BARS_PER_S[pkt.speed_step]
        stale = (now - heard.received_at) + PACKET_S  # the bar was stamped at packet start
        self._ref = (pkt.bar + speed * stale, self._t, pkt.speed_step)
        self._heard_at = self._t
        self._step = pkt.speed_step
        self._paused = False  # a follower runs as soon as it hears the conductor

    def packet(self) -> ClockPacket:
        seq, self._seq = self._seq, (self._seq + 1) % 16
        return ClockPacket(channel=0, seq=seq, bar=min(self._pos, 4095), speed_step=self._step)

    def tick(self, dt: float) -> Tick:
        if self._reset_pending:
            self._reset_pending = False
            self._t += dt
            return Tick([], True)
        t0, self._t = self._t, self._t + dt
        if self._paused:
            return Tick([], False)
        rate = float(config.SPEED_BARS_PER_S[self._step])
        extra = 0
        if self.status == "following":
            bar, ref_t, step = self._ref
            err = bar + config.SPEED_BARS_PER_S[step] * (t0 - ref_t) - self._pos  # conductor minus us
            if err <= -config.RESET_BACK_BARS:
                # advisers restore to the warm state, so replay from the start up to the conductor's bar
                to = max(self._first, min(round(bar), self._last))
                self._pos, self._acc = to + 1, 0.0
                return Tick(self._bars[self._first : to + 1], True)
            if err < -config.FOLLOW_JUMP_BARS:
                rate = 0.0  # hold
            elif err > config.FOLLOW_JUMP_BARS:
                extra = int(err)  # catch up
            else:
                rate *= 1 + config.FOLLOW_TRIM * err / config.FOLLOW_JUMP_BARS  # trim
        self._acc += rate * dt
        n = int(self._acc)
        self._acc -= n
        n = max(0, min(n + extra, MAX_CATCHUP_BARS, self._last + 1 - self._pos))
        out = self._bars[self._pos : self._pos + n]
        self._pos += n
        return Tick(out, False)
