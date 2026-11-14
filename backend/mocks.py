"""In-process stand-ins for the real world (SPEC 4.8). VirtualRoom (P3) lives here too."""
import heapq
from collections.abc import Iterable, Sequence

import numpy as np

from backend import config as C
from backend.contracts import AdviserPacket, Heard


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


# The modem sends score and dial as one byte each (contracts.AdviserPacket), so the room rounds them the same way.
BYTE_MAX = 255
ROOM_SNR_DB = 20.0  # reported on every Heard from the room; the adviser stores it but never decides on it


class VirtualRoom:
    """Delivers adviser packets between in-process advisers, with loss and delay but no audio (SPEC 4.8, 7.6).

    Each listener loses each packet independently with probability `loss`, and hears it
    `delay_s` seconds after it was sent (uniform in the range: the packet's length on air plus
    decoding). Time is the caller's clock, simulated seconds in `sim.py`.
    """

    def __init__(
        self,
        loss: float = 0.1,
        delay_s: tuple[float, float] = (1.6, 2.0),
        channels: Iterable[int] = range(4),
        seed: int = 0,
    ) -> None:
        self.loss = loss
        self.delay_s = delay_s
        self.channels = tuple(channels)
        self._rng = np.random.default_rng(seed)
        self._queue: list[tuple[float, int, int, AdviserPacket]] = []  # (deliver_at, order, listener, packet)
        self._order = 0
        self.sent = 0
        self.delivered = 0

    def send(self, packet: AdviserPacket, now: float) -> None:
        """Put a packet on the air at time `now`. Every other channel may hear it later."""
        self.sent += 1
        packet = AdviserPacket(
            channel=packet.channel,
            seq=packet.seq,
            score=round(packet.score * BYTE_MAX) / BYTE_MAX,
            dial=round(packet.dial / C.DIAL_MAX * BYTE_MAX) / BYTE_MAX * C.DIAL_MAX,
        )
        for listener in self.channels:
            if listener == packet.channel or self._rng.random() < self.loss:
                continue
            deliver_at = now + float(self._rng.uniform(*self.delay_s))
            heapq.heappush(self._queue, (deliver_at, self._order, listener, packet))
            self._order += 1

    def receive(self, now: float) -> list[tuple[int, Heard]]:
        """Every (listener channel, Heard) due by `now`, oldest first."""
        out = []
        while self._queue and self._queue[0][0] <= now:
            deliver_at, _, listener, packet = heapq.heappop(self._queue)
            out.append((listener, Heard(packet=packet, snr_db=ROOM_SNR_DB, received_at=deliver_at)))
        self.delivered += len(out)
        return out
