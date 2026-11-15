"""Melody modem (SPEC 9.5): the 40-bit packet of modem.py played as 11 plucked A-major notes, one base-14 digit each.

Macs take turns (MELODY_SLOT_S), so one alphabet serves all four. Notes sit above the chords (2.0-7.9 kHz).
"""
import numpy as np

from backend import config as C
from backend.audio.modem import _crc_of, _unpack, symbols
from backend.contracts import AdviserPacket, ClockPacket, Heard

_SYM = C.MELODY_NOTE_MS * C.SAMPLE_RATE // 1000
_TONE = C.MELODY_SOUND_MS * C.SAMPLE_RATE // 1000
_HPS = _SYM // C.HOP  # hops per note (10)
_NSYM = 11  # 14**11 > 2**40
_SPAN = _HPS * (_NSYM - 1)
_EXT = 4
_LAST_END = (_NSYM - 1) * _SYM + _TONE
PACKET_S = _LAST_END / C.SAMPLE_RATE  # first note to Heard.received_at (end of the last note): 1.08 s
_WIN = np.hanning(C.FFT_N).astype(np.float32)

# A major, B6 up to B8, minus C#8 (4435 Hz sits on a count-in click partial, countin.py)
_MIDI = np.array([95, 97, 98, 100, 102, 104, 105, 107, 110, 112, 114, 116, 117, 119])
FREQS = 440.0 * 2.0 ** ((_MIDI - 69) / 12)  # 14 notes
# Equal-loudness tilt: up to -3 dB near 3.5 kHz, where ears are most sensitive. Costs about as much margin as a 1 dB gain
# cut (only the middle notes lose SNR), so it buys more softness per dB than MELODY_GAIN_DB; -5 dB fails the noise tests.
_EAR = 10 ** (-3 * np.exp(-0.5 * (np.log2(FREQS / 3500) / 0.6) ** 2) / 20)
_BINS = np.round(FREQS * C.FFT_N / C.SAMPLE_RATE).astype(int)[:, None] + np.array([-1, 0, 1])  # (14, 3)


def digits(packet: AdviserPacket | ClockPacket) -> list[int]:
    s = symbols(packet)
    s[1] = packet.channel  # the sender rides in the header: no per-Mac frequency band any more
    n = 0
    for nib in s:
        n = n << 4 | nib
    return [n // 14**k % 14 for k in range(_NSYM - 1, -1, -1)]


def encode(packet: AdviserPacket | ClockPacket) -> np.ndarray:
    """float32 mono, peak 1.0, one plucked note per digit."""
    out = np.zeros(_NSYM * _SYM)
    t = np.arange(_TONE) / C.SAMPLE_RATE
    attack = C.MELODY_ATTACK_MS * C.SAMPLE_RATE // 1000
    release = int(0.015 * C.SAMPLE_RATE)  # soft cosine tail, no click at the note's end
    env = np.exp(-np.maximum(t - attack / C.SAMPLE_RATE, 0) / (C.MELODY_DECAY_MS / 1000))  # decay starts after the attack
    env[:attack] *= 0.5 - 0.5 * np.cos(np.pi * np.arange(attack) / attack)
    env[-release:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(release) / release)
    for j, d in enumerate(digits(packet)):
        out[j * _SYM : j * _SYM + _TONE] = _EAR[d] * env * np.sin(2 * np.pi * FREQS[d] * t)
    return (out / np.abs(out).max()).astype(np.float32)


class MelodyDecoder:
    """Same interface as modem.Decoder. Packets from our own channel (our own speaker) are dropped."""

    def __init__(self, own_channel: int) -> None:
        self.own = own_channel
        self._buf = np.zeros(0, np.float32)
        self._buf_hop = 0
        self.hop0, self.scan = 0, 0
        self.best = np.zeros(0, np.int8)  # strongest note per hop
        self.db = np.zeros(0, np.float32)  # its dB over the median note
        self.stats = {"packets": 0, "crc_fail": 0}

    def feed(self, frames: np.ndarray, t0: float) -> list[Heard]:
        n_before = self._buf_hop * C.HOP + len(self._buf)
        anchor = t0 - n_before / C.SAMPLE_RATE
        self._buf = np.concatenate([self._buf, np.asarray(frames, np.float32)])
        n_win = (len(self._buf) - C.FFT_N) // C.HOP + 1
        if n_win <= 0:
            return []
        view = np.lib.stride_tricks.sliding_window_view(self._buf, C.FFT_N)[:: C.HOP][:n_win]
        for a in range(0, n_win, 200):
            p = np.abs(np.fft.rfft(view[a : a + 200] * _WIN, axis=1)) ** 2
            notes = p[:, _BINS].sum(2)  # (windows, 14)
            db = 10 * np.log10((notes.max(1) + 1e-20) / (np.median(notes, axis=1) + 1e-20))
            self.best = np.concatenate([self.best, notes.argmax(1).astype(np.int8)])
            self.db = np.concatenate([self.db, db.astype(np.float32)])
        self._buf = self._buf[n_win * C.HOP :]
        self._buf_hop += n_win
        return self._scan(anchor)

    def _try(self, i: int):
        """None: no notes there. False: notes but not a packet. Else (nibbles, mean dB)."""
        idx = i + _HPS * np.arange(_NSYM)
        if (self.db[idx] < C.MIN_TONE_DB).any():
            return None
        n = 0
        for d in self.best[idx].tolist():
            n = n * 14 + d
        if n >> 40:
            return False
        s = [n >> (36 - 4 * j) & 15 for j in range(10)]
        if s[0] != 15 or s[1] > 3 or s[2] > 1 or _crc_of(s) != s[8] << 4 | s[9]:  # type 0 adviser, 1 clock (§9.4a)
            return False
        return s, float(self.db[idx].mean())

    def _scan(self, anchor: float) -> list[Heard]:
        out: list[Heard] = []
        last = self.hop0 + len(self.best) - 1 - _SPAN - _EXT
        m = max(self.scan, self.hop0)
        while m <= last:
            r = self._try(m - self.hop0)
            if r is False:
                self.stats["crc_fail"] += 1
            elif r is not None:
                s, snr = r
                k = 0  # extend over contiguous alignments decoding the same packet; use their middle
                while k < _EXT:
                    r2 = self._try(m - self.hop0 + k + 1)
                    if not r2 or r2[0] != s:
                        break
                    k += 1
                if s[1] != self.own:
                    centre = (m + k / 2) * C.HOP + C.FFT_N / 2
                    end = centre - _TONE / 2 + _LAST_END
                    out.append(Heard(_unpack(s[1], s), snr, anchor + end / C.SAMPLE_RATE))
                    self.stats["packets"] += 1
                m += k + _SPAN
                continue
            m += 1
        self.scan = m
        cut = min(m - self.hop0, len(self.best))
        self.best, self.db, self.hop0 = self.best[cut:], self.db[cut:], self.hop0 + cut
        return out
