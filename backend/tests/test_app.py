"""app.py: smoke test (SPEC §13) and the UI message shapes (SPEC §10.2)."""
import pytest

from backend import app
from backend import config as C
from backend.data import load_bars

DEFAULT_BARS = int(C.SPEED_BARS_PER_S[C.DEFAULT_SPEED_STEP])  # bars in 1 s at the default speed


@pytest.fixture(scope="module")
def bars():
    return load_bars()


def test_smoke(bars):
    assert app.run_smoke(bars)


def test_messages_match_protocol(bars):
    mac = app.Mac(bars, 1)
    hello = mac.hello()
    assert set(hello) == {"type", "channel", "replayStart", "replayEnd", "shockTime", "speeds", "chords"}
    assert len(hello["speeds"]) == 8 and len(hello["chords"]) == 7
    hist = mac.history["bars"]
    assert hist[0]["S"] == pytest.approx(100.0) and hist[0]["time"] == hello["replayStart"]
    state = mac.state_message()
    assert set(state) == {"type", "bar", "time", "speed", "paused", "clock", "modem", "adviser"}
    assert set(state["adviser"]) == {"channel", "dial", "step", "chord", "halfLifeHours", "h", "score",
                                     "pnlUnhedgedPct", "pnlHedgedPct", "leaderChannel", "heard", "inTrial"}
    assert state["adviser"]["halfLifeHours"] == pytest.approx(app.C.H_MIN_BARS * 2**3 * app.C.BAR_MINUTES / 60)


def test_controls(bars):
    mac = app.Mac(bars, 0)
    assert mac.handle({"type": "speed", "step": 7}) is None
    assert mac.handle({"type": "control", "action": "start"}) is None
    assert mac.clock.take_count_in()
    mac.step(0.05, 0.0)
    mac.step(1.5, 0.05)  # through the count-in
    mac.step(1.0, 1.55)
    assert mac.bar - mac.first + 1 == DEFAULT_BARS and not mac.paused  # default speed, not 7
    assert mac.handle({"type": "control", "action": "reset"}) is None
    mac.step(0.05, 2.6)
    assert mac.bar == mac.first - 1 and mac.paused
    assert mac.handle({"type": "control", "action": "jump"}) is not None


def test_starts_on_heard_count_in(bars):
    mac = app.Mac(bars, 1)
    mac.on_count_in()
    mac.step(0.05, 0.0)
    mac.step(1.0, 0.05)
    assert mac.bar - mac.first + 1 == DEFAULT_BARS and not mac.paused and mac.state_message()["clock"] == "free"


def test_only_adviser_packets_are_sent(bars):
    mac = app.Mac(bars, 2)
    assert all(type(mac.next_packet()).__name__ == "AdviserPacket" for _ in range(3))


def test_smoke_melody(bars):
    assert app.run_smoke(bars, modem_mode="melody")


def test_modem_switch_is_open_to_macs(bars):
    mac = app.Mac(bars, 1)
    assert mac.state_message()["modem"] == "pilot"
    assert mac.handle({"type": "modem", "mode": "melody"}) is None and mac.state_message()["modem"] == "melody"
    assert mac.handle({"type": "modem", "mode": "pilot"}) is None and mac.modem == "pilot"
    assert mac.handle({"type": "modem", "mode": "x"}) is not None


def test_melody_turns(bars):
    mac = app.Mac(bars, 2, modem_mode="melody")
    assert not mac.melody_due(2, 5.0)  # no replay yet
    mac.slot_t0 = 10.0
    slot = app.C.MELODY_SLOT_S
    assert not mac.melody_due(2, 10.0 + slot)  # channel 1's turn
    assert mac.melody_due(2, 10.0 + 2 * slot + 0.05) and not mac.melody_due(2, 10.0 + 2 * slot + 0.1)  # once per turn
    assert not mac.melody_due(2, 10.0 + 2 * slot + 0.9)  # too late in the slot: skip it
    assert mac.melody_due(2, 10.0 + 6 * slot + 0.05)  # the next cycle


def test_mixed_modems_hear_each_other(bars):
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB, "melody")
    room.macs[1].modem = "pilot"
    dt = 1 / app.C.LOOP_HZ
    while room.t < 1.5:
        room.step(dt)
    room.macs[0].handle({"type": "control", "action": "start"})
    while room.t < 25:
        room.step(dt)
    assert all(d.stats["packets"] >= 3 for d in room.decoders)


def test_either_mac_can_start_the_room(bars):
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB)
    dt = 1 / app.C.LOOP_HZ
    while room.t < 1.5:
        room.step(dt)
    room.macs[1].handle({"type": "control", "action": "start"})  # the higher channel starts it
    while room.t < 6:
        room.step(dt)
    assert abs(room.macs[0].bar - room.macs[1].bar) <= 1 and room.macs[0].bar > room.macs[0].first
