"""app.py: smoke test (SPEC §13) and the UI message shapes (SPEC §10.2)."""
import pytest

from backend import app
from backend.data import load_bars


@pytest.fixture(scope="module")
def bars():
    return load_bars()


def test_smoke(bars):
    assert app.run_smoke(bars)


def test_messages_match_protocol(bars):
    mac = app.Mac(bars, 1, conductor=False)
    hello = mac.hello()
    assert set(hello) == {"type", "channel", "conductor", "replayStart", "replayEnd", "shockTime", "speeds", "chords"}
    assert hello["conductor"] is False and len(hello["speeds"]) == 8 and len(hello["chords"]) == 7
    hist = mac.history["bars"]
    assert hist[0]["S"] == pytest.approx(100.0) and hist[0]["time"] == hello["replayStart"]
    state = mac.state_message()
    assert set(state) == {"type", "bar", "time", "speed", "paused", "clock", "adviser"}
    assert set(state["adviser"]) == {"channel", "dial", "step", "chord", "halfLifeHours", "h", "score",
                                     "pnlUnhedgedPct", "pnlHedgedPct", "leaderChannel", "heard", "inTrial"}
    assert state["adviser"]["halfLifeHours"] == pytest.approx(app.C.H_MIN_BARS * 2**3 * app.C.BAR_MINUTES / 60)


def test_controls(bars):
    follower = app.Mac(bars, 1, conductor=False)
    assert follower.clock.status == "free"  # no clock heard yet: controls allowed (§10.1)
    conductor = app.Mac(bars, 0, conductor=True)
    assert conductor.handle({"type": "speed", "step": 7}) is None
    assert conductor.handle({"type": "control", "action": "start"}) is None
    conductor.step(1.0, 0.0)
    assert conductor.bar - conductor.first + 1 == 64 and not conductor.paused
    assert conductor.handle({"type": "control", "action": "reset"}) is None
    conductor.step(0.05, 1.0)
    assert conductor.bar == conductor.first - 1 and conductor.paused
    assert conductor.handle({"type": "control", "action": "jump"}) is not None


def test_clock_packets_carry_own_channel(bars):
    mac = app.Mac(bars, 2, conductor=True)
    first, second = mac.next_packet(), mac.next_packet()
    assert first.channel == 2 and type(first).__name__ == "ClockPacket"
    assert second.channel == 2 and type(second).__name__ == "AdviserPacket"
