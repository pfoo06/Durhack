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
    assert set(state) == {"type", "bar", "time", "speed", "paused", "clock", "modem", "adviser", "peers"}
    assert state["peers"] == []
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


def test_only_adviser_packets_are_sent_while_paused(bars):
    mac = app.Mac(bars, 2)
    assert all(type(mac.next_packet()).__name__ == "AdviserPacket" for _ in range(3 * C.CLOCK_EVERY))


def test_running_mac_announces_its_position(bars):
    mac = app.Mac(bars, 2)
    mac.on_count_in()
    mac.step(0.05, 0.0)
    mac.step(1.0, 0.05)
    kinds = [type(mac.next_packet()).__name__ for _ in range(2 * C.CLOCK_EVERY)]
    assert kinds.count("ClockPacket") == 2 and kinds[C.CLOCK_EVERY - 1] == "ClockPacket"


def test_late_joiner_catches_up(bars):
    """Start pressed before the other Mac's detector has learned the noise floor: it misses the count-in, then
    joins from the position packets (late join, #35)."""
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB)
    room.macs[0].handle({"type": "control", "action": "start"})
    dt = 1 / app.C.LOOP_HZ
    while room.t < 20:
        room.step(dt)
    m0, m1 = room.macs
    assert m1.bar > m1.first and not m1.paused
    assert abs(m0.bar - m1.bar) <= C.RESYNC_BARS


def test_paused_mac_stays_held(bars):
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB)
    dt = 1 / app.C.LOOP_HZ
    room.macs[1].handle({"type": "control", "action": "pause"})
    room.macs[0].handle({"type": "control", "action": "start"})
    while room.t < 20:
        room.step(dt)
    assert room.macs[1].paused and room.macs[1].bar == room.macs[1].first - 1


def test_smoke_melody(bars):
    assert app.run_smoke(bars, modem_mode="melody")


def test_modem_switch_is_open_to_macs(bars):
    mac = app.Mac(bars, 1)
    assert mac.state_message()["modem"] == "melody"  # the quiet melody is the default (C.DEFAULT_MODEM)
    assert mac.handle({"type": "modem", "mode": "pilot"}) is None and mac.state_message()["modem"] == "pilot"
    assert mac.handle({"type": "modem", "mode": "melody"}) is None and mac.modem == "melody"
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


def test_state_lists_the_peers_it_hears(bars):
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB)
    dt = 1 / app.C.LOOP_HZ
    while room.t < 1.5:
        room.step(dt)
    room.macs[0].handle({"type": "control", "action": "start"})
    while room.t < 12:
        room.step(dt)
    peers = room.macs[1].state_message()["peers"]
    assert [p["channel"] for p in peers] == [0]
    assert set(peers[0]) == {"channel", "dial", "score", "ageS"} and 0 <= peers[0]["ageS"] <= app.C.LOST_AFTER_S


@pytest.mark.parametrize("kind", ["pilot", "melody"])
def test_heard_packets_carry_their_modem_length(kind):
    """A position must be aged by the modem it arrived on: melody packets are shorter than pilot ones (#35)."""
    import numpy as np
    from backend.audio import melody, modem
    from backend.contracts import ClockPacket
    enc, packet_s = (modem.encode, modem.PACKET_S) if kind == "pilot" else (melody.encode, melody.PACKET_S)
    lead = int(0.5 * C.SAMPLE_RATE)
    audio = np.concatenate([np.zeros(lead, np.float32), enc(ClockPacket(0, 3, 100, 1)), np.zeros(C.SAMPLE_RATE, np.float32)])
    ears, got = app.Ears(1), []
    for a in range(0, len(audio), C.BLOCK):
        got += ears.feed_timed(audio[a : a + C.BLOCK], a / C.SAMPLE_RATE)
    assert len(got) == 1
    heard, s = got[0]
    assert s == packet_s and heard.packet.bar == 100
    assert abs(heard.received_at - (0.5 + packet_s)) < 0.05  # received_at is packet start + its modem's length


