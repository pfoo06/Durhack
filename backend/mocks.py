"""In-process stand-ins for the real world (SPEC 4.8). VirtualRoom (P3) lives here too."""
from collections.abc import Sequence

import numpy as np

from backend import config as C


class VirtualAir:
    """Sums the sample buffers of in-process Macs and adds white noise.

    snr_db is in-band: noise power inside one pilot channel (CHANNEL_BINS wide) vs the
    power of a pure tone of `tone_amplitude` (peak). The noise is white over 0..fs/2.
    """

    def __init__(self, snr_db: float = 0.0, tone_amplitude: float = 1.0, seed: int = 0) -> None:
        in_band = C.CHANNEL_BINS * C.SAMPLE_RATE / C.FFT_N
        power = tone_amplitude**2 / 2 / 10 ** (snr_db / 10) * (C.SAMPLE_RATE / 2) / in_band
        self.sigma = float(np.sqrt(power))
        self._rng = np.random.default_rng(seed)

    def mix(self, buffers: Sequence[np.ndarray]) -> np.ndarray:
        """What a microphone hears: the zero-padded sum of all buffers plus noise (float32)."""
        out = np.zeros(max(len(b) for b in buffers))
        for b in buffers:
            out[: len(b)] += b
        out += self._rng.standard_normal(len(out)) * self.sigma
        return out.astype(np.float32)
