"""16-FSK pilot-tone modem (SPEC 9.1-9.3, D13). Tones sit exactly on FFT bins."""
import numpy as np

from backend import config as C
from backend.contracts import AdviserPacket, ClockPacket, Heard

_SYM = (C.TONE_MS + C.GAP_MS) * C.SAMPLE_RATE // 1000  # samples per symbol slot
_TONE = C.TONE_MS * C.SAMPLE_RATE // 1000
_HPS = _SYM // C.HOP  # hops per symbol slot (16): slots are a whole number of hops
_NSYM = 10
_SPAN = _HPS * (_NSYM - 1)  # hops from symbol 0's window to symbol 9's
_EXT = 12  # extra alignments tried after the first valid one (timing refinement)
_LAST_END = (_NSYM - 1) * _SYM + _TONE  # samples from tone 0 start to last tone end
_WIN = np.hanning(C.FFT_N).astype(np.float32)


def crc8(data: bytes) -> int:
    """CRC-8, poly 0x07, init 0, no reflection."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def _bin(channel: int, k: int) -> int:
    return C.PILOT_BASE_BIN + C.CHANNEL_BINS * channel + C.TONE_SPACING_BINS * k


def _crc_of(s: list[int]) -> int:
    return crc8(bytes([s[2] << 4 | s[3], s[4] << 4 | s[5], s[6] << 4 | s[7]]))


def symbols(packet: AdviserPacket | ClockPacket) -> list[int]:
    """The 10 nibbles of a packet (SPEC 9.2)."""
    if isinstance(packet, AdviserPacket):
        typ = 0
        payload = round(packet.score * 255) << 8 | round(packet.dial / C.DIAL_MAX * 255)
    else:
        typ = 1
        payload = packet.bar << 4 | packet.speed_step
    s = [15, 0, typ, packet.seq, payload >> 12, payload >> 8 & 15, payload >> 4 & 15, payload & 15]
    c = _crc_of(s)
    return s + [c >> 4, c & 15]


def encode(packet: AdviserPacket | ClockPacket) -> np.ndarray:
    """float32 mono, peak 1.0, symbols then IDLE_MS of silence."""
    out = np.zeros(_NSYM * _SYM + C.IDLE_MS * C.SAMPLE_RATE // 1000)
    t = np.arange(_TONE) / C.SAMPLE_RATE
    ramp = C.RAMP_MS * C.SAMPLE_RATE // 1000
    env = np.ones(_TONE)
    edge = 0.5 - 0.5 * np.cos(np.pi * np.arange(ramp) / ramp)
    env[:ramp], env[-ramp:] = edge, edge[::-1]
    for j, k in enumerate(symbols(packet)):
        f = _bin(packet.channel, k) * C.SAMPLE_RATE / C.FFT_N
        out[j * _SYM : j * _SYM + _TONE] = env * np.sin(2 * np.pi * f * t)
    return (out / np.abs(out).max()).astype(np.float32)


class _Chan:
    def __init__(self) -> None:
        self.hop0 = 0  # absolute hop index of best[0]
        self.best = np.zeros(0, np.int8)  # strongest tone per hop
        self.db = np.zeros(0, np.float32)  # its dB over the channel median
        self.scan = 0  # next absolute hop to try as a packet start


class Decoder:
    def __init__(self, own_channel: int) -> None:
        self.own = own_channel
        self._chans = {c: _Chan() for c in range(4) if c != own_channel}
        self._buf = np.zeros(0, np.float32)
        self._buf_hop = 0  # absolute hop index of the first window starting in _buf
        self.stats = {"packets": 0, "crc_fail": 0}

    def feed(self, frames: np.ndarray, t0: float) -> list[Heard]:
        """Add mic samples (t0 = monotonic time of frames[0]); return newly completed packets."""
        n_before = self._buf_hop * C.HOP + len(self._buf)
        anchor = t0 - n_before / C.SAMPLE_RATE  # monotonic time of absolute sample 0
        self._buf = np.concatenate([self._buf, np.asarray(frames, np.float32)])
        n_win = (len(self._buf) - C.FFT_N) // C.HOP + 1
        if n_win <= 0:
            return []
        view = np.lib.stride_tricks.sliding_window_view(self._buf, C.FFT_N)[:: C.HOP][:n_win]
        for a in range(0, n_win, 200):
            p = np.abs(np.fft.rfft(view[a : a + 200] * _WIN, axis=1)) ** 2
            for ch, s in self._chans.items():
                lo = _bin(ch, 0)
                band = p[:, lo : lo + C.CHANNEL_BINS]
                tones = band[:, :: C.TONE_SPACING_BINS][:, :16]
                db = 10 * np.log10((tones.max(1) + 1e-20) / (np.median(band, axis=1) + 1e-20))
                s.best = np.concatenate([s.best, tones.argmax(1).astype(np.int8)])
                s.db = np.concatenate([s.db, db.astype(np.float32)])
        self._buf = self._buf[n_win * C.HOP :]
        self._buf_hop += n_win
        out: list[Heard] = []
        for ch, s in self._chans.items():
            out += self._scan(ch, s, anchor)
        return out

    def _try(self, s: _Chan, i: int) -> tuple[list[int], float] | None:
        """Decode a packet whose symbol 0 is analysed at index i; None on any failure."""
        idx = i + _HPS * np.arange(_NSYM)
        if (s.db[idx] < C.MIN_TONE_DB).any():
            return None
        sym = s.best[idx].tolist()
        if sym[0] != 15 or sym[1] != 0 or sym[2] > 1 or _crc_of(sym) != sym[8] << 4 | sym[9]:
            return None
        return sym, float(s.db[idx].mean())

    def _scan(self, ch: int, s: _Chan, anchor: float) -> list[Heard]:
        out: list[Heard] = []
        last = s.hop0 + len(s.best) - 1 - _SPAN - _EXT
        m = max(s.scan, s.hop0)
        while m <= last:
            i = m - s.hop0
            if s.db[i] >= C.MIN_TONE_DB and s.best[i] == 15 and s.best[i + _HPS] == 0:
                r = self._try(s, i)
                if r is None:
                    self.stats["crc_fail"] += 1
                else:
                    sym, snr = r
                    k = 0  # extend over contiguous alignments decoding the same packet; use their middle
                    while k < _EXT:
                        r2 = self._try(s, i + k + 1)
                        if r2 is None or r2[0] != sym:
                            break
                        k += 1
                    centre = (m + k / 2) * C.HOP + C.FFT_N / 2  # of symbol 0's window, absolute samples
                    end = centre - _TONE / 2 + _LAST_END  # symbol 0 tone is centred there
                    out.append(Heard(_unpack(ch, sym), snr, anchor + end / C.SAMPLE_RATE))
                    self.stats["packets"] += 1
                    m += 100  # a channel never carries two packets within 1 s
                    continue
            m += 1
        s.scan = m
        cut = min(m - s.hop0, len(s.best))
        s.best, s.db, s.hop0 = s.best[cut:], s.db[cut:], s.hop0 + cut
        return out


def _unpack(ch: int, s: list[int]) -> AdviserPacket | ClockPacket:
    payload = s[4] << 12 | s[5] << 8 | s[6] << 4 | s[7]
    if s[2] == 0:
        return AdviserPacket(ch, s[3], (payload >> 8) / 255, (payload & 255) / 255 * C.DIAL_MAX)
    return ClockPacket(ch, s[3], payload >> 4, payload & 15)
