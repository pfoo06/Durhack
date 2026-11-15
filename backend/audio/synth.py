"""Chord synth (SPEC section 8). Pure numpy, no hardware."""
from __future__ import annotations

import math

import numpy as np

from backend.config import BLOCK, SAMPLE_RATE

# Music constants from SPEC section 8 (not in config.py; spec gap noted in PR).
A3_HZ = 220.0
SCALE = (0, 2, 4, 5, 7, 9, 11)  # A major, semitones above A3
N_HARM = 10  # bowed string: sawtooth-like 1/k partials, shaped by the body resonances below
BODY_HZ = (200.0, 420.0, 1100.0)  # cello body/air/wood resonance peaks (approx.); partials near them ring louder
BODY_OCT = 0.45  # width of each resonance, in octaves
VIB_HZ = 5.2  # vibrato rate; each voice a little different so they never pulse in lockstep
VIB_CENTS = 9.0  # vibrato depth
HARMONIC_TOP_HZ = 1900.0  # drop partials above this: 2-8 kHz belongs to the melody and count-in (countin.py)
CHORUS_CENTS = 6.0  # a second, slightly sharp copy of the triad: slow beating, fuller body, still reads as in tune
CHORUS_GAIN = 0.5
SUB_GAIN = 0.6  # root an octave down
DETUNE_CENTS = 30.0
E_TAU_S = 0.2
FADE_S = 0.15
SWELL_S = 0.25  # bow swell after a chord change: dips SWELL_DEPTH then eases back over ~3*SWELL_S
SWELL_DEPTH = 0.3
NOISE_CUTOFF_HZ = 2000.0
NOISE_STAGES = 6  # ponytail: spec says one pole; that leaves too much above 8 kHz, so cascade
HEADROOM = 0.345  # fixed scale so peak <= 1.0 before the engine's chord gain
N_STEPS = 7
NVOICE = 9  # root, third, fifth, minor second, tritone, sub root, chorus root/third/fifth
TWO_PI = 2.0 * math.pi


