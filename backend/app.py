"""The backend process: wiring, main loop, /ws and run modes (SPEC §4.7, §4.8, §10). Only P4 edits this file."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import logging
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend import config as C
from backend.audio import countin, modem
from backend.audio.synth import Synth
from backend.contracts import AdviserPacket, AdviserState, Bar, Heard
from backend.data import history_payload, load_bars, replay_range
from backend.finance import Effectiveness, Hedger, PnL
from backend.replay import Clock

log = logging.getLogger("storm.app")

CHORDS = ["A", "Bm", "C♯m", "D", "E", "F♯m", "G♯dim"]  # SPEC §8.1, one per dial step
STEP_HYSTERESIS = 0.6  # SPEC §8.3
SMOKE_BARS = 200  # SPEC §4.8 --smoke
SMOKE_MIN_PACKETS = 3
SMOKE_TIMEOUT_S = 160.0  # virtual seconds: ~119 bars at 1 bar/s plus the count-in
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _iso(t: Any) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _db(x: float) -> float:
    return 10 ** (x / 20)


class StandInAdviser:
    """Stand-in until `backend/adviser.py` (P3-A) lands: hedges at a FIXED dial and never moves.

    Same interface as SPEC §4.6 `Adviser`, so app.py switches to the real one automatically.
    It still tracks heard peers, so `heard` and `leader_channel` are real.
    """

    def __init__(self, channel: int, start_dial: float) -> None:
        self.channel = channel
        self.dial = float(start_dial)
        self.step = round(self.dial)
        self.hedger = Hedger(C.H_MIN_BARS * 2**self.dial)
        self.eff = Effectiveness()
        self.pnl = PnL()
        self.score = 1.0
        self.peers: dict[int, tuple[float, float, float]] = {}  # channel -> (dial, score, heard_at)
        self._seq = 0
        self._now = 0.0

    def on_bar(self, bar: Bar) -> AdviserState:
        _, rH = self.hedger.update(bar)
        self.score = self.eff.update(bar.rS, rH)
        unhedged, hedged = self.pnl.update(bar.rS, rH)
        if abs(self.dial - self.step) > STEP_HYSTERESIS:
            self.step = round(self.dial)
        live = {c: p for c, p in self.peers.items() if self._now - p[2] <= C.LOST_AFTER_S}
        leader = min([(-self.score, self.channel)] + [(-p[1], c) for c, p in live.items()])[1]
        return AdviserState(self.channel, self.dial, self.step, self.hedger.half_life_bars, self.hedger.h,
                            self.score, unhedged, hedged, leader, len(live), False)

    def on_heard(self, heard: Heard) -> None:
        p = heard.packet
        if isinstance(p, AdviserPacket) and p.channel != self.channel:
            self.peers[p.channel] = (p.dial, p.score, heard.received_at)

    def decide(self, now: float) -> None:
        self._now = now  # never moves: the real rule (§7.3) is P3-A

    def packet(self) -> AdviserPacket:
        seq, self._seq = self._seq, (self._seq + 1) % 16
        return AdviserPacket(self.channel, seq, min(max(self.score, 0.0), 1.0), self.dial)

    def snapshot(self) -> Any:
        return copy.deepcopy({k: v for k, v in self.__dict__.items() if k not in ("peers", "_seq", "_now")})

    def restore(self, snap: Any) -> None:
        self.__dict__.update(copy.deepcopy(snap))


try:  # use P3-A's adviser as soon as it exists
    from backend.adviser import Adviser  # type: ignore[attr-defined]
except ImportError:
    Adviser = StandInAdviser  # type: ignore[misc,assignment]


class Mac:
    """One Mac's brain: clock → adviser → synth, packets in and out, UI messages (SPEC §4.7)."""

    def __init__(self, bars: list[Bar], channel: int, conductor: bool, dial: float | None = None,
                 adviser_cls: type = Adviser) -> None:
        self.bars, self.channel, self.conductor = bars, channel, conductor
        self.first, self.last = replay_range(bars)
        self.adviser = adviser_cls(channel, C.START_DIALS[channel] if dial is None else dial)
        state = None
        for bar in bars[: self.first]:  # warm-up (§4.7 startup step 3)
            state = self.adviser.on_bar(bar)
        self.warm = self.adviser.snapshot()
        self.state: AdviserState = state if state is not None else self.adviser.on_bar(bars[0])
        self.bar = self.first - 1  # last processed bar
        self.clock = Clock(bars, conductor)
        self.synth = Synth()
        self.synth.set(self.state.step, self.state.score)
        self.paused = True
        self._last_decide = -1e9
        self.history = history_payload(bars)

    # --- the main-loop body ---
    def step(self, dt: float, now: float) -> None:
        tick = self.clock.tick(dt)
        if tick.reset:
            self.adviser.restore(self.warm)
            self.bar = self.first - 1
        for bar in tick.bars:  # in order, never skip
            self.state = self.adviser.on_bar(bar)
            self.bar = bar.i
        self.synth.set(self.state.step, self.state.score)
        if now - self._last_decide >= C.DECISION_PERIOD_S:
            self.adviser.decide(now)
            self._last_decide = now

    def next_packet(self) -> AdviserPacket:
        """Every Mac sends adviser packets only; the conductor's clock is the count-in (SPEC §9.4)."""
        return self.adviser.packet()

    def on_heard(self, heard: Heard, now: float) -> None:
        if isinstance(heard.packet, AdviserPacket):  # clock packets are no longer sent; ignore any heard
            self.adviser.on_heard(heard)

    def on_count_in(self, lag: float = 0.0) -> None:  # COUNT-IN: a follower heard beat 4, `lag` s ago
        if not self.conductor:
            self.clock.on_count_in(lag)
            self.paused = False

    # --- UI ---
    def handle(self, msg: dict) -> str | None:
        """Apply a UI message. Returns an error message if refused (§10.2)."""
        if not self.conductor:  # COUNT-IN: start, pause, reset and speed are conductor-only
            return "following the conductor; controls disabled"
        if msg.get("type") == "control":
            action = msg.get("action")
            if action == "start":
                self.clock.start(); self.paused = False  # conductor: begins a new count-in
            elif action == "pause":
                self.clock.pause(); self.paused = True
            elif action == "reset":
                self.clock.reset(); self.paused = True
            else:
                return f"unknown action {action!r}"
        elif msg.get("type") == "speed" and isinstance(msg.get("step"), int):
            self.clock.set_speed(msg["step"])
        else:
            return "unknown message"
        return None

    def hello(self) -> dict:
        bars = self.history["bars"]
        return {"type": "hello", "channel": self.channel, "conductor": self.conductor,
                "replayStart": bars[0]["time"], "replayEnd": bars[-1]["time"],
                "shockTime": C.SHOCK_TIME.replace("Z", ":00Z"), "speeds": list(C.SPEED_BARS_PER_S), "chords": CHORDS}

    def state_message(self) -> dict:
        s, bar = self.state, max(self.bar, self.first)
        return {"type": "state", "bar": self.bar, "time": _iso(self.bars[bar].time), "speed": self.clock.speed_step,
                "paused": self.paused, "clock": self.clock.status,
                "adviser": {"channel": s.channel, "dial": round(s.dial, 3), "step": s.step, "chord": CHORDS[s.step],
                            "halfLifeHours": round(s.half_life_bars * C.BAR_MINUTES / 60, 2), "h": round(s.h, 4),
                            "score": round(s.score, 4), "pnlUnhedgedPct": round(s.pnl_unhedged_pct, 3),
                            "pnlHedgedPct": round(s.pnl_hedged_pct, 3), "leaderChannel": s.leader_channel,
                            "heard": s.heard, "inTrial": s.in_trial}}


