"""VirtualRoom and offline simulation tests (SPEC.md §4.8, §7.6)."""

from backend import config as C
from backend import sim
from backend.contracts import AdviserPacket
from backend.mocks import VirtualRoom


def packet(channel: int = 0, score: float = 0.5, dial: float = 3.0) -> AdviserPacket:
    return AdviserPacket(channel=channel, seq=0, score=score, dial=dial)


def test_room_delivers_to_others_after_delay() -> None:
    room = VirtualRoom(loss=0.0, delay_s=(1.6, 2.0), channels=range(4))
    room.send(packet(channel=1), now=10.0)
    assert room.receive(11.5) == []  # still on the air
    got = room.receive(12.0)
    assert sorted(ch for ch, _ in got) == [0, 2, 3]  # never back to the sender
    assert all(11.6 <= h.received_at <= 12.0 for _, h in got)
    assert room.receive(100.0) == []  # delivered once only


def test_room_total_loss_delivers_nothing() -> None:
    room = VirtualRoom(loss=1.0)
    room.send(packet(), now=0.0)
    assert room.receive(100.0) == []


def test_room_loss_rate() -> None:
    room = VirtualRoom(loss=0.1, channels=range(2), seed=3)
    for k in range(2000):
        room.send(packet(channel=0), now=float(k))
    heard = len(room.receive(1e9))
    assert 0.87 < heard / 2000 < 0.93


def test_room_rounds_like_the_modem() -> None:
    room = VirtualRoom(loss=0.0, channels=range(2))
    room.send(packet(channel=0, score=0.123456, dial=2.345678), now=0.0)
    (_, heard), = room.receive(10.0)
    assert heard.packet.score == round(0.123456 * 255) / 255
    assert heard.packet.dial == round(2.345678 / C.DIAL_MAX * 255) / 255 * C.DIAL_MAX


def test_synthetic_data_has_a_shock() -> None:
    bars = sim.synthetic_bars()
    shock_bar = bars[sim.shock_index([b.time for b in bars])]
    assert shock_bar.time <= sim.utc(C.SHOCK_TIME) < shock_bar.time + sim.timedelta(minutes=C.BAR_MINUTES)
    assert abs(shock_bar.rS) > 0.03
    assert max(bars, key=lambda b: abs(b.rS)) is shock_bar


def test_simulation_passes_on_synthetic_data() -> None:
    bars = sim.synthetic_bars()
    run = sim.simulate(bars, 4, C.DEFAULT_SPEED_STEP, loss=0.1)
    fixed = sim.simulate(bars, 4, C.DEFAULT_SPEED_STEP, loss=None)
    s = sim.summarise(run, fixed)
    assert s.calm_held, s
    assert s.converged, s
    assert s.helped, s


def test_without_hearing_dials_stay_fixed() -> None:
    run = sim.simulate(sim.synthetic_bars(), 4, C.DEFAULT_SPEED_STEP, loss=None)
    assert run.dials[0] == run.dials[-1] == [float(d) for d in C.START_DIALS]
