"""Tune the synth by ear: python tools/audition.py [--step 3]

Plays E sweeping 1 -> 0 over 20 s, then each step at E = 1 for 2 s,
then the four starting chords together.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.audio.synth import Synth  # noqa: E402
from backend.config import BLOCK, CHORD_GAIN_DB, SAMPLE_RATE, START_DIALS  # noqa: E402

SWEEP_S = 20.0
HOLD_S = 2.0
CHORDS_S = 6.0


def blocks(secs: float) -> int:
    return int(secs * SAMPLE_RATE / BLOCK)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=3, help="chord for the E sweep")
    args = ap.parse_args()

    import sounddevice as sd  # lazy: no PortAudio needed to import this module

    gain = 10 ** (CHORD_GAIN_DB / 20)
    synth = Synth()
    quad = [Synth() for _ in START_DIALS]

    with sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=BLOCK) as out:
        print(f"E sweep 1 -> 0 on step {args.step}")
        n = blocks(SWEEP_S)
        for i in range(n):
            synth.set(args.step, 1.0 - i / (n - 1))
            out.write(synth.render(BLOCK) * gain)
        for step in range(7):
            print(f"step {step}, E = 1")
            synth.set(step, 1.0)
            for _ in range(blocks(HOLD_S)):
                out.write(synth.render(BLOCK) * gain)
        print(f"starting chords together: {START_DIALS}")
        for s, d in zip(quad, START_DIALS):
            s.set(int(round(d)), 1.0)
        for _ in range(blocks(CHORDS_S)):
            mix = sum(s.render(BLOCK) for s in quad) / len(quad)
            out.write((mix * gain).astype(np.float32))


if __name__ == "__main__":
    main()