# ---------------------------------------------------------------- software loopback (SPEC §4.8)

class LoopbackRoom:
    """Two Macs in one process (channel 0 conductor, channel 1 follower) joined through VirtualAir."""

    def __init__(self, bars: list[Bar], snr_db: float, chord_gain_db: float, pilot_gain_db: float) -> None:
        from backend.mocks import VirtualAir
        self.macs = [Mac(bars, 0, True), Mac(bars, 1, False)]
        self.decoders = [modem.Decoder(m.channel) for m in self.macs]
        self.detector = countin.CountInDetector()  # COUNT-IN: the follower listens; the conductor never does
        self.air = [VirtualAir(snr_db, tone_amplitude=_db(pilot_gain_db), seed=k) for k in range(2)]
        self.pilot: list[deque[np.ndarray]] = [deque(), deque()]
        self.chord_gain, self.pilot_gain = _db(chord_gain_db), _db(pilot_gain_db)
        self.t = 0.0  # virtual seconds

    def _pilot_chunk(self, k: int, n: int) -> np.ndarray:
        out, got, q = np.zeros(n, np.float32), 0, self.pilot[k]
        while got < n and q:
            a = q.popleft()
            take = min(n - got, len(a))
            out[got : got + take] = a[:take]
            if take < len(a):
                q.appendleft(a[take:])
            got += take
        return out

    def step(self, dt: float) -> None:
        """Advance virtual time by dt: main-loop work, then dt of audio through the air."""
        for k, mac in enumerate(self.macs):
            if mac.clock.take_count_in(sum(len(a) for a in self.pilot[k]) / C.SAMPLE_RATE):  # COUNT-IN: play the clicks
                self.pilot[k].append(countin.clicks() * _db(C.COUNT_IN_GAIN_DB) / self.pilot_gain)
            mac.step(dt, self.t)
            if not self.pilot[k]:
                self.pilot[k].append(modem.encode(mac.next_packet()))
        n = int(round(dt * C.SAMPLE_RATE))
        outs = [m.synth.render(n).copy() * self.chord_gain + self._pilot_chunk(k, n) * self.pilot_gain
                for k, m in enumerate(self.macs)]
        for k, mac in enumerate(self.macs):
            heard_audio = self.air[k].mix(outs)
            for heard in self.decoders[k].feed(heard_audio, self.t):
                mac.on_heard(heard, self.t + dt)
            if not mac.conductor and (lag := self.detector.feed(heard_audio)) is not None:  # COUNT-IN
                mac.on_count_in(lag)
        self.t += dt


