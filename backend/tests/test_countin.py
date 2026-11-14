"""Count-in detector (SPEC 9.4, 13): finds the 4 clicks, ignores everything else. No hardware."""
import numpy as np

from backend import config as C
from backend.audio import countin, modem
from backend.audio.synth import Synth
from backend.contracts import AdviserPacket

SR = C.SAMPLE_RATE
CLICKS = countin.clicks()
GAP = round(C.COUNT_IN_INTERVAL_S * SR)


def run(x: np.ndarray) -> list[float | None]:
    """Feed in mic-sized blocks; return (sample at which each trigger fired, minus its reported lag)."""
    d, out = countin.CountInDetector(), []
    for a in range(0, len(x), C.BLOCK):
        lag = d.feed(x[a : a + C.BLOCK].astype(np.float32))
        if lag is not None:
            out.append(a + C.BLOCK - lag * SR)  # estimated start sample of the 4th click
    return out


def chords(n: int, step: int, score: float, seed: int = 0) -> np.ndarray:
    s = Synth(seed)
    s.set(step, score)
    return np.concatenate([s.render(C.BLOCK).copy() for _ in range(n // C.BLOCK + 1)])[:n] * 10 ** (C.CHORD_GAIN_DB / 20)


def test_clicks_stay_in_band() -> None:
    spec = np.abs(np.fft.rfft(CLICKS.astype(np.float64), 1 << 18)) ** 2
    f = np.fft.rfftfreq(1 << 18, 1 / SR)
    lo, hi = C.COUNT_IN_BAND_HZ
    assert spec[(f >= lo) & (f <= hi)].sum() / spec.sum() > 0.99
    assert spec[f > 8000].sum() / spec.sum() < 1e-6  # synth rule: nothing above 8 kHz
    assert abs(CLICKS).max() == 1.0 and len(CLICKS) == 3 * GAP + C.COUNT_IN_CLICK_MS * SR // 1000


def test_detects_at_0db_with_chords() -> None:
    """0 dB = click burst power equals the noise power inside 2-6 kHz; chords play at CHORD_GAIN_DB throughout."""
    burst = float(np.mean(CLICKS[: C.COUNT_IN_CLICK_MS * SR // 1000] ** 2)) * 0.5**2  # on air at peak 0.5
    sigma = np.sqrt(burst * 6)  # white noise: 4 kHz of 24 kHz is in band
    for seed in range(7):
        pre = 2 * SR + seed * 137
        x = np.zeros(pre + len(CLICKS) + SR)
        x[pre : pre + len(CLICKS)] = CLICKS * 0.5
        x += np.random.default_rng(seed).standard_normal(len(x)) * sigma + chords(len(x), seed, 0.1, seed)
        hits = run(x)
        assert len(hits) == 1
        assert abs(hits[0] - (pre + 3 * GAP)) < 0.015 * SR  # lag-corrected start of beat 4


def test_no_false_start() -> None:
    rng = np.random.default_rng(1)
    for sigma in (0.01, 0.3):  # 60 s of white noise at two levels: 0 false starts
        assert run(rng.standard_normal(60 * SR) * sigma) == []
    for step in (0, 3, 6):  # chords alone, changing step
        assert run(chords(8 * SR, step, 1.0)) == []
    pkts = np.concatenate([modem.encode(AdviserPacket(c, 1, 0.5, 3.0)) for c in range(4)]) * 10 ** (C.PILOT_GAIN_DB / 20)
    assert run(np.concatenate([np.zeros(SR), pkts, pkts])) == []  # adviser pilot packets


def test_wrong_rhythm_ignored() -> None:
    click = CLICKS[: C.COUNT_IN_CLICK_MS * SR // 1000]
    for gap in (0.3, 0.8):  # 4 clicks, wrong spacing
        x = np.zeros(8 * SR)
        for k in range(4):
            a = 2 * SR + round(k * gap * SR)
            x[a : a + len(click)] = click
        assert run(x) == []
    x = np.zeros(8 * SR)  # right spacing, only 3 clicks
    for k in range(3):
        x[2 * SR + k * GAP : 2 * SR + k * GAP + len(click)] = click
    assert run(x) == []
