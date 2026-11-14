import numpy as np
import pytest

from backend import config as C
from backend.audio import countin, melody
from backend.contracts import AdviserPacket
from backend.mocks import VirtualAir

TAIL = np.zeros(C.SAMPLE_RATE // 2, np.float32)


def decode(own: int, audio: np.ndarray, block: int = 4800):
    d = melody.MelodyDecoder(own)
    out = []
    audio = np.concatenate([audio, TAIL])
    for a in range(0, len(audio), block):
        out += d.feed(audio[a : a + block], 100.0 + a / C.SAMPLE_RATE)
    return out, d


def test_notes_clear_chords_and_count_in():
    assert melody.FREQS[0] > 1800 and melody.FREQS[-1] < 8000
    partials = np.linspace(*C.COUNT_IN_BAND_HZ, 6)[1:-1]
    assert len(melody.FREQS) == 14 and 14**11 > 2**40
    assert all(abs(f - p) > 50 for f in melody.FREQS for p in partials)  # clear of the count-in detector's bins


@pytest.mark.parametrize("ch", range(4))
def test_round_trip(ch):
    for p in (AdviserPacket(ch, 0, 0.0, 0.0), AdviserPacket(ch, 15, 1.0, 6.0), AdviserPacket(ch, 7, 0.5, 3.0)):
        heard, _ = decode((ch + 1) % 4, melody.encode(p))
        assert len(heard) == 1
        got = heard[0].packet
        assert (got.channel, got.seq) == (ch, p.seq)
        assert got.score == pytest.approx(p.score, abs=1 / 255) and got.dial == pytest.approx(p.dial, abs=6 / 255)


def test_own_packets_are_ignored():
    heard, d = decode(2, melody.encode(AdviserPacket(2, 1, 0.5, 3.0)))
    assert heard == [] and d.stats["packets"] == 0


def test_packet_length_and_peak():
    a = melody.encode(AdviserPacket(0, 1, 0.5, 3.0))
    assert len(a) == 11 * C.MELODY_NOTE_MS * C.SAMPLE_RATE // 1000 and abs(a).max() == pytest.approx(1.0)
    assert 11 * C.MELODY_NOTE_MS / 1000 < C.MELODY_SLOT_S


def test_noise_at_pilot_snr_beats_the_pilots():
    """Noise sized for a 0 dB pilot at PILOT_GAIN_DB; the melody plays 6 dB louder (MELODY_GAIN_DB)."""
    gain = 10 ** (C.MELODY_GAIN_DB / 20)
    air = VirtualAir(0.0, tone_amplitude=10 ** (C.PILOT_GAIN_DB / 20), seed=1)
    rng = np.random.default_rng(3)
    ok = 0
    for k in range(30):
        p = AdviserPacket(1, k % 16, float(rng.random()), float(rng.random() * 6))
        heard, _ = decode(0, air.mix([melody.encode(p) * gain]))
        ok += len(heard) == 1 and heard[0].packet.seq == p.seq
    assert ok >= 28


def test_back_to_back_slots_two_senders():
    a, b = melody.encode(AdviserPacket(1, 3, 0.2, 1.0)), melody.encode(AdviserPacket(2, 4, 0.8, 5.0))
    gap = np.zeros(int((C.MELODY_SLOT_S - 11 * C.MELODY_NOTE_MS / 1000) * C.SAMPLE_RATE), np.float32)
    heard, _ = decode(0, np.concatenate([a, gap, b]))
    assert [h.packet.channel for h in heard] == [1, 2]


def test_melody_never_fires_the_count_in_detector():
    rng = np.random.default_rng(5)
    det = countin.CountInDetector()
    audio = np.concatenate([np.zeros(C.SAMPLE_RATE, np.float32)] + [
        np.concatenate([melody.encode(AdviserPacket(int(rng.integers(4)), int(rng.integers(16)), float(rng.random()),
                                                    float(rng.random() * 6))) * 0.25, np.zeros(int((C.MELODY_SLOT_S - 1.1) * C.SAMPLE_RATE), np.float32)])
        for _ in range(60)])
    audio = audio + rng.standard_normal(len(audio)).astype(np.float32) * 1e-3  # a mic is never digitally silent
    assert all(det.feed(audio[a : a + 480]) is None for a in range(0, len(audio), 480))


def test_four_macs_taking_turns_with_clock_error():
    """Every Mac hears the other three, 6 cycles, with each Mac's slot clock up to 150 ms off."""
    sr, slot = C.SAMPLE_RATE, int(C.MELODY_SLOT_S * C.SAMPLE_RATE)
    offsets, mix, sent = (0, 0.1, -0.1, 0.15), np.zeros(25 * slot + sr, np.float32), []
    for k in range(24):
        c = k % 4
        p = AdviserPacket(c, k % 16, (k * 37 % 100) / 100, (k * 11 % 60) / 10)
        a = melody.encode(p) * 10 ** (C.MELODY_GAIN_DB / 20)
        s = int(k * slot + offsets[c] * sr) + slot // 4
        mix[s : s + len(a)] += a
        sent.append((c, p.seq))
    audio = VirtualAir(0.0, 10 ** (C.PILOT_GAIN_DB / 20)).mix([mix])
    for me in range(4):
        heard, _ = decode(me, audio)
        assert sorted((h.packet.channel, h.packet.seq) for h in heard) == sorted(x for x in sent if x[0] != me)