def _degree_hz(d: int) -> float:
    return A3_HZ * 2.0 ** ((12 * (d // 7) + SCALE[d % 7]) / 12.0)


def _chord_hz(step: int) -> np.ndarray:
    root, third, fifth = (_degree_hz(step + k) for k in (0, 2, 4))
    return np.array([root, third, fifth, root * 2 ** (1 / 12), root * 2 ** (6 / 12), root / 2, root, third, fifth])


def _body(f: np.ndarray) -> np.ndarray:
    """Body-resonance gain at frequency f: a floor plus one log-gaussian bump per resonance."""
    lf = np.log2(f[..., None] / np.array(BODY_HZ))
    return 0.35 + np.exp(-0.5 * (lf / BODY_OCT) ** 2).sum(-1)


def _clamp01(x: float) -> float:
    return min(max(x, 0.0), 1.0)


class Synth:
    def __init__(self, seed: int | None = None) -> None:
        self._step = 0  # targets, written by set()
        self._score = 1.0
        self._e = 1.0  # smoothed score
        self._cur = 0
        self._hz_cur = _chord_hz(0)
        self._hz_old = self._hz_cur
        self._ph_cur = np.zeros(NVOICE)
        self._ph_old = np.zeros(NVOICE)
        self._vib_w = TWO_PI * VIB_HZ * np.linspace(0.93, 1.07, NVOICE) / SAMPLE_RATE  # rad/sample per voice
        self._vib_ph = np.linspace(0.0, TWO_PI, NVOICE, endpoint=False)
        self._fade_pos = 0  # 0 = not fading
        self._fade_n = int(FADE_S * SAMPLE_RATE)
        self._swell_pos = 1 << 30  # samples since the last chord change; huge = no swell at start
        self._rng = np.random.default_rng(seed)
        self._a = math.exp(-TWO_PI * NOISE_CUTOFF_HZ / SAMPLE_RATE)
        self._lp = [0.0] * NOISE_STAGES
        self._playing = True  # set_playing(): the Mac keeps the chord silent until its replay runs
        self._level = 1.0  # current output level, ramped towards 0 or 1 over FADE_S
        self._rendered = False
        self._size = 0
        self._alloc(BLOCK)
        # normalise filtered noise to ~unit rms so the 0.15 gain means something
        self._noise_norm = 1.0
        probe = self._noise(1 << 14)
        self._noise_norm = 1.0 / float(np.sqrt(np.mean(probe**2)))
        self._lp = [0.0] * NOISE_STAGES

    def set(self, step: int, score: float) -> None:
        self._step = step
        self._score = score

    def set_playing(self, on: bool) -> None:
        """Fade the chord in (True) or out (False) over FADE_S, so starting and stopping never click.
        Before anything has been rendered it just starts at that level (no blip when the app opens)."""
        self._playing = on
        if not self._rendered:
            self._level = 1.0 if on else 0.0

    def _alloc(self, n: int) -> None:
        self._size = n
        self._t = np.arange(1, n + 1, dtype=np.float64)
        self._ph = np.empty((NVOICE, n))
        self._a1 = np.empty((NVOICE, n))
        self._b1 = np.empty((NVOICE, n))
        self._cur_buf = np.empty(n)
        self._old_buf = np.empty(n)
        self._w = np.empty(n)
        self._out = np.empty(n, dtype=np.float32)
        self._g = np.empty(n)

    def _bank(self, phases: np.ndarray, hz: np.ndarray, detune: np.ndarray,
              gains: np.ndarray, out: np.ndarray, n: int) -> None:
        f = hz * detune
        inc = TWO_PI * f / SAMPLE_RATE
        # vibrato: frequency f*(1 + D sin(vib)), phase is its closed-form integral (no per-sample state)
        dv = 2.0 ** (VIB_CENTS / 1200.0) - 1.0
        w, v0 = self._vib_w, self._vib_ph
        k_vib = (inc * dv / w)[:, None]
        ph, a, b = self._ph, self._a1, self._b1
        np.multiply(w[:, None], self._t, out=b)
        b += v0[:, None]
        np.cos(b, out=b)
        np.multiply(inc[:, None], self._t, out=ph)
        ph += phases[:, None] + k_vib * (np.cos(v0)[:, None] - b)
        k = np.arange(1, N_HARM + 1)
        fk = f[:, None] * k
        amp = (fk < HARMONIC_TOP_HZ) * _body(fk) / k  # (NVOICE, N_HARM)
        amp /= np.sqrt((amp**2).sum(1, keepdims=True))  # each voice unit power whatever its pitch
        np.sin(ph, out=a)
        a *= amp[:, :1]
        for j in range(1, N_HARM):
            if not amp[:, j].any():
                continue
            np.multiply(ph, j + 1, out=b)
            np.sin(b, out=b)
            b *= amp[:, j : j + 1]
            a += b
        np.dot(gains, a, out=out)
        phases[:] = ph[:, -1] % TWO_PI
        self._vib_next = (v0 + w * n) % TWO_PI

    def _noise(self, n: int) -> np.ndarray:
        white = self._rng.standard_normal(n)
        a, k = self._a, 1.0 - self._a
        lp = self._lp
        out = np.empty(n)
        for i in range(n):
            x = white[i]
            for j in range(NOISE_STAGES):
                lp[j] = a * lp[j] + k * x
                x = lp[j]
            out[i] = x
        return out * self._noise_norm

    def render(self, n: int) -> np.ndarray:
        self._rendered = True
        if n != self._size:
            self._alloc(n)
        target = min(max(int(self._step), 0), N_STEPS - 1)
        score = _clamp01(float(self._score))
        self._e += (1.0 - math.exp(-n / (SAMPLE_RATE * E_TAU_S))) * (score - self._e)
        e = self._e

        if self._fade_pos == 0 and target != self._cur:
            self._hz_old, self._ph_old = self._hz_cur, self._ph_cur
            self._hz_cur, self._ph_cur = _chord_hz(target), np.zeros(NVOICE)
            self._cur = target
            self._fade_pos = 1
            self._swell_pos = 0

        g2 = _clamp01((0.7 - e) / 0.1) * 0.6
        g3 = _clamp01((0.4 - e) / 0.1) * 0.6
        gn = _clamp01((0.2 - e) / 0.1) * 0.15
        d = 2.0 ** (DETUNE_CENTS * (1.0 - e) / 1200.0)
        c = 2.0 ** (CHORUS_CENTS / 1200.0)
        detune = np.array([1.0, d, 1.0 / d, 1.0, 1.0, 1.0, c, d * c, c / d])
        gains = np.array([1.0, 1.0, 1.0, g2, g3, SUB_GAIN, CHORUS_GAIN, CHORUS_GAIN, CHORUS_GAIN])
        scale = HEADROOM / math.sqrt(gains.sum() + gn)
        gains *= scale

        out = self._cur_buf
        self._bank(self._ph_cur, self._hz_cur, detune, gains, out, n)
        if self._fade_pos:
            self._bank(self._ph_old, self._hz_old, detune, gains, self._old_buf, n)
            w = self._w
            np.add(self._t, self._fade_pos - 2, out=w)  # sample index within the fade
            w *= (math.pi / 2) / self._fade_n
            np.clip(w, 0.0, math.pi / 2, out=w)
            out *= np.sin(w)
            self._old_buf *= np.cos(w)
            out += self._old_buf
            self._fade_pos += n
            if self._fade_pos > self._fade_n:
                self._fade_pos = 0
        self._vib_ph = self._vib_next  # both banks share the vibrato clock: advance it once per block
        if self._swell_pos < 4 * SWELL_S * SAMPLE_RATE:
            g = self._g  # 1 - D*exp(-t/tau), reusing the ramp buffer (overwritten below if needed)
            np.add(self._t, self._swell_pos, out=g)
            g *= -1.0 / (SWELL_S * SAMPLE_RATE)
            np.exp(g, out=g)
            g *= -SWELL_DEPTH
            g += 1.0
            out *= g
            self._swell_pos += n
        if gn > 0.0:
            out += gn * scale * self._noise(n)
        target_level = 1.0 if self._playing else 0.0
        if self._level != target_level or target_level == 0.0:
            reach = n / max(1, self._fade_n)  # a full fade takes FADE_S
            end = self._level + max(-reach, min(reach, target_level - self._level))
            np.multiply(self._t, (end - self._level) / n, out=self._g)  # a linear ramp, no allocation
            self._g += self._level
            out *= self._g
            self._level = end
        np.clip(out, -1.0, 1.0, out=out)
        self._out[:] = out
        return self._out
