"""Count-in clicks and their detector (SPEC 9.4). Energy lives in COUNT_IN_BAND_HZ only: chords stop below
1.8 kHz and pilots start at 14 kHz. Pure numpy, no hardware."""
from collections import deque

import numpy as np

from backend import config as C

_TONES = np.linspace(*C.COUNT_IN_BAND_HZ, 6)[1:-1]  # the click's four partials, inside the band
_BINS = np.array([[round(f * C.FFT_N / C.SAMPLE_RATE) + d for d in (-1, 0, 1)] for f in _TONES])  # (4, 3)
_WIN = np.hanning(C.FFT_N)
_FLOOR_HOPS = round(C.COUNT_IN_FLOOR_S * C.SAMPLE_RATE / C.HOP)
_RATIO = 10 ** (C.COUNT_IN_ONSET_DB / 10)
_NEED = 3  # partials (of 4) that must rise together
_GAP_HOPS = C.COUNT_IN_INTERVAL_S * C.SAMPLE_RATE / C.HOP
_TOL_HOPS = C.COUNT_IN_TOL_S * C.SAMPLE_RATE / C.HOP
_SPAN_HOPS = (C.COUNT_IN_CLICKS - 1) * _GAP_HOPS + _TOL_HOPS * (C.COUNT_IN_CLICKS - 1)
DETECT_LAG_S = 0.028  # measured (test_countin): the onset fires this long after a click starts


def clicks() -> np.ndarray:
    """float32 mono, peak 1.0: COUNT_IN_CLICKS windowed bursts, COUNT_IN_INTERVAL_S apart (first at sample 0)."""
    n = C.COUNT_IN_CLICK_MS * C.SAMPLE_RATE // 1000
    t = np.arange(n) / C.SAMPLE_RATE
    click = sum(np.sin(2 * np.pi * f * t) for f in _TONES) * np.hanning(n)
    step = round(C.COUNT_IN_INTERVAL_S * C.SAMPLE_RATE)
    out = np.zeros(step * (C.COUNT_IN_CLICKS - 1) + n)
    for k in range(C.COUNT_IN_CLICKS):
        out[k * step : k * step + n] = click
    return (out / np.abs(out).max()).astype(np.float32)


class CountInDetector:
    """feed(block) -> lag in seconds when COUNT_IN_CLICKS onsets of band energy arrive COUNT_IN_INTERVAL_S apart (±tol).

    An onset is energy at the click's partials rising COUNT_IN_ONSET_DB over its running median. Broadband noise, steady chords and
    pilot packets raise the median with them, so only a rhythm of clicks gets through.
    """

    def __init__(self) -> None:
        self._buf = np.zeros(0, np.float32)
        self._hist: deque[np.ndarray] = deque(maxlen=_FLOOR_HOPS)  # per-partial energy
        self._hop = 0  # hop counter: the time base
        self._above = False
        self._onsets: deque[int] = deque()

    def feed(self, block: np.ndarray) -> float | None:
        """None, or (on the 4th click) roughly how many seconds ago that click started, so the caller can catch up."""
        self._buf = np.concatenate([self._buf, block.astype(np.float32, copy=False)])
        lag = None
        while len(self._buf) >= C.FFT_N:
            if self._hop_step(self._buf[: C.FFT_N]):
                lag = (len(self._buf) - C.FFT_N) / C.SAMPLE_RATE + DETECT_LAG_S  # unread audio + window delay
            self._buf = self._buf[C.HOP :]
        return lag

    def _hop_step(self, win: np.ndarray) -> bool:
        e = np.sum(np.abs(np.fft.rfft(win * _WIN)[_BINS]) ** 2, axis=1)  # each of the click's partials: the most noise-proof
        self._hop += 1
        if len(self._hist) < _FLOOR_HOPS // 2:  # no floor yet
            self._hist.append(e)
            return False
        above = (e > np.median(self._hist, axis=0) * _RATIO + 1e-9).sum() >= _NEED  # a click lights all partials, a melody note one
        self._hist.append(e)
        rising, self._above = above and not self._above, above
        if not rising:
            return False
        self._onsets.append(self._hop)
        while self._onsets[0] < self._hop - _SPAN_HOPS:
            self._onsets.popleft()
        if any(self._chain(o, C.COUNT_IN_CLICKS - 1) for o in self._onsets):
            self._onsets.clear()
            return True
        return False

    def _chain(self, at: int, more: int) -> bool:
        """Is there a run of `more` further onsets after `at`, each one beat (±tol) after the last?"""
        return more == 0 or any(abs(o - at - _GAP_HOPS) <= _TOL_HOPS and self._chain(o, more - 1)
                                for o in self._onsets if o > at)