def run_smoke(bars: list[Bar], snr_db: float = 0.0, chord_gain_db: float = C.CHORD_GAIN_DB,
              pilot_gain_db: float = C.PILOT_GAIN_DB) -> bool:
    """--loopback --smoke: count-in, then replay at the default speed until ≥200 bars and ≥3 packets decoded by each
    Mac (virtual time). The follower must have started within 1 bar of the conductor."""
    room = LoopbackRoom(bars, snr_db, chord_gain_db, pilot_gain_db)
    conductor, follower = room.macs
    dt = 1 / C.LOOP_HZ
    target_bars = min(SMOKE_BARS, conductor.last - conductor.first + 1)  # 2-hour bars: the replay is ~119 bars
    while room.t < 1.5:  # let the follower's detector learn the noise floor
        room.step(dt)
    conductor.handle({"type": "control", "action": "start"})
    while room.t < SMOKE_TIMEOUT_S:
        room.step(dt)
        done_bars = conductor.bar - conductor.first + 1 >= target_bars
        if done_bars and all(d.stats["packets"] >= SMOKE_MIN_PACKETS for d in room.decoders):
            break
    stats = [d.stats for d in room.decoders]
    gap = conductor.bar - follower.bar
    log.info("smoke: %.1f virtual s, conductor bar %d, follower bar %d (gap %d), decode stats %s",
             room.t, conductor.bar, follower.bar, gap, stats)
    return (all(s["packets"] >= SMOKE_MIN_PACKETS for s in stats) and conductor.bar - conductor.first + 1 >= target_bars
            and 0 <= gap <= 1)


# ---------------------------------------------------------------- web server and main loop

def create_app(mac: Mac, loop_body: Any) -> FastAPI:
    """FastAPI app with /ws and the built frontend at / (SPEC §4.2, §10)."""
    clients: set[WebSocket] = set()

    async def broadcaster() -> None:
        last_ws = 0.0
        while True:
            await asyncio.sleep(1 / C.LOOP_HZ)
            loop_body()
            now = time.monotonic()
            if now - last_ws >= 1 / C.WS_HZ and clients:
                last_ws = now
                text = json.dumps(mac.state_message())
                for ws in list(clients):
                    try:
                        await ws.send_text(text)
                    except Exception:
                        clients.discard(ws)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        task = asyncio.create_task(broadcaster())
        yield
        task.cancel()

    app = FastAPI(lifespan=lifespan)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(json.dumps(mac.hello()))
        await ws.send_text(json.dumps(mac.history))
        clients.add(ws)
        try:
            while True:
                try:
                    msg = json.loads(await ws.receive_text())
                except json.JSONDecodeError:
                    continue
                err = mac.handle(msg) if isinstance(msg, dict) else "unknown message"
                if err:
                    await ws.send_text(json.dumps({"type": "error", "message": err}))
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="ui")
    else:
        @app.get("/")
        def no_ui() -> PlainTextResponse:
            return PlainTextResponse("UI not built. Run: cd frontend && npm install && npm run build")

    return app


