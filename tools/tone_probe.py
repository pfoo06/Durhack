"""Play tones 0 and 15 of each channel and report dB over the channel median (SPEC 9.1, hall test).

Usage: python tools/tone_probe.py [--gain-db -18] [--secs 1.0] [--input-device X] [--output-device Y]
"""
import argparse

import numpy as np
import sounddevice as sd

from backend import config as C


def tone_bin(channel: int, k: int) -> int:
    return C.PILOT_BASE_BIN + C.CHANNEL_BINS * channel + C.TONE_SPACING_BINS * k


def db_over_median(rec: np.ndarray, channel: int, k: int) -> float:
    """Mean Hann-FFT power at the tone bin vs the median of the channel's bins, in dB."""
    w = np.hanning(C.FFT_N)
    n = (len(rec) - C.FFT_N) // C.HOP
    p = np.zeros(C.FFT_N // 2 + 1)
    for m in range(n):
        p += np.abs(np.fft.rfft(rec[m * C.HOP : m * C.HOP + C.FFT_N] * w)) ** 2
    lo = C.PILOT_BASE_BIN + C.CHANNEL_BINS * channel
    return 10 * np.log10((p[tone_bin(channel, k)] + 1e-20) / (np.median(p[lo : lo + C.CHANNEL_BINS]) + 1e-20))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gain-db", type=float, default=C.PILOT_GAIN_DB)
    ap.add_argument("--secs", type=float, default=1.0)
    ap.add_argument("--input-device")
    ap.add_argument("--output-device")
    a = ap.parse_args()
    n = int(a.secs * C.SAMPLE_RATE)
    t = np.arange(n) / C.SAMPLE_RATE
    amp = 10 ** (a.gain_db / 20)
    print(f"gain {a.gain_db} dB; need >= {C.MIN_TONE_DB} dB (aim for 15+)")
    for ch in range(4):
        for k in (0, 15):
            f = tone_bin(ch, k) * C.SAMPLE_RATE / C.FFT_N
            out = (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)
            rec = sd.playrec(out, C.SAMPLE_RATE, channels=1, dtype="float32",
                             device=(a.input_device, a.output_device), blocking=True)[:, 0]
            rec = rec[C.SAMPLE_RATE // 4 :]  # drop start-up
            db = db_over_median(rec, ch, k)
            print(f"ch{ch} tone{k:2d} {f:8.1f} Hz  {db:5.1f} dB  {'OK' if db >= C.MIN_TONE_DB else 'WEAK'}")


if __name__ == "__main__":
    main()
