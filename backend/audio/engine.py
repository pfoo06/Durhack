"""Full-duplex audio I/O (SPEC 4.7). sounddevice is imported lazily in start()."""
import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np

from backend import config as C

log = logging.getLogger(__name__)


class Engine:
    """Plays synth chord + queued pilot samples; hands mic blocks to on_frames(block, t) on a thread."""

    def __init__(self, synth: Any, on_frames: Callable[[np.ndarray, float], None],
                 chord_gain_db: float = C.CHORD_GAIN_DB, pilot_gain_db: float = C.PILOT_GAIN_DB,
                 input_device: str | int | None = None, output_device: str | int | None = None) -> None:
        self.synth = synth
        self.on_frames = on_frames
        self.chord_gain = 10 ** (chord_gain_db / 20)
        self.pilot_gain = 10 ** (pilot_gain_db / 20)
        self.devices = (input_device, output_device)
        self._pilot: deque[np.ndarray] = deque()  # BLOCK-sized chunks; append/popleft are thread-safe
        self._cur = np.zeros(0, np.float32)  # callback-owned leftover of a partly played chunk
        self._mic_q: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stats = {"xruns": 0, "mic_drops": 0}
        self._stream: Any = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        import sounddevice as sd  # lazy: tests and loopback need no PortAudio

        self._running = True
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()
        self._stream = sd.Stream(samplerate=C.SAMPLE_RATE, blocksize=C.BLOCK, channels=(1, 2), dtype="float32",
                                 latency="low", device=self.devices, callback=self._callback)
        self._stream.start()

    def stop(self) -> None:
        self._running = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def send(self, samples: np.ndarray) -> None:
        """Queue pilot samples (peak 1.0; pilot gain is applied at playback)."""
        s = np.asarray(samples, np.float32)
        for a in range(0, len(s), C.BLOCK):
            self._pilot.append(s[a : a + C.BLOCK])

    def send_count_in(self, samples: np.ndarray) -> None:
        """Queue count-in clicks (peak 1.0) behind any pilots; played at COUNT_IN_GAIN_DB, not the pilot gain."""
        self.send(np.asarray(samples, np.float32) * (10 ** (C.COUNT_IN_GAIN_DB / 20) / self.pilot_gain))

    def pending(self) -> int:
        """Pilot samples still queued."""
        return len(self._cur) + sum(len(a) for a in tuple(self._pilot))

    def stats(self) -> dict:
        return dict(self._stats, pending=self.pending())

    def _next_pilot(self, frames: int) -> np.ndarray:
        out = np.zeros(frames, np.float32)
        got = 0
        while got < frames:
            if not len(self._cur):
                try:
                    self._cur = self._pilot.popleft()
                except IndexError:
                    break
            n = min(frames - got, len(self._cur))
            out[got : got + n] = self._cur[:n]
            self._cur = self._cur[n:]
            got += n
        return out

    def _callback(self, indata: np.ndarray, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        """Audio thread: no FFTs, logging, locks or I/O in here."""
        if status:
            self._stats["xruns"] += 1
        out = self.synth.render(frames) * self.chord_gain
        out += self._next_pilot(frames) * self.pilot_gain
        np.clip(out, -1.0, 1.0, out=out)
        outdata[:, 0] = out
        outdata[:, 1] = out
        try:
            self._mic_q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            self._stats["mic_drops"] += 1

    def _decode_loop(self) -> None:
        n = 0
        anchor = 0.0
        while self._running:
            try:
                block = self._mic_q.get(timeout=0.1)
            except queue.Empty:
                continue
            if n == 0:
                anchor = time.monotonic()
            try:
                self.on_frames(block, anchor + n / C.SAMPLE_RATE)
            except Exception:
                log.exception("on_frames failed")
            n += len(block)