def live_body(mac: Mac, engine: Any, extra: list[StandInAdviser]) -> Any:
    """Main-loop body for real sound (SPEC §4.7). `extra` = --fake-neighbour advisers sharing the speaker."""
    state = {"last": time.monotonic(), "turn": 0}
    lead_in = mac.first

    def body() -> None:
        now = time.monotonic()
        dt, state["last"] = now - state["last"], now
        before = mac.bar
        if mac.clock.take_count_in(engine.pending() / C.SAMPLE_RATE):  # COUNT-IN: queue the clicks behind any pilots
            engine.send_count_in(countin.clicks())
        mac.step(dt, now)
        for adv in extra:  # the fake neighbour follows our bars with its fixed dial
            for bar in mac.bars[max(before + 1, lead_in) : mac.bar + 1]:
                adv.on_bar(bar)
        if engine.pending() == 0:
            senders = [mac.next_packet] + [a.packet for a in extra]
            engine.send(modem.encode(senders[state["turn"] % len(senders)]()))
            state["turn"] += 1
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m backend.app", description="Storm Chorus backend (SPEC §4.8)")
    p.add_argument("--channel", type=int, default=0, choices=range(4))
    p.add_argument("--conductor", action="store_true")
    p.add_argument("--dial", type=float)
    p.add_argument("--fake-neighbour", type=float, metavar="D")
    p.add_argument("--loopback", action="store_true")
    p.add_argument("--snr-db", type=float, default=0.0)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--chord-gain-db", type=float, default=C.CHORD_GAIN_DB)
    p.add_argument("--pilot-gain-db", type=float, default=C.PILOT_GAIN_DB)
    p.add_argument("--input-device")
    p.add_argument("--output-device")
    p.add_argument("--port", type=int, default=C.PORT)
    p.add_argument("--log-level", default="INFO")
    a = p.parse_args(argv)
    logging.basicConfig(level=a.log_level.upper(), stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if Adviser is StandInAdviser:
        log.warning("backend/adviser.py not found: using a stand-in adviser that never moves its dial")

    bars = load_bars()
    if a.smoke:
        if not a.loopback:
            p.error("--smoke needs --loopback")
        ok = run_smoke(bars, a.snr_db, a.chord_gain_db, a.pilot_gain_db)
        log.info("smoke %s", "passed" if ok else "FAILED")
        return 0 if ok else 1

    import uvicorn

    if a.loopback:
        room = LoopbackRoom(bars, a.snr_db, a.chord_gain_db, a.pilot_gain_db)
        mac = room.macs[0]  # the UI shows the conductor
        clock_state = {"last": time.monotonic()}

        def body() -> None:
            now = time.monotonic()
            room.step(min(now - clock_state["last"], 0.2)); clock_state["last"] = now
        app = create_app(mac, body)
    else:
        mac = Mac(bars, a.channel, a.conductor, a.dial)
        extra: list[StandInAdviser] = []
        if a.fake_neighbour is not None:
            nb = StandInAdviser((a.channel + 1) % 4, a.fake_neighbour)
            for bar in bars[: mac.first]:
                nb.on_bar(bar)
            extra.append(nb)
        from backend.audio.engine import Engine
        loop_ref: dict[str, asyncio.AbstractEventLoop] = {}
        decoder = modem.Decoder(a.channel)
        detector = None if a.conductor else countin.CountInDetector()  # COUNT-IN: the conductor never listens

        def on_frames(block: np.ndarray, t: float) -> None:  # decoder thread
            if detector is not None and (lag := detector.feed(block)) is not None:
                loop_ref["loop"].call_soon_threadsafe(mac.on_count_in, lag)
            for heard in decoder.feed(block, t):
                loop_ref["loop"].call_soon_threadsafe(mac.on_heard, heard, time.monotonic())

        dev = lambda d: int(d) if d is not None and d.isdigit() else d  # noqa: E731
        engine = Engine(mac.synth, on_frames, a.chord_gain_db, a.pilot_gain_db, dev(a.input_device), dev(a.output_device))
        body = live_body(mac, engine, extra)

        def started_body() -> None:
            if "loop" not in loop_ref:
                loop_ref["loop"] = asyncio.get_running_loop()
                engine.start()
                log.info("audio started on channel %d%s", a.channel, " (conductor)" if a.conductor else "")
            body()
        app = create_app(mac, started_body)

    log.info("open http://localhost:%d", a.port)
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
