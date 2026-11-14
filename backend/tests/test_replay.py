from datetime import datetime, timedelta, timezone

from backend.contracts import Bar, ClockPacket, Heard
from backend.replay import PACKET_S, Clock

STALE_BARS = 8 * PACKET_S  # bars the conductor moves while a step-4 packet is in flight


def make_bars() -> list[Bar]:
    t0 = datetime(2015, 1, 12, tzinfo=timezone.utc) - timedelta(minutes=15 * 10)  # 10 warm-up bars
    return [Bar(k, t0 + timedelta(minutes=15 * k), 1.0, 1.0, 1.0, 0.0, 0.0, 0.0) for k in range(1200)]


def follower_hearing(error: float, step: int = 4) -> Clock:
    """A running follower whose conductor estimate is `error` bars ahead of it (negative: behind)."""
    c = Clock(make_bars(), conductor=False)
    c.set_speed(step)
    c.start()
    c.tick(30.0)  # nothing heard yet, runs free: plenty of room both ways
    bar = c.position + error - STALE_BARS
    c.on_clock(Heard(ClockPacket(0, 0, round(bar), step), 20.0, 100.0), 100.0)
    return c


def test_starts_at_replay_start_paused() -> None:
    c = Clock(make_bars(), conductor=True)
    assert c.position == 10 and c.status == "conductor"
    assert c.tick(1.0).bars == []


def test_speed() -> None:
    c = Clock(make_bars(), conductor=True)
    c.set_speed(4)
    c.start()
    assert len(c.tick(1.0).bars) == 8


def test_packet_seq_wraps() -> None:
    c = Clock(make_bars(), conductor=True)
    assert [c.packet().seq for _ in range(17)][-2:] == [15, 0]


def test_follow_catch_up() -> None:
    t = follower_hearing(+20).tick(1.0)
    assert not t.reset and len(t.bars) >= 20


def test_follow_hold() -> None:
    t = follower_hearing(-20).tick(1.0)
    assert not t.reset and t.bars == []


def test_follow_trim() -> None:
    t = follower_hearing(+3).tick(5.0)
    assert not t.reset and len(t.bars) > 8 * 5


def test_follow_reset() -> None:
    c = follower_hearing(-200)
    t = c.tick(0.1)
    assert t.reset and t.bars[0].i == 10 and c.position == t.bars[-1].i + 1


def test_lost_goes_free_keeps_speed() -> None:
    c = follower_hearing(0, step=5)
    assert c.status == "following"
    for _ in range(11):
        c.tick(1.0)
    assert c.status == "free" and c.speed_step == 5