def test_melody_late_joiner_shares_the_turn_clock(bars):
    """Melody, Start pressed before the other Mac can hear the count-in: once it joins, its turns line up with
    the room's, so both Macs keep hearing each other (whole-project review, must fix)."""
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB, modem_mode="melody")
    m0, m1 = room.macs
    m0.handle({"type": "control", "action": "start"})
    dt = 1 / app.C.LOOP_HZ
    while m1.paused and room.t < 40:
        room.step(dt)
    assert not m1.paused
    before = [d.stats["packets"] for d in room.decoders]
    end = room.t + 40
    while room.t < end:
        room.step(dt)
    assert abs(m1.slot_t0 - m0.slot_t0) < 0.3  # inside the 0.3 s window a turn may start in
    assert all(d.stats["packets"] - b >= 3 for d, b in zip(room.decoders, before))


def test_reset_shows_the_restored_adviser_at_once(bars):
    """After Reset the screen and synth must show the warmed-up adviser, not the last bar before the reset."""
    mac = app.Mac(bars, 0)
    warm_score = mac.state.score
    mac.on_count_in()
    mac.step(0.05, 0.0)
    mac.step(60.0, 0.05)  # well past the shock
    assert mac.state.score < warm_score
    mac.handle({"type": "control", "action": "reset"})
    mac.step(0.05, 60.1)
    assert mac.paused and mac.state.score == warm_score
    assert mac.state_message()["adviser"]["score"] == round(warm_score, 4)


CYCLE = 4 * C.MELODY_SLOT_S


def _phase(a, b) -> float:
    return ((a.slot_t0 - b.slot_t0 + CYCLE / 2) % CYCLE) - CYCLE / 2


def _melody_room(bars, starter: int):
    room = app.LoopbackRoom(bars, 0.0, app.C.CHORD_GAIN_DB, app.C.PILOT_GAIN_DB, modem_mode="melody")
    room.macs[starter].handle({"type": "control", "action": "start"})  # before the other can hear the count-in
    while room.macs[1 - starter].paused and room.t < 40:
        room.step(1 / app.C.LOOP_HZ)
    return room


def _packets_over(room, seconds: float) -> list[int]:
    before = [d.stats["packets"] for d in room.decoders]
    end = room.t + seconds
    while room.t < end:
        room.step(1 / app.C.LOOP_HZ)
    return [d.stats["packets"] - b for d, b in zip(room.decoders, before)]


def test_melody_turns_align_when_the_higher_channel_started_first(bars):
    """Channel 1 starts, channel 0 joins late: channel 1 lines its turns up with channel 0, the reference."""
    room = _melody_room(bars, starter=1)
    got = _packets_over(room, 40)
    assert abs(_phase(*room.macs)) < 2 * C.MELODY_ALIGN_S
    assert all(n >= 3 for n in got)


def test_melody_turns_realign_after_a_restart(bars):
    room = _melody_room(bars, starter=0)
    _packets_over(room, 15)
    room.macs[1].handle({"type": "control", "action": "start"})  # restarts its own turn clock from now
    _packets_over(room, 15)
    got = _packets_over(room, 40)
    assert abs(_phase(*room.macs)) < 2 * C.MELODY_ALIGN_S
    assert all(n >= 3 for n in got)


def test_melody_peers_never_look_lost(bars):
    """A clock turn leaves 2 cycles (11.2 s) between adviser packets; LOST_AFTER_S must cover it."""
    room = _melody_room(bars, starter=0)
    _packets_over(room, 15)  # both have heard each other at least once
    dt, empty = 1 / app.C.LOOP_HZ, 0
    end = room.t + 60
    while room.t < end:
        room.step(dt)
        empty += sum(1 for m in room.macs if not m.state_message()["peers"])
    assert empty == 0
