import numpy as np
import pytest

from backend import config as C
from backend.audio import modem
from backend.contracts import AdviserPacket, ClockPacket
from backend.mocks import VirtualAir

TAIL = np.zeros(C.SAMPLE_RATE // 2, np.float32)


def decode(ch: int, audio: np.ndarray, t0: float = 100.0, block: int = 4800):
    d = modem.Decoder(ch)
    out = []
    audio = np.concatenate([audio, TAIL])
    for a in range(0, len(audio), block):
        out += d.feed(audio[a : a + block], t0 + a / C.SAMPLE_RATE)
    return out


def test_crc():
    assert modem.crc8(b"123456789") == 0xF4


EDGE = [
    lambda c: AdviserPacket(c, 0, 0.0, 0.0),
    lambda c: AdviserPacket(c, 15, 1.0, 6.0),
    lambda c: AdviserPacket(c, 7, 0.5, 3.0),
    lambda c: ClockPacket(c, 0, 0, 0),
    lambda c: ClockPacket(c, 15, 4095, 7),
    lambda c: ClockPacket(c, 3, 1234, 4),
]


@pytest.mark.parametrize("ch", range(4))
def test_round_trip(ch):
    own = (ch + 1) % 4
    for make in EDGE:
        p = make(ch)
        heard = decode(own, modem.encode(p))
        assert len(heard) == 1
        got = heard[0].packet
        assert type(got) is type(p) and (got.channel, got.seq) == (p.channel, p.seq)
        if isinstance(p, ClockPacket):
            assert got == p
        else:
            assert abs(got.score - p.score) <= 0.5 / 255 and abs(got.dial - p.dial) <= 3 / 255


def test_encode_shape():
    a = modem.encode(AdviserPacket(0, 1, 0.3, 2.0))
    assert a.dtype == np.float32 and a.ndim == 1 and abs(np.abs(a).max() - 1.0) < 1e-6
    assert len(a) == int(1.9 * C.SAMPLE_RATE) and not a[-int(0.29 * C.SAMPLE_RATE) :].any()


def test_noise_0db():
    air = VirtualAir(snr_db=0.0, seed=1)
    rng = np.random.default_rng(2)
    d = modem.Decoder(0)
    good = wrong = 0
    for n in range(200):
        ch = int(rng.integers(1, 4))
        p = AdviserPacket(ch, n % 16, int(rng.integers(0, 256)) / 255, int(rng.integers(0, 256)) / 255 * 6)
        heard = d.feed(air.mix([modem.encode(p)]), float(n))
        for h in heard:
            if h.packet == p:
                good += 1
            else:
                wrong += 1
    assert wrong == 0 and good >= 190


def test_corruption():
    p = AdviserPacket(1, 3, 0.5, 3.0)
    for j in range(2, 10):
        s = modem.symbols(p)
        s[j] = (s[j] + 5) % 16
        # re-synthesise with one tone changed, CRC left stale
        a = np.zeros(10 * modem._SYM + C.SAMPLE_RATE // 2)
        t = np.arange(modem._TONE) / C.SAMPLE_RATE
        for i, k in enumerate(s):
            f = modem._bin(1, k) * C.SAMPLE_RATE / C.FFT_N
            a[i * modem._SYM : i * modem._SYM + modem._TONE] = np.sin(2 * np.pi * f * t)
        assert decode(0, a.astype(np.float32)) == []


def test_two_at_once():
    a, b = AdviserPacket(1, 2, 0.4, 1.0), ClockPacket(2, 5, 321, 6)
    heard = decode(0, modem.encode(a) * 0.5 + modem.encode(b) * 0.5)
    assert sorted(h.packet.channel for h in heard) == [1, 2]
    assert {h.packet for h in heard} == {a, b} or {type(h.packet) for h in heard} == {AdviserPacket, ClockPacket}


def test_self_ignored():
    assert decode(1, modem.encode(AdviserPacket(1, 0, 0.5, 3.0))) == []


@pytest.mark.parametrize("offset", [0, 1234, 3000, 5111])
def test_timing(offset):
    p = ClockPacket(2, 1, 100, 4)
    t0 = 1000.0
    audio = np.concatenate([np.zeros(offset, np.float32), modem.encode(p)])
    heard = decode(0, audio, t0, block=C.BLOCK)
    assert len(heard) == 1
    true_end = t0 + (offset + 9 * modem._SYM + modem._TONE) / C.SAMPLE_RATE
    assert abs(heard[0].received_at - true_end) < 0.030
