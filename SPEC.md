# Storm Chorus: technical spec

> **Status:** v2, 2026-11-14. Built from the team Q&A, then expanded into the single reference for the project.
> **Team:** 4 people (P1–P4), names assigned after review. See [§12](#12-team-and-agent-plan).

---

## 0. How to use this document

**This is the single source of truth.** Every person and every agent works from it. If code, a chat message or another document disagrees with it, **this document wins** until a pull request changes it.

### Wording
- **MUST** means required. If you can't do it, stop and tell your human.
- **SHOULD** means the default. Break it only with a reason written in the pull request description.
- **MAY** means optional.
- *Expected* means a prediction that hasn't been checked on real data yet. Every *expected* claim names the tool or test that checks it.

### Reading guide
| You are working on | Read first | Then |
| --- | --- | --- |
| Anything (everyone) | §1, §2, §3 | §12 (your lane and the rules) |
| Data (P1) | §5 | §4.4–4.6, §13 |
| Finance (P1) | §6 (all of it, including §6.4) | §4.4–4.6, §13 |
| Advisers, sweep, simulation (P3) | §6.4, §7 | §6, §4.4–4.8, §13 |
| Audio and music (P2) | §8, §9 | §4.4–4.8, §13 |
| UI and integration (P4) | §10, §4 | §14, §13 |

### Changing this document
- Spec changes go through a pull request like code. Use the title prefix `spec:`.
- A pull request that changes behaviour MUST update the spec in the same pull request.
- If you find a gap or a contradiction, **don't guess silently**. Choose the simplest reading, write it in the pull request description under "Spec gap", and tell your human so the spec gets fixed.

---

## 1. What we're building

### The one-paragraph version
Four MacBooks each play the role of an **FX hedging adviser**. They all replay the same historical market crisis: the day the Swiss central bank removed the euro–franc floor, 15 January 2015. Each adviser protects the same currency position, but **each starts with a different strategy**. Each Mac plays a chord. **The chord's root shows its strategy, and how dissonant it sounds shows how well that strategy is working.** The Macs aren't networked. They **communicate only through sound**: each one listens with its microphone, works out which adviser is doing best, and moves its own strategy towards that one. The room starts in **harmony** (different strategies, all doing fine), turns **dissonant** in the storm (everyone failing), then **converges into unison** (all advisers move to the strategy that works).

### The finance setup, in plain terms
- A **UK company owes a Swiss supplier francs (CHF)**. It pays in the future, so if the franc rises against the pound, the bill gets more expensive in pounds.
- Hedging the franc directly is what we *don't* do. The company **cross-hedges with euros (EUR)**, because the franc was pinned to the euro at 1.20, so euros behaved almost like francs.
- **How much** euro to hold per franc owed is the **hedge ratio h**. Each adviser estimates h from recent market data.
- **The strategy is how much history the adviser trusts** when estimating h: an hour, or several days. That's its **reaction speed**.
- On 15 January 2015 the floor was removed and the franc–euro link broke. The hedge stopped working. Advisers that adapt their h well score better afterwards. Advisers that cling to the old relationship score worse.

### The arc of the piece (default speed, about 2 minutes)
| Time | Market | What the room sounds like | Why |
| --- | --- | --- | --- |
| 0:00–0:41 | Calm, the floor holds | Four different chords, all clean (**harmony**) | Every strategy hedges well. Score gaps are too small for anyone to move. |
| about 0:41 | The floor breaks | Every chord turns harsh at once (**dissonance**) | No hedge helps on the shock itself, and everyone's score collapses together |
| 0:53–1:30 | The aftermath | Chords shift one by one towards one root | Strategies now differ. Advisers hear the leader and move towards it. |
| 1:30–2:00 | The new normal | One chord, getting cleaner (**unison**) | All advisers have converged on the strategy that works |

### Prize targets
| Prize | Why we fit |
| --- | --- |
| DurHack theme "Composition" | The piece is composed by the market and the advisers, and composition is literally how the strategy is built |
| SGX FX (market storm) | A real FX storm, real cross-hedging and basis risk, and the standard minimum-variance hedge ratio |
| Marshall Wace "New Worlds" | Strategy signals carried in a new medium: sound |
| Neptune North (stretch) | Independent actors that keep working when communication fails (§7.5, §9.4) |

---

## 2. Glossary
Use these words with exactly these meanings in code, comments, pull requests and the UI.

| Term | Meaning |
| --- | --- |
| **Adviser** | One instance of the strategy logic. One per Mac (plus one optional fake neighbour, §4.8). Identified by its **channel**. |
| **Bar** | One time step of the replay: **15 minutes** of market time. Weekend hours have no bars. |
| **Bar index `i`** | The bar's position in `data/chf2015.csv`, starting from 0. Absolute: it counts warm-up bars too. |
| **Replay** | Playing bars from `REPLAY_START` to `REPLAY_END` at a chosen speed (bars per second of real time). |
| **Warm-up** | Bars before `REPLAY_START`. Processed instantly and silently at startup, so the estimates are settled. |
| **Shock** | 15 January 2015, 09:30 UTC: the Swiss National Bank's announcement. |
| **S** | The exposure price: the GBP value of 1 CHF. |
| **F** | The proxy (hedge instrument) price: the GBP value of 1 EUR. |
| **rS, rF** | Log returns of S and F over one bar: `ln(p_t / p_{t−1})`. |
| **Hedge ratio `h`** | How much EUR exposure to hold per unit of CHF exposure. Estimated per adviser. |
| **Hedged return `rH`** | `rS − h_used · rF`: what's left after the hedge. |
| **Dial** | The adviser's strategy: a continuous number from **0.0 to 6.0**. |
| **Step** | The dial rounded to a whole number 0–6, with hysteresis (§8.3). Picks the chord. |
| **Half-life `H`** | How the dial turns into memory: `H = 4 · 2^dial` bars. After H bars, old data counts half as much. |
| **λ (lambda)** | The decay per bar: `λ = 0.5^(1/H)`. |
| **Score `E`** | Rolling hedge effectiveness over the last `W = 96` bars, from 0 to 1. Higher is better. |
| **Variance** | **Only** the statistic: how much a return series wobbles. Never use it to mean "how different the advisers are". |
| **Spread** | How far apart the advisers' dials are (the largest minus the smallest). Convergence makes spread shrink. |
| **Leader** | The adviser with the highest score among this one and every adviser it currently hears. |
| **Heard** | Decoded from the microphone within the last `LOST_AFTER_S` seconds. |
| **Lost** | Not heard for `LOST_AFTER_S` seconds. Lost advisers are ignored. |
| **Trial** | The period after a dial move, during which the adviser checks whether the move helped (§7.4). |
| **Channel** | The Mac's identity (0–3) and its frequency band for pilot tones. |
| **Pilot tones** | High-frequency tones (about 14–18.7 kHz) that carry data packets between Macs. |
| **Symbol** | One tone carrying 4 bits (one of 16 tones in a channel). |
| **Packet** | 10 symbols: a sync marker, a header, a payload and a checksum (§9.2). |
| **Conductor** | The one Mac whose replay clock the others follow (`--conductor`). |
| **Follower** | Any Mac that isn't the conductor. |
| **Clock status** | `conductor`, `following` (locked to a heard conductor) or `free` (running alone). |

---

## 3. Decisions already made (don't relitigate)
Each line is settled. To change one, raise it with the whole team. Don't change it inside a feature pull request.

| # | Decision | Why |
| --- | --- | --- |
| D1 | **Macs communicate only through sound.** No Wi-Fi, no network sockets between Macs. | It's the concept, and the resilience story |
| D2 | **Each Mac runs its own Python backend and its own React UI**, on localhost | No shared server to fail |
| D3 | **Python owns all audio input and output.** The browser makes no sound and doesn't use the mic. | One process controls timing. numpy does the signal processing. Browser background tabs get throttled. |
| D4 | **Data travels on pilot tones. Chords are never used for decisions.** | In unison every Mac plays the same chord, so chords can't tell advisers apart |
| D5 | **The strategy has exactly one dimension: reaction speed (the dial).** | It maps cleanly to one root note, and convergence on a single dimension is easy to hear |
| D6 | **Every adviser runs identical maths. Only the dial differs.** | Score differences then come from strategy alone |
| D7 | **Score = rolling hedge effectiveness over a fixed 96-bar window, the same for everyone** | It's a standard measure, and comparable across advisers |
| D8 | **MVP convergence = step 20% towards the leader, with trial and revert** | Simple and easy to hear. Particle swarm optimisation comes after the MVP. |
| D9 | **One conductor sends the replay clock. Followers fall back to their own timing if it's lost.** | Keeps the room in sync without a network |
| D10 | **Everything stays in A major** (one chord per dial step) | Moving between strategies still sounds musical |
| D11 | **The position is a CHF payable** (the company owes francs), hedged by holding EUR | The franc's jump is a loss, which makes a clear storm story |
| D12 | **Trial and revert compares the score *gap* to the leader, not the raw score** (§7.4) | The market moves all scores together, so a raw-score check would revert good moves during the storm |
| D13 | **Pilot tones sit exactly on FFT bins, and decoding uses symbol timing from the sync marker** (§9) | No extra filtering libraries, and it copes with echoes in the hall |
| D14 | **Historical data only, replayed from a prepared CSV** | No live feeds, no API keys |
| D15 | **The microphone is the only sensor in the MVP. The lid angle comes after.** | Scope |

### Non-goals
- No real trading, real money, live market data or investment advice.
- No baskets of several currencies: one exposure, one proxy.
- No network fallback "just in case". If sound fails, we demo closer together or in a quieter spot (§15).
- No Windows or Linux support (CI runs tests on Linux, but the product targets macOS).
- No logins, no persistence and no database.

---

## 4. Architecture

### 4.1 One Mac
```
┌───────────────────────── one Mac (every Mac is the same) ─────────────────────────┐
│                                                                                   │
│  React UI (browser, localhost) ◀── WebSocket /ws (state ~10 Hz) ──▶ Python backend │
│   - own adviser status                    controls (start, pause,   - replay clock │
│   - storm chart                           reset, speed)             - finance      │
│                                                                     - adviser      │
│                                                                     - audio I/O ───┼──▶ speaker: chord + pilot tones
│                                                                                ◀───┼─── microphone: other Macs
└───────────────────────────────────────────────────────────────────────────────────┘
        No network between Macs. Sound is the only link.
```

### 4.2 Stack
| Part | Choice | Notes |
| --- | --- | --- |
| Language | Python **3.11+** | Uses `X \| Y` type unions and `dataclasses` |
| Web server | FastAPI + uvicorn | One WebSocket at `/ws`. It also serves the built frontend from `frontend/dist` at `/`. |
| Maths | numpy, pandas | pandas only in data prep and loading. numpy everywhere else. |
| Audio | sounddevice (PortAudio) | **Imported lazily** inside `audio/engine.py`, so tests and loopback mode run without PortAudio |
| Plots | matplotlib | Only for `tools/` and `sim.py` (offline), never imported by the app |
| Tests | pytest | |
| Frontend | React 18 + Vite + **TypeScript**, Recharts | The WebSocket message types are mirrored in `frontend/src/protocol.ts` |

`requirements.txt` (exact versions get pinned in the first skeleton pull request):
```
fastapi
uvicorn[standard]
numpy
pandas
sounddevice
matplotlib
pytest
```
No other Python dependency without a pull request that gives a one-line reason (§12.3 rule 3). **scipy is not needed.** Tones are read straight from FFT bins (D13).

### 4.3 Components and data flow inside the backend
```
                  ┌───────────────────────── backend (one Python process) ─────────────────────────────┐
                  │                                                                                     │
data/chf2015.csv ─┼─▶ data.load_bars ─▶ replay.Clock ──Tick(bars, reset)──▶ app main loop               │
                  │                        ▲      ▲                           │                         │
                  │        ClockPacket ────┘      └── speed / start / pause ──┤◀── WebSocket ◀── React  │
                  │        (from Decoder)            reset (from UI)          │                         │
                  │                                                           ▼                         │
                  │                                          adviser.Adviser.on_bar(bar)                │
                  │                                            └─ uses finance.Hedger,                  │
                  │                                               finance.Effectiveness, finance.PnL    │
                  │                                                           │ AdviserState            │
                  │                         ┌─────────────────────────────────┼─────────────┐           │
                  │                         ▼                                 ▼             ▼           │
                  │              synth.Synth.set(step, score)    modem.encode(packet)   WebSocket ──────┼──▶ React
                  │                         │                                 │                         │
                  │                         ▼                                 ▼                         │
                  │              audio.engine: callback mixes chord + queued pilot ──────────────────────┼──▶ speaker
                  │                                                                                     │
                  │              audio.engine: mic frames ─▶ queue ─▶ decoder thread ─▶ modem.Decoder   │◀── mic
                  │                                                         │ Heard                     │
                  │                                                         ▼                           │
                  │                              Adviser.on_heard(...)  or  Clock.on_clock(...)         │
                  └─────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.4 Contracts (`backend/contracts.py`)
These dataclasses are the **only** objects that cross between workstreams.
- **They're frozen at +1h.** After that, a change needs a pull request titled `contract: ...`, with a comment saying "approved" from the human owner of every role that uses the changed type.
- Never add a field "for later".

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ClockStatus = Literal["conductor", "following", "free"]

@dataclass(frozen=True)
class Bar:                    # one row of data/chf2015.csv. Produced by data.load_bars.
    i: int                    # absolute bar index (0 = first row of the CSV)
    time: datetime            # bar START time, timezone-aware UTC
    S: float                  # GBP per 1 CHF
    F: float                  # GBP per 1 EUR
    eurchf: float             # CHF per 1 EUR (chart and sanity check only, never used in finance)
    rS: float                 # ln(S_i / S_{i-1}); 0.0 on row 0
    rF: float                 # ln(F_i / F_{i-1}); 0.0 on row 0
    rho: float                # 96-bar rolling correlation of rS and rF; 0.0 where undefined

@dataclass(frozen=True)
class Tick:                   # what replay.Clock.tick returns
    bars: list[Bar]           # bars to process, in order (may be empty, may be many)
    reset: bool               # True = throw away all adviser state first, then process bars

@dataclass(frozen=True)
class AdviserState:           # produced by Adviser.on_bar. Read by app, synth and UI.
    channel: int              # 0–3
    dial: float               # 0.0–6.0, continuous
    step: int                 # 0–6, the chord (rounded with hysteresis, §8.3)
    half_life_bars: float     # 4 * 2**dial
    h: float                  # hedge ratio that will be used on the NEXT bar
    score: float              # E, 0.0–1.0
    pnl_unhedged_pct: float   # cumulative, % of exposure, positive = gain
    pnl_hedged_pct: float
    leader_channel: int       # equals channel when this adviser leads
    heard: int                # other advisers currently heard (not lost)
    in_trial: bool

@dataclass(frozen=True)
class AdviserPacket:          # adviser info carried on pilot tones
    channel: int              # from the frequency band, not sent as bits
    seq: int                  # 0–15, wraps
    score: float              # 0.0–1.0, sent as a byte: round(score * 255)
    dial: float               # 0.0–6.0, sent as a byte: round(dial / 6 * 255)

@dataclass(frozen=True)
class ClockPacket:            # conductor clock info carried on pilot tones
    channel: int
    seq: int                  # 0–15, wraps (separate counter from adviser packets)
    bar: int                  # absolute bar index when the packet was encoded, 0–4095
    speed_step: int           # 0–7 (§9.4)

@dataclass(frozen=True)
class Heard:                  # one successfully decoded packet
    packet: AdviserPacket | ClockPacket
    snr_db: float             # mean over symbols of (tone energy dB − channel median dB)
    received_at: float        # time.monotonic() at the END of the last symbol's tone
```

### 4.5 Configuration (`backend/config.py`)
**Every tunable number lives here, and only here.** No magic numbers anywhere else. Changing a value is a normal pull request, but the role that owns its group MUST approve it in a comment.

| Constant | Default | Owner | Meaning |
| --- | --- | --- | --- |
| `BAR_MINUTES` | 15 | P1 | Bar size used by data prep |
| `REPLAY_START` | `2015-01-12T00:00Z` | P1 | First replayed bar. Everything before is warm-up. |
| `REPLAY_END` | `2015-01-23T22:00Z` | P1 | Last replayed bar (Friday market close) |
| `SHOCK_TIME` | `2015-01-15T09:30Z` | P1 | For UI markers and phase checks only. Never used in the finance maths. |
| `RHO_WINDOW` | 96 | P1 | Rolling correlation window for the chart |
| `H_MIN_BARS` | 4 | P1 | Half-life at dial 0 |
| `DIAL_MAX` | 6.0 | P1 | Dial range is 0 to `DIAL_MAX` |
| `SCORE_WINDOW` | 96 | P1 | W, the judge's window |
| `H_CLAMP` | (0.0, 2.0) | P1 | Hedge ratio limits (§6.3 step 4) |
| `START_DIALS` | (0, 3, 4, 5) | P3 | Default starting dial for channels 0–3 |
| `DECISION_PERIOD_S` | 2.0 | P3 | How often `Adviser.decide` acts |
| `MOVE_THRESHOLD` | 0.05 | P3 | The leader must beat us by at least this much before we move |
| `STEP_FRACTION` | 0.2 | P3 | The fraction of the gap to the leader's dial moved per decision |
| `SNAP_DISTANCE` | 0.1 | P3 | Within this distance, jump straight to the leader's dial |
| `TRIAL_BARS` | 16 | P3 | Bars to wait before judging a move |
| `REVERT_MARGIN` | 0.05 | P3 | How much the gap may worsen before we revert |
| `BLACKLIST_S` | 10.0 | P3 | Ignore a leader for this long after reverting a move towards it |
| `LOST_AFTER_S` | 10.0 | P3 | Forget an adviser after this long without a packet |
| `SAMPLE_RATE` | 48000 | P2 | Audio sample rate, input and output |
| `BLOCK` | 480 | P2 | Audio callback size (10 ms) |
| `FFT_N` | 2048 | P2 | Decoder analysis window (42.7 ms, bin = 23.4375 Hz) |
| `HOP` | 480 | P2 | Decoder step between analysis windows (10 ms) |
| `PILOT_BASE_BIN` | 598 | P2 | First bin of channel 0 (598 × 23.4375 = 14,015.6 Hz) |
| `CHANNEL_BINS` | 51 | P2 | Width of each channel in bins (1,195 Hz) |
| `TONE_SPACING_BINS` | 3 | P2 | Bins between neighbouring tones (70.3 Hz) |
| `TONE_MS` / `GAP_MS` / `IDLE_MS` | 100 / 60 / 300 | P2 | Symbol tone length, silent gap after each symbol, and silence after each packet |
| `RAMP_MS` | 5 | P2 | Raised-cosine fade at each tone edge |
| `MIN_TONE_DB` | 10.0 | P2 | A tone counts only if it's this far above the channel median |
| `SPEED_BARS_PER_S` | (0, 1, 2, 4, 8, 16, 32, 64) | P2 | Bars per second for speed steps 0–7 |
| `DEFAULT_SPEED_STEP` | 4 | P2 | 8 bars per second |
| `FOLLOW_JUMP_BARS` | 8 | P2 | Bigger errors than this jump or hold, smaller ones trim (§9.4) |
| `FOLLOW_TRIM` | 0.10 | P2 | Maximum ±10% speed adjustment while following |
| `RESET_BACK_BARS` | 96 | P2 | If the conductor is this far behind us, treat it as a reset |
| `CLOCK_LOST_S` | 10.0 | P2 | No clock packet for this long → status becomes `free` |
| `CHORD_GAIN_DB` | −12 | P2 | Chord level (calibrated on the day) |
| `PILOT_GAIN_DB` | −18 | P2 | Pilot level (calibrated on the day) |
| `LOOP_HZ` | 20 | P4 | Main loop rate |
| `WS_HZ` | 10 | P4 | State broadcast rate |
| `PORT` | 8000 | P4 | Backend port |

### 4.6 Module interfaces
Signatures are binding. Behaviour is specified in the section shown.

| Module | Interface | Section | Owner |
| --- | --- | --- | --- |
| `data.py` | `load_bars(path: str = "data/chf2015.csv") -> list[Bar]`; `replay_range(bars) -> tuple[int, int]` (first and last bar index of the replay) | §5 | P1 |
| `finance.py` | `Hedger(half_life_bars)`: `update(bar) -> tuple[float, float]` returns `(h_used, rH)`; `set_half_life(bars)`; attribute `h` (the ratio for the next bar) | §6.3 | P1 |
| | `Effectiveness(window=SCORE_WINDOW)`: `update(rS, rH) -> float` returns E | §6.3 | P1 |
| | `PnL()`: `update(rS, rH) -> tuple[float, float]` returns `(unhedged_pct, hedged_pct)` | §6.3 | P1 |
| `adviser.py` | `Adviser(channel, start_dial)`: `on_bar(bar) -> AdviserState`, `on_heard(heard)`, `decide(now: float)`, `packet() -> AdviserPacket`, `snapshot()` and `restore(snapshot)` for resets | §7 | P3 |
| `sim.py` | `python -m backend.sim [--advisers 4] [--loss 0.1] [--speed 4] [--out sim.png]` | §7.6 | P3 |
| `audio/modem.py` | `encode(packet) -> np.ndarray` (float32, mono, peak 1.0, includes the idle tail); `Decoder(own_channel)`: `feed(frames: np.ndarray, t0: float) -> list[Heard]`; `crc8(data: bytes) -> int` | §9.1–9.3 | P2 |
| `audio/engine.py` | `Engine(synth, on_frames)`: `start()`, `stop()`, `send(samples)`, `pending() -> int` (pilot samples still queued), `stats() -> dict` | §4.7 | P2 |
| `audio/synth.py` | `Synth()`: `set(step: int, score: float)`, `render(n: int) -> np.ndarray` (float32, peak ≤ 1.0, nothing above 8 kHz) | §8 | P2 |
| `audio/chords.py` | (stretch) `ChordListener()`: `feed(frames) -> dict[int, float]` (chord step → match strength 0–1) | §9.5 | P2 |
| `replay.py` | `Clock(bars, conductor: bool)`: `tick(dt) -> Tick`, `start()`, `pause()`, `reset()`, `set_speed(step)`, `on_clock(heard, now)`, `packet() -> ClockPacket`, properties `status`, `speed_step`, `position` | §9.4 | P2 |
| `mocks.py` | `VirtualRoom(loss=0.1, delay_s=(1.6, 2.0))` delivers packets between in-process advisers. `VirtualAir(snr_db=0.0)` mixes the sample buffers of in-process Macs and adds noise. | §4.8 | P3 (Room), P2 (Air) |
| `app.py` | FastAPI app, `/ws`, the main loop, the command-line options and the wiring. **Only P4 edits it.** | §4.7, §10 | P4 |

### 4.7 Threads, timing and the main loop
There are three execution contexts. Get this right and the rest is simple.

**1. Audio callback** (PortAudio thread, every 10 ms, 480 samples). It MUST finish in under 2 ms. It does only this:
```python
def callback(indata, outdata, frames, time_info, status):
    if status: stats["xruns"] += 1
    out = synth.render(frames) * chord_gain            # preallocated inside Synth
    out += next_pilot_chunk(frames) * pilot_gain      # pops from a collections.deque of arrays; zeros if empty
    np.clip(out, -1.0, 1.0, out=out)
    outdata[:, 0] = out; outdata[:, 1] = out          # MacBook speakers are stereo: same signal on both
    try: mic_q.put_nowait(indata[:, 0].copy())
    except queue.Full: stats["mic_drops"] += 1
```
- The stream is `sd.Stream(samplerate=48000, blocksize=480, channels=(1, 2), dtype="float32", latency="low", callback=callback)`.
- No FFTs, no logging, no locks and no file or network access inside the callback.
- `collections.deque.append` and `popleft` are thread-safe in CPython, so the pilot queue needs no lock.

**2. Decoder thread** (an ordinary `threading.Thread`, daemon):
- It takes blocks from `mic_q` (`maxsize=200`, 2 seconds) and keeps a sample counter `n`.
- Each block's time is `t_anchor + n / SAMPLE_RATE`, where `t_anchor = time.monotonic()` at the first block.
- It calls `decoder.feed(block, t)` (and `chord_listener.feed(block)` if enabled), and hands each `Heard` to the asyncio loop with `loop.call_soon_threadsafe(on_heard, heard)`.

**3. Asyncio main loop** (`app.py`, `LOOP_HZ` = 20):
```python
async def main_loop():
    last = time.monotonic(); last_decide = last; last_ws = last
    while True:
        await asyncio.sleep(1 / LOOP_HZ)
        now = time.monotonic(); dt = now - last; last = now
        tick = clock.tick(dt)
        if tick.reset:
            adviser.restore(warm_snapshot)               # state right after warm-up
        for bar in tick.bars:                           # in order, never skip
            state = adviser.on_bar(bar)
        synth.set(state.step, state.score)
        if now - last_decide >= DECISION_PERIOD_S:
            adviser.decide(now); last_decide = now
        if engine.pending() == 0:                        # transmit back-to-back
            pkt = clock.packet() if (conductor and send_clock_next) else adviser.packet()
            send_clock_next = not send_clock_next
            engine.send(modem.encode(pkt))
        if now - last_ws >= 1 / WS_HZ:
            await broadcast(state_message(state, bar, clock)); last_ws = now

def on_heard(heard):                                     # runs on the asyncio loop
    if isinstance(heard.packet, ClockPacket):
        if not conductor: clock.on_clock(heard, time.monotonic())
    else:
        adviser.on_heard(heard)
```
- **Startup order:**
  1. `load_bars`;
  2. create `Adviser`;
  3. **warm-up**: call `on_bar` for every bar before `REPLAY_START`, then `warm_snapshot = adviser.snapshot()`;
  4. create `Clock` positioned at `REPLAY_START`, paused;
  5. start `Engine` and the decoder thread;
  6. start uvicorn and the main loop.
- **Transmit schedule:** a packet lasts 1.6 s plus 0.3 s of idle, so 1.9 s per packet.
  - Followers send an adviser packet every 1.9 s.
  - The conductor alternates clock and adviser packets, so each type goes out every 3.8 s.
- **Fast-forwarding:** `Clock.tick` MAY return up to 200 bars in one tick, when catching up to the conductor. Processing 200 bars takes well under 50 ms.

### 4.8 Run modes and command-line options
**Command:** `python -m backend.app [options]`. Run from the repo root.

| Option | Default | Meaning |
| --- | --- | --- |
| `--channel N` | 0 | This Mac's channel (0–3). **Every Mac in the room MUST use a different one.** |
| `--conductor` | off | This Mac sends the clock. **Exactly one Mac in the room.** |
| `--dial D` | `START_DIALS[channel]` | Starting dial |
| `--fake-neighbour D` | off | Also run a second adviser in-process on channel `(N+1) % 4` with a **fixed** dial D. Its packets are played through the real speaker, and this Mac hears them through the real mic. Used for testing one Mac on its own. |
| `--loopback` | off | No sound hardware. Runs **two** full Macs in one process (channel 0 as conductor, channel 1 as follower), joined through `VirtualAir`. |
| `--snr-db X` | 0 | Noise level for `--loopback` |
| `--smoke` | off | With `--loopback`: replay 200 bars at speed 7, then exit 0 if each Mac decoded at least 3 packets and nothing raised an error. Exit 1 otherwise. |
| `--chord-gain-db X` / `--pilot-gain-db X` | from config | Calibration on the day |
| `--input-device` / `--output-device` | system default | A sounddevice device name or index |
| `--port P` | 8000 | |
| `--log-level` | INFO | Plain `logging` to stderr. Decode stats are logged every 10 s. |

| Mode | How to run | What's real | What's faked | Used by |
| --- | --- | --- | --- | --- |
| **Offline simulation** | `python -m backend.sim` | finance, adviser | the air, through `VirtualRoom` (packet loss and delay, no audio) | P1, P3 |
| **Strategy sweep** | `python tools/sweep.py` | finance only | no advisers talking: each dial runs alone | P3 (and P1 to check the finance) |
| **Software loopback** | `--loopback [--smoke]` | everything, including modem encode and decode | the speaker and mic (`VirtualAir`) | P2, CI |
| **Single Mac** | `--channel 0 --conductor --fake-neighbour 3` | everything, including the real speaker and mic | the other Mac (in-process) | P2, P4 |
| **Room** | `--channel N [--conductor]` on each Mac | everything | nothing | everyone, from +12h |
| **UI mock** | `npm run dev:mock` in `frontend/` | the UI | the backend (a local mock WebSocket replaying `frontend/mock/state.jsonl`) | P4, from hour 1 |

**macOS microphone permission:**
- The **terminal app** (Terminal, iTerm, Ghostty and so on) needs microphone access, under System Settings → Privacy & Security → Microphone. The first run asks for it.
- Agents running inside tmux sessions inherit the terminal's permission.
- Check that Control Center → Mic Mode is **Standard**, not Voice Isolation.
- PortAudio captures raw audio, without the echo cancellation, noise suppression or auto gain that browsers apply. That's another reason audio lives in Python (D3).

---

## 5. Data

### 5.1 Source
- **Dukascopy** free 1-minute bid bars, downloaded with the `dukascopy-node` command-line tool. (HistData was the first plan, but its downloads were blocked on the team's work laptops.)
- You need **January 2015** for three pairs: **EURCHF**, **EURGBP** and **GBPCHF**. From `data/raw/`, run once per pair:
  ```
  npx -y dukascopy-node -i <pair> -from 2015-01-01 -to 2015-02-01 -t m1 -f csv
  ```
  Each run writes `download/<pair>-m1-bid-2015-01-01-2015-02-01.csv`.
- **Format:** a header row, then one row per minute. `timestamp` is milliseconds since the epoch, **already UTC**:
  ```
  timestamp,open,high,low,close
  1421314200000,1.2009,1.2009,1.2009,1.2009
  ```
- ⚠️ **Closed-market filler:** Dukascopy writes a row for every minute, **including when the market is shut** (Sunday daytime and 1 January), repeating the last price. Those rows MUST be dropped (§5.2 step 1), or they look like hours of perfect calm. Don't drop every unchanged minute: EUR/CHF genuinely sat still for long stretches while the floor held.
- **Licence:** Dukascopy's redistribution terms are unchecked. Raw files go in `data/raw/`, which **is gitignored**. Only the prepared `data/chf2015.csv` (about 210 KB) is committed.
- **Fallback:** European Central Bank daily reference rates (a free CSV). It's daily only, so set `BAR_MINUTES` to 1440 and accept a less dramatic replay. Treat this as a last resort.

### 5.2 Preparation (`scripts/prepare_data.py`, run once by P1)
Run it as `python scripts/prepare_data.py data/raw/ data/chf2015.csv`. It MUST:
1. Read the three CSVs. Parse `timestamp` as milliseconds, timezone-aware UTC. Keep **only the close** price. Then keep only:
   - minutes from **2 January 2015** (1 January is a holiday) up to, not including, **24 January 2015** (the end of the replay week);
   - minutes when the market is open: **Sunday 22:00 ≤ t < Friday 22:00 UTC** (§5.3).
2. Resample each pair to `BAR_MINUTES` buckets, labelled by **bucket start**, taking the **last close in the bucket**: `df.resample("15min", label="left", closed="left").last()`.
3. **Inner-join** the three pairs on time. **Drop** any bucket where a pair has no data. **Never forward-fill**: filling in missing data creates fake zero returns, which distort variance.
4. Compute:
   - `S = 1 / GBPCHF` (GBPCHF is quoted as CHF per GBP, so S is GBP per CHF);
   - `F = EURGBP` (GBP per EUR);
   - `eurchf = EURCHF`.
5. Compute the returns `rS = ln(S_i / S_{i−1})` and `rF = ln(F_i / F_{i−1})` between **consecutive rows**. Row 0 gets 0.0.
   - The first bar after a weekend carries the price change over the weekend. **Keep it.** It's real, and tiny compared with the shock.
6. Compute `rho` = the pandas rolling correlation of rS and rF over `RHO_WINDOW` rows. Use 0.0 where it isn't defined.
7. Write the CSV with columns `time,S,F,eurchf,rS,rF,rho`. `time` is ISO 8601 with `Z`. Use full float precision.
8. **Print and assert these checks:**
   - Row count is between 1,400 and 1,700.
   - The first row is on 2 January 2015.
   - There's at least one row on or before `REPLAY_START`, and the replay's last bar exists (the bar starting at `REPLAY_END` − `BAR_MINUTES`, because the market closes at `REPLAY_END`).
   - The bar containing `SHOCK_TIME` exists and has `|rS| > 0.03`.
   - Outside 15 January, `|eurchf − F/S| / eurchf < 0.005`. This proves S and F were built the right way round.
   - Print the largest five `|rS|` with their times. They MUST be on 15 January.

### 5.3 Size and timing of the data (confirmed by the script on the Dukascopy data)
| | Bars | Note |
| --- | --- | --- |
| Warm-up, 2 January to 11 January 23:45 | 576 | 88 on Friday 2 January, 480 in the week of 4 January, 8 on Sunday evening 11 January. More than 2 × the longest half-life (256 bars), so every estimate has settled. |
| Replay, 12 to 23 January | 952 (bar indexes 576 to 1527) | 472 bars in week 1, then 480 in week 2 |
| Shock | bar 326 of the replay (index 902) | Thursday, 3 days and 9.5 hours into the replay. `rS` = 0.188 on the shock bar. |
| Total | 1,528 | Fits the 12-bit bar field in clock packets (maximum 4,095) |

**FX market hours:** the market is open from Sunday 22:00 UTC to Friday 22:00 UTC. Hours with no trading have no bars. Half-lives count **bars, not calendar time**, so weekends don't decay anyone's memory.

### 5.4 Loading (`backend/data.py`)
- `load_bars` reads the CSV with pandas and returns a `list[Bar]`, with `i` equal to the row number.
- `replay_range` returns `(first bar index with time ≥ REPLAY_START, last bar index with time ≤ REPLAY_END)`.
- Load it once at startup and treat it as read-only.

---

## 6. Finance engine

### 6.1 The position
- **A CHF payable:** the company owes francs in the future (D11). If the franc rises against the pound (S goes up), the company loses.
- **The hedge:** hold `h` units of EUR exposure per unit of CHF exposure. If the euro rises against the pound (F goes up), the company gains on the hedge.
- **Per-bar return of the position** (as a fraction of the exposure):
  - unhedged: `−rS`;
  - hedged: `−(rS − h_used · rF) = −rH`.

The variance maths below uses `rH = rS − h·rF`. The minus sign in front doesn't change any variance. It only matters for P&L.

### 6.2 The strategy dial
- `dial` ∈ [0.0, 6.0], continuous.
- `H = H_MIN_BARS · 2^dial` bars. `λ = 0.5^(1/H)`.

| Step | H (bars) | H (trading hours) | Character |
| --- | --- | --- | --- |
| 0 | 4 | 1 | Reacts within the hour |
| 1 | 8 | 2 | |
| 2 | 16 | 4 | |
| 3 | 32 | 8 | About one trading session |
| 4 | 64 | 16 | |
| 5 | 128 | 32 | |
| 6 | 256 | 64 | About 2.7 trading days |

- **The dial is the only thing that differs between advisers (D6).** The data, every formula, `W` and every constant are identical.
- Changing the dial calls `Hedger.set_half_life(H)`. This changes `λ` **from the next bar on**. The existing `cov` and `var` estimates are **kept**: the adviser keeps its own memory and just starts forgetting at a different rate. A move doesn't copy the leader's `h`, only its reaction speed.

### 6.3 What every adviser computes, every bar, in this exact order
Given a bar with returns `rS` and `rF`, and state `cov`, `var`, `h` (initially 0.0, 0.0 and 1.0):

1. **Hedged return, using the ratio decided *before* this bar:**
   `h_used = h`, then `rH = rS − h_used · rF`.
   ⚠️ **Never use a ratio that has seen this bar's returns.** That lets the adviser see the future, and makes every adviser look perfect. The test in §13 catches this.
2. **Update the exponentially weighted estimates** (they assume a mean of zero, which is fine for 15-minute FX returns):
   - `cov ← λ·cov + (1−λ)·rS·rF`
   - `var ← λ·var + (1−λ)·rF²`
3. **New hedge ratio for the next bar:** if `var > 1e−12`, then `h ← cov / var`. Otherwise keep `h`.
   - This is the minimum-variance hedge ratio `ρ·σS/σF`: the slope of a regression of rS on rF.
4. **Clamp:** `h ← min(max(h, H_CLAMP[0]), H_CLAMP[1])`, that is, limit it to [0, 2].
   - Without the clamp, a short-memory adviser that sees one big rS next to a tiny rF can compute `h = 40`. No real hedger would do that.
   - The clamp means "never hold the hedge backwards, never hold more than twice the exposure".
5. **Score: rolling hedge effectiveness** over the last `W = SCORE_WINDOW` bars, with **equal weights** (a plain window, not exponential):
   `E = 1 − mean(rH²) / mean(rS²)` over the window, then clip to [0, 1].
   - If `mean(rS²) < 1e−16`, E is 1.0 (nothing to hedge).
   - Before W bars have been seen, use the bars so far. The warm-up makes the window full before the replay starts.
   - `mean(x²)` stands in for the variance because the mean return is about zero.
   - E = 1 is a perfect hedge. E = 0 means the hedge removes nothing, or adds risk (clipped).
6. **P&L, cumulative, in percent of the exposure:**
   - `pnl_unhedged_pct += −rS · 100`
   - `pnl_hedged_pct += −rH · 100`

   (Summing log returns is close enough for display.)

Implement `Effectiveness` with two `collections.deque(maxlen=W)` objects and running sums, so each update costs the same regardless of window size. Once the deque is full, subtract the value about to drop off before appending. Recompute the sums from scratch every 1,000 updates to stop floating-point drift.

### 6.4 How advisers differ (read this before writing any finance or adviser code)

#### Two windows that get mixed up
| | Dial half-life **H** | Score window **W** |
| --- | --- | --- |
| Belongs to | the **adviser** (its memory) | the **judge** (the yardstick) |
| Differs between advisers? | **Yes**: this is the strategy | **No**: always 96 bars |
| Used for | estimating the hedge ratio `h` | measuring how good `h` turned out to be |
| Kind | exponential decay (EWMA) | plain rolling window, equal weights |

An adviser picks its hedge with **its own memory**, and is marked against **the same window as everyone else**. If W varied, scores wouldn't be comparable and "who's best" would mean nothing.

#### The causal chain
Everything is identical between advisers except the first box:
```
dial ──▶ H = 4·2^dial ──▶ λ = 0.5^(1/H) ──▶ how much old data counts ──▶ estimated h
     ──▶ rH = rS − h_used·rF ──▶ mean(rH²) over W ──▶ score E ──▶ dissonance, and who leads
```
Same data, same formula, different memory ⇒ different `h` ⇒ different leftover wobble ⇒ different score.

#### The trade-off each dial makes
- **Short memory (small H):** forgets fast and adapts quickly when the relationship changes. But it's estimating from few bars (about `2.9·H` effective bars), so `h` **jitters** with noise.
- **Long memory (large H):** a smooth, stable `h`, but it's **stuck in the past** after a change.

That's the classic noise-versus-lag trade-off. No dial wins in every market.

How much each starting adviser still remembers from **before** a change, one trading day (96 bars) later: `λ^96 = 0.5^(96/H)`.
| Adviser | H (bars) | Weight still on pre-change data after 1 day |
| --- | --- | --- |
| Jumpy (step 0) | 4 | ~0% |
| Day trader (step 3) | 32 | 12.5% |
| Cautious (step 4) | 64 | 35% |
| Steady (step 5) | 128 | 59% |

#### Why a wrong `h` costs score
`Var(rH) = Var(S) − 2h·Cov(S,F) + h²·Var(F)`. This is smallest at `h* = Cov/Var(F)`. Any `h` either side of `h*` leaves extra wobble.

Illustrative numbers, not real data: `σS = σF = 1`, the true correlation has dropped to ρ = 0.4, so `h* = 0.4`.
| Adviser's `h` | `Var(rH) = 1 − 0.8h + h²` | `E = 1 − Var(rH)` |
| --- | --- | --- |
| 0.40 (correct) | 0.840 | 0.16 (equal to ρ², the best possible) |
| 0.45 (close) | 0.843 | 0.16 |
| 0.90 (stuck on the old ρ ≈ 1) | 1.090 | −0.09 → clipped to **0** |

An adviser still hedging as if the old relationship held does **worse than not hedging at all**.

#### What we expect across the replay
*Expected. `tools/sweep.py` (lane P3-B) MUST confirm this on the real data before +4h.*

1. **Calm (12 January to the shock):**
   - The 1.20 floor pins CHF to EUR, so S and F move almost identically: ρ ≈ 1, `h` ≈ 1.
   - Every adviser scores close to 1. Jumpy's `h` jitters a little, so it may score slightly lower.
   - **All the gaps are under `MOVE_THRESHOLD`, so nobody moves.** The dials stay apart, and the room plays four different clean chords: harmony.
2. **The shock bar (15 January, 09:30 UTC):**
   - On one or two bars, `rS` is enormous (the franc jumped by more than 10% in minutes) while `rF` is small.
   - **No hedge ratio can offset that.** For every adviser, `rH ≈ rS` on those bars.
   - Those bars dominate everyone's 96-bar score window, so **every score collapses together for one trading day** (about 12 s at the default speed). The whole room goes dissonant at once. **This is intended. Don't filter it out.**
3. **The shock poisons memory:**
   - The shock bar's huge `rS·rF` and `rF²` enter every adviser's `cov` and `var`, which pushes `h` far from its true value (hitting the clamp, in either direction).
   - A short memory flushes that out within hours. A long memory keeps it for days.
   - **This is expected to be the biggest single difference between strategies in the aftermath.** Steady keeps hedging with a poisoned `h` long after Jumpy has recovered.
4. **The aftermath (shock + 1 day, to the end):**
   - The floor is gone, the correlation is lower and unstable, and the best `h` has changed.
   - Score gaps open up beyond `MOVE_THRESHOLD`. Advisers hear the leader and move towards it, and the room converges.
   - *Which* dial leads is for the sweep to tell us. It may be Jumpy or a middle dial. Don't hard-code an expectation.

#### What the sweep MUST show (pass criteria)
`tools/sweep.py` runs each of the 7 steps **alone** through warm-up and replay, then prints a table of mean E per step for three phases:
- calm: replay start to the shock;
- storm: the shock to 96 bars after it;
- aftermath: from there to the end.

It also saves `sweep.png`: E over time for each of the 7 steps, with a line at the shock.
- **MUST (or convergence can't happen):** among `START_DIALS`, the largest gap in mean aftermath E is **≥ 2 × `MOVE_THRESHOLD`**.
- **MUST (or harmony doesn't hold):** among `START_DIALS`, the largest gap in mean calm E is **< `MOVE_THRESHOLD`**.
- **SHOULD (a better story):** the step with the best calm score isn't the step with the best aftermath score. In other words, **the leader changes**.

If a MUST fails, fix it in this order: first change `START_DIALS`, then `BAR_MINUTES`, then `SCORE_WINDOW`. **Change the convergence code only as a last resort.**

#### Reference implementation (the sweep MAY use this directly; `finance.py` MUST match it to within 1e−9)
```python
import numpy as np

def run(rS: np.ndarray, rF: np.ndarray, H: float, W: int = 96) -> np.ndarray:
    lam = 0.5 ** (1 / H)
    cov = var = 0.0
    h = 1.0
    rH = np.empty_like(rS)
    for t in range(len(rS)):
        rH[t] = rS[t] - h * rF[t]                      # 1. judged on the ratio decided BEFORE this bar
        cov = lam * cov + (1 - lam) * rS[t] * rF[t]    # 2.
        var = lam * var + (1 - lam) * rF[t] ** 2
        if var > 1e-12:                                # 3.
            h = cov / var
        h = min(max(h, 0.0), 2.0)                      # 4.
    k = np.ones(W)                                     # 5. same judge for everyone
    num = np.convolve(rH ** 2, k)[: len(rH)]
    den = np.convolve(rS ** 2, k)[: len(rS)]
    with np.errstate(divide="ignore", invalid="ignore"):
        E = np.where(den > 1e-16, 1 - num / den, 1.0)
    return np.clip(E, 0.0, 1.0)                        # score E for every bar

# sweep: for step in range(7): E = run(rS, rF, H=4 * 2**step)
```
(The full convolution truncated to `len(rH)` gives a trailing window that uses the bars so far for the first W−1 bars, which matches §6.3 step 5. The ratio of sums equals the ratio of means.)

---

## 7. Adviser behaviour

### 7.1 Starting strategies: every adviser is different
No two advisers start on the same dial. That's what makes it a search rather than a chorus. The dial is set per Mac with `--dial` (defaults from `START_DIALS`).

| Channel | Dial | Half-life | Chord | Character | Expected behaviour |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | 1 hour | A | **Jumpy**: trusts only the last hour | Slightly noisy in calm markets. Flushes the shock out of its memory fastest. |
| 1 | 3 | 8 hours | D | **Day trader**: about one session | A middle ground |
| 2 | 4 | 16 hours | E | **Cautious**: two sessions | Slow to recover after the shock |
| 3 | 5 | 32 hours | F♯m | **Steady**: trusts the old relationship | Fine before the shock. Its memory is poisoned for days after it. |

- The chords A, D, E and F♯m all belong to A major, so the piece **starts in harmony**.
- **The strategies stay different only while the advisers disagree.** Converging is the point: the piece ends in unison once every adviser is near the dial that weathers the storm best.

### 7.2 What an adviser remembers about the others
A dictionary from channel to:
```python
@dataclass
class Peer:
    dial: float
    score: float
    snr_db: float
    heard_at: float            # Heard.received_at of the last packet
```
- `on_heard(heard)` overwrites the entry for `heard.packet.channel`. It ignores its own channel. It ignores packets from a channel on the **blacklist** (until that entry expires).
- A peer is **lost** when `now − heard_at > LOST_AFTER_S`. Lost peers are ignored. They aren't deleted, so the UI can show "lost".
- ⚠️ **A peer's score is up to about 2 s old** (one packet cycle), which is about 16 bars at the default speed. That's fine and expected.

### 7.3 MVP convergence rule: step a fraction
`decide(now)` is called by the main loop. It acts at most once every `DECISION_PERIOD_S`:
```
1. If in trial and the trial isn't finished (fewer than TRIAL_BARS bars since the move): return.
2. If in trial and it's finished: evaluate it (§7.4). The trial ends either way.
3. candidates = {self} ∪ {peers not lost and not blacklisted}
   leader = the candidate with the highest score (tie → the lowest channel)
4. If leader is self: return.
5. If leader.score − own.score < MOVE_THRESHOLD: return.      # not worth moving
6. If |leader.dial − dial| ≤ SNAP_DISTANCE:  new_dial = leader.dial
   else:                                     new_dial = dial + STEP_FRACTION · (leader.dial − dial)
7. Start a trial: remember (old_dial = dial, leader channel, gap_at_move = leader.score − own.score,
   bars_at_move = bars processed so far). Set dial = new_dial and call hedger.set_half_life(4 · 2**dial).
```
At the default speed, a move can happen about every 2 s. A gap of 2 steps closes to under half a step (the same chord) in about 6 moves (12 s), and is fully snapped in about 13 moves (27 s). The aftermath lasts about 65 s, so there's time to converge.

### 7.4 Trial and revert (D12)
After `TRIAL_BARS` bars:
- If the trial's leader is now **lost**: keep the move, and the trial ends.
- Otherwise `gap_now = leader.score − own.score`, using the leader's latest heard score.
  - If `gap_now > gap_at_move + REVERT_MARGIN`, the move made things worse **relative to the leader**: set `dial = old_dial`, call `set_half_life` back, and blacklist that leader for `BLACKLIST_S`.
  - Otherwise keep the move.

**Why compare the gap, not the raw score:** when the market turns, every score drops together. A raw-score check would undo good moves every time the market turned. The gap to the leader cancels the market-wide swing.

**Known limit:** the score is a 96-bar average, so after 16 bars only about 1/6 of the window reflects the new dial. Trials are weak evidence, which is why `REVERT_MARGIN` is generous. P3 tunes `TRIAL_BARS` in the simulation.

### 7.5 Resilience (the Neptune North point)
- **No peers heard:** `decide` finds only itself as a candidate, so it never moves. The adviser keeps hedging and playing on its own. Nothing breaks.
- **One Mac switched off mid-demo:** it's marked lost after `LOST_AFTER_S`, and the others carry on with whoever they can still hear.
- **The conductor switched off:** followers carry on at the last speed (§9.4).

### 7.6 Offline simulation (`backend/sim.py`, lane P3-C)
- Creates N advisers (default 4, dials from `START_DIALS`), runs warm-up, then the replay at `SPEED_BARS_PER_S[--speed]`, keeping simulated time as `t = bars_done / speed`.
- Every 1.9 s of simulated time, each adviser's packet is delivered to the others through `VirtualRoom`, with probability `1 − loss` and a delay drawn from `delay_s`.
- Calls `decide(t)` on every adviser every `DECISION_PERIOD_S` of simulated time.
- Output:
  - `sim.png` with three panels: every adviser's dial over time, score over time, and spread over time, each with a line at the shock;
  - a printed summary: spread at the shock, spread at the end, the final step for each adviser, and the mean aftermath score with convergence and without (dials fixed).
- **Pass criteria:**
  - at `--loss 0.1`, spread at the end is **< 0.5 × spread at the shock**;
  - mean aftermath score **with convergence ≥ without**;
  - **no adviser moves during calm**.

### 7.7 After the MVP (keep the design open for these, don't build them early)
- **Full particle swarm optimisation:** velocity, inertia, a personal best and the group best. It would replace step 6 of §7.3.
- **Probabilistic jumps:** jump straight to the leader's dial with a probability that rises with the gap.
- **Lid angle as risk appetite:** the lid nudges this Mac's dial by hand. `sensors/lid.c` already prints degrees, one per line. It would map 60°–130° to a ±1.0 dial offset.

---

## 8. Music

### 8.1 Chords
**Key: A major (D10).** Each dial step is the triad built on one note of the scale. Equal temperament, A4 = 440 Hz.

| Step | Chord | Notes | Frequencies (Hz) |
| --- | --- | --- | --- |
| 0 | A | A3 C♯4 E4 | 220.00, 277.18, 329.63 |
| 1 | Bm | B3 D4 F♯4 | 246.94, 293.66, 369.99 |
| 2 | C♯m | C♯4 E4 G♯4 | 277.18, 329.63, 415.30 |
| 3 | D | D4 F♯4 A4 | 293.66, 369.99, 440.00 |
| 4 | E | E4 G♯4 B4 | 329.63, 415.30, 493.88 |
| 5 | F♯m | F♯4 A4 C♯5 | 369.99, 440.00, 554.37 |
| 6 | G♯dim | G♯4 B4 D5 | 415.30, 493.88, 587.33 |

**Timbre:** each voice is `sin(φ) + 0.3·sin(2φ) + 0.15·sin(3φ)`. The highest content is 3 × 587 = 1,762 Hz. This is in the range where MacBook speakers sound good, and far below the pilot band.

⚠️ **The synth MUST NOT produce anything above 8 kHz**: no square waves, no unfiltered noise, no clicks. Anything up there lands in the pilot band and breaks decoding. The test in §13 checks this.

### 8.2 Dissonance from the score E
Every parameter is a smooth function of E, so the sound changes gradually rather than switching.

| Layer | Rule | Gets harsh when |
| --- | --- | --- |
| **Beating** | Detune the third up and the fifth down by `d = 30 cents × (1 − E)`. The root stays in tune. | Always: e.g. 30 cents at 330 Hz beats at about 6 Hz, which sounds rough |
| **Minor second** | Add a voice at `root × 2^(1/12)`, with gain `clamp((0.7 − E) / 0.1, 0, 1) × 0.6` | E < 0.7 |
| **Tritone** | Add a voice at `root × 2^(6/12)`, with gain `clamp((0.4 − E) / 0.1, 0, 1) × 0.6` | E < 0.4 |
| **Roughness noise** | White noise passed through a one-pole low-pass at 2 kHz, gain `clamp((0.2 − E) / 0.1, 0, 1) × 0.15` | E < 0.2 |

- **Keep the loudness constant:** scale the sum by `1 / sqrt(3 + total extra-voice gain)`. Dissonance must sound *wrong*, not *louder*.
- **No zipper noise:** smooth E inside the synth with a one-pole filter, time constant 200 ms, per block.

### 8.3 Choosing the step, and changing chords
- `step` changes only when `|dial − step| > 0.6`, and then becomes `round(dial)`. This hysteresis stops the chord flickering when the dial sits near x.5. The adviser computes `step` (it's in `AdviserState`), and the synth just plays it.
- **On a step change, crossfade** from the old chord to the new one over **150 ms**: an equal-power fade, sharing the same dissonance settings.

### 8.4 Levels
- The chord is set by ear (`--chord-gain-db`, default −12 dBFS). The pilot is set by the hall test (`--pilot-gain-db`, default −18 dBFS).
- **Calibration order on the day:**
  1. Set the pilot level to the lowest that decodes at least 90% at 1 m.
  2. Set the chord level by ear.
  3. Re-check decoding with the chord playing.
- ⚠️ **Many young people can hear 14–19 kHz as a faint whine.** Keep the pilot as quiet as decoding allows.

### 8.5 Implementation notes
- Per voice, keep a running phase (float64), advanced by `2π·f/SAMPLE_RATE` each sample. Build each block with `np.arange` from a preallocated buffer.
- `set(step, score)` stores targets only. It's called from the asyncio thread while `render` runs on the audio thread. Plain attribute assignment of a float or int is atomic in CPython, so no lock is needed.
- `tools/audition.py` (P2): `python tools/audition.py [--step 3]`. It plays E sweeping from 1 down to 0 over 20 s, then holds each step at E = 1 for 2 s, then the four starting chords together. It's used to tune by ear.

---

## 9. Communication through sound

### 9.1 Pilot frequency plan (D13)
- All tones sit **exactly on FFT bins** of a 2048-point FFT at 48 kHz. Bin width is 23.4375 Hz.
- Tone `k` (0–15) of channel `c` (0–3) is on bin `PILOT_BASE_BIN + CHANNEL_BINS·c + TONE_SPACING_BINS·k`, which is `598 + 51c + 3k`.

| Channel | Tone 0 bin / Hz | Tone 15 bin / Hz |
| --- | --- | --- |
| 0 | 598 / 14,015.6 | 643 / 15,070.3 |
| 1 | 649 / 15,210.9 | 694 / 16,265.6 |
| 2 | 700 / 16,406.3 | 745 / 17,460.9 |
| 3 | 751 / 17,601.6 | 796 / 18,656.3 |

- Neighbouring tones are 3 bins (70.3 Hz) apart. Neighbouring channels have a guard of at least 6 bins between them.
- If the hall test shows the top channel is weak (MacBook speakers fall off near 19 kHz), lower `PILOT_BASE_BIN`. For example, 512 is 12.0 kHz: easier to hear for people, but more reliable.

### 9.2 Packet format
**One symbol = one tone = 4 bits (a nibble).** Every packet is exactly **10 symbols**:

| Symbol | Content |
| --- | --- |
| 0 | Sync A: always tone **15** |
| 1 | Sync B: always tone **0** |
| 2 | Type: 0 = adviser, 1 = clock (2–15 reserved, drop the packet) |
| 3 | Sequence number, 0–15 |
| 4–7 | Payload: 16 bits, most significant nibble first |
| 8–9 | CRC-8 of symbols 2–7 packed into 3 bytes `[s2<<4 \| s3, s4<<4 \| s5, s6<<4 \| s7]`, high nibble first |

| Type | Payload (16 bits) |
| --- | --- |
| Adviser | score byte `round(E·255)`, then dial byte `round(dial/6·255)` |
| Clock | bar index (12 bits, must be < 4096), then speed step (4 bits, 0–7) |

- **CRC-8:** polynomial `0x07`, initial value `0x00`, no reflection, no final XOR (CRC-8/SMBUS). **Check value:** `crc8(b"123456789") == 0xF4`. Write it in about 8 lines. No library.
- **The channel isn't in the bits.** It's the frequency band the packet arrived on.

**Timing of each symbol:** 100 ms of tone (with 5 ms raised-cosine fades in and out), then 60 ms of silence. One packet is 10 × 160 ms = **1.6 s**, then 300 ms idle. `encode` returns all of it, including the idle tail.

### 9.3 Decoding (reference algorithm; P2 MAY improve it if the tests still pass)
Analysis runs every `HOP` (10 ms) on the latest `FFT_N` samples (42.7 ms):
1. `spec = |rfft(frame · hann(2048))|²`.
2. For each channel except our own, read the 16 tone bins `e[k] = spec[bin(c, k)]`.
3. `best = argmax(e)`. The level above the floor is `snr = 10·log10(e[best] / median(e))`.
4. The hop's reading for that channel is `best` if `snr ≥ MIN_TONE_DB`, else **none**. Store `(time, reading, snr)` for each channel for the last 3 s.

**A small state machine per channel:**
- **SEARCH:**
  - Look for a run of at least 3 consecutive hops reading **15**, followed by a hop that doesn't read 15.
  - Take the **midpoint** of the run as the centre of symbol 0, `t_mid0`.
  - The midpoint is used because echoes in the hall only extend the *end* of a run, so the midpoint moves by at most half the echo length. The timing tolerance is ±28 ms.
- **COLLECT:**
  - For `k = 1..9`, the expected centre of symbol k is `t_mid0 + k × 0.160 s`.
  - Use the hop whose window centre is nearest to it. If its reading is none, the packet fails: go back to SEARCH.
- **CHECK:**
  - Symbol 1 must be 0.
  - The type must be 0 or 1.
  - The CRC must match.
  - The clock bar must be < 4096 and the speed ≤ 7.
  - If everything passes, emit `Heard`. `received_at = t_mid0 + 9 × 0.160 + 0.050` (the end of the last tone), and `snr_db` is the mean snr of the 10 symbols. Then go back to SEARCH.

**Robustness checklist:**
- Raw mic input (§4.8). No band-pass filter is needed, because only pilot bins are read.
- Ignore our own channel (we hear ourselves loudly).
- Count, per channel: packets decoded, sync found but failed, and CRC failures. Log them every 10 s and expose them through `Engine.stats()`.
- **Upgrade path, only if more than 20% of packets are lost in the hall:**
  1. Send each packet twice.
  2. Then add Hamming(7,4) error correction (a contract change).

### 9.4 Shared replay clock (`replay.py`)
**The state:** `position` (float, absolute bar index), `speed_step`, `paused`, `trim` (starts at 1.0), `last_clock_at`.

**`tick(dt)`:**
```
rate = SPEED_BARS_PER_S[speed_step] · trim   (0 if paused)
new = min(position + rate·dt, replay_end + 0.999)
bars = all bars with index in (floor(position), floor(new)], capped at 200 per tick
position = new  (or less, if capped: carry on next tick)
return Tick(bars, reset=<pending reset flag, then clear it>)
```
- `start()` unpauses at the current `speed_step`. On the conductor, start re-sends the last non-zero speed.
- `pause()` sets paused. On the conductor, it broadcasts `speed_step = 0`.
- `reset()` sets `position = replay_start` and flags a reset for the next tick.

**The conductor:**
- `packet()` returns `ClockPacket(bar=floor(position), speed_step=0 if paused else speed_step)`.
- Its status is always `conductor`. It ignores clock packets it hears.

**Followers: `on_clock(heard, now)`:**
```
p = heard.packet
est = p.bar + SPEED_BARS_PER_S[p.speed_step] · (1.54 + (now − heard.received_at))
        # 1.54 s = time from encoding the packet to the end of its last tone
speed_step = p.speed_step; paused = (p.speed_step == 0)
status = "following"; last_clock_at = now
err = est − position
if   err < −RESET_BACK_BARS:   reset(); position = replay_start; then fast-forward to est
                               # the conductor was reset
elif err > FOLLOW_JUMP_BARS:   position stays; set a catch-up target = est
                               # tick returns the skipped bars (≤ 200 per tick)
elif err < −FOLLOW_JUMP_BARS:  trim = 0 until err ≥ −1   # hold: never un-process bars
else:                          trim = 1 + clamp(err / FOLLOW_JUMP_BARS, −1, 1) · FOLLOW_TRIM
```
- **Clock lost:** if `now − last_clock_at > CLOCK_LOST_S`, the status becomes `free`, trim resets to 1.0, and the Mac **keeps the last speed**. When a clock packet arrives again, it re-locks using the same rules.
- **Startup:** a follower starts `free` and **paused** at `replay_start`. The first clock packet it hears starts it.
- **Controls on a follower:** while `following`, the follower ignores start, pause, reset and speed from its own UI (the UI shows them disabled). While `free`, it accepts them.

**Time conversions at the default speed (step 4, 8 bars per second):**
| Thing | Bars | Real time |
| --- | --- | --- |
| 1 bar | 1 | 0.125 s |
| 1 trading hour | 4 | 0.5 s |
| 1 trading day (= W) | 96 | 12 s |
| One packet cycle | about 15 | 1.9 s |
| Decision period / trial | 16 | 2 s |
| Lost timeout | 80 | 10 s |
| Whole replay | about 952 | about 119 s |
| Start to shock | about 326 | about 41 s |

Higher speeds (5–7) are for skipping through calm periods. Convergence is tuned for speed 4. At speed 7 information goes stale before it's used, so expect less convergence.

### 9.5 Chord analysis (stretch goal, after +12h: "it really is listening")
- Every 0.5 s, take an 8,192-point FFT (5.9 Hz bins) of the mic input, keep 100–2,000 Hz, and fold the energy into 12 pitch classes.
- Compare against the 7 triad templates by cosine similarity. Return `{step: similarity}`.
- **Use:** for each peer heard on pilots, show "✓ heard" in the UI if that peer's chord template scores ≥ 0.6.
- **Never used for decisions (D4).**

---

## 10. User interface

### 10.1 Layout (one page, served at `http://localhost:8000/`, or Vite at `:5173` in development)
```
┌──────────────────────────────────────────────────────────────────────────┐
│ Storm Chorus · Mac 1 (channel 1) · following conductor      ● connected  │
├──────────────────────────────┬───────────────────────────────────────────┤
│ OWN ADVISER                  │ STORM CHART                               │
│  Strategy: 8h memory         │  S and F rebased to 100 (two lines)       │
│  Dial 3.4 · step 3 · D major │  ─────────────────────────────────────    │
│  Score E  ███████░░░  0.71   │  rolling correlation ρ, −1 to 1           │
│  Hedge ratio h  0.62         │  │ shock marker (15 Jan 09:30)            │
│  P&L unhedged  −14.2%        │  ┃ replay position                        │
│  P&L hedged    −12.9%        │                                           │
│  Listening: 3 · leader Mac 2 │                                           │
│  Trial in progress           │                                           │
├──────────────────────────────┴───────────────────────────────────────────┤
│ [Start] [Pause] [Reset]   Speed ◀ 4 ▶ (8 bars/s)   12 Jan 2015 14:15 UTC │
└──────────────────────────────────────────────────────────────────────────┘
```
- Two columns from 900 px wide. Below that, one column.
- **Score colour:** green when E ≥ 0.7, amber from 0.4 to 0.7, red below 0.4. These thresholds match the dissonance layers in §8.2.
- **Chart:**
  - Only bars ≤ the current bar are shown. The `history` message has the whole replay window, so the chart slices it, and never reveals the future.
  - The chart re-renders at most 4 times a second.
- **Controls:**
  - Enabled on the conductor, or on a follower that's `free`. Disabled (with a tooltip "following the conductor") otherwise.
  - The speed control shows bars per second next to the step.
- **Connection banner:** if the WebSocket closes, show "backend not running" and retry every 1 s.

Not in v1: a list of every peer, or a debug spectrum view. Add them only if tuning needs them, after +12h.

### 10.2 WebSocket protocol (`/ws`, JSON, mirrored in `frontend/src/protocol.ts`)
```jsonc
// backend → UI, once, on connect
{ "type": "hello", "channel": 1, "conductor": false,
  "replayStart": "2015-01-12T00:00:00Z", "replayEnd": "2015-01-23T21:45:00Z",
  "shockTime": "2015-01-15T09:30:00Z",
  "speeds": [0, 1, 2, 4, 8, 16, 32, 64],
  "chords": ["A", "Bm", "C♯m", "D", "E", "F♯m", "G♯dim"] }

// backend → UI, once, on connect: the replay window, already rebased so S and F start at 100
{ "type": "history", "bars": [ { "i": 568, "time": "2015-01-12T00:00:00Z", "S": 100.0, "F": 100.0, "rho": 0.98 }, ... ] }

// backend → UI, WS_HZ times a second
{ "type": "state", "bar": 894, "time": "2015-01-15T09:45:00Z",
  "speed": 4, "paused": false, "clock": "following",          // "conductor" | "following" | "free"
  "adviser": { "channel": 1, "dial": 3.4, "step": 3, "chord": "D", "halfLifeHours": 10.6,
               "h": 0.62, "score": 0.71, "pnlUnhedgedPct": -14.2, "pnlHedgedPct": -12.9,
               "leaderChannel": 2, "heard": 3, "inTrial": true } }

// UI → backend
{ "type": "control", "action": "start" }      // or "pause" or "reset"
{ "type": "speed", "step": 5 }                // 0–7

// backend → UI, when a control is refused
{ "type": "error", "message": "following the conductor; controls disabled" }
```
- `halfLifeHours = 4 · 2^dial × BAR_MINUTES / 60`.
- The numbers in the examples are illustrative.

### 10.3 Mock
- `frontend/mock/state.jsonl` holds one `state` message per line: at least 300 lines, covering calm, the shock and convergence.
- P4 writes the first version by hand. Later, `python -m backend.sim --dump-ui-mock` MAY generate it.
- `npm run dev:mock` serves `hello` and `history` from `frontend/mock/`, then replays `state.jsonl` at 10 Hz.

---

## 11. Repository layout
```
backend/
  __init__.py
  contracts.py        shared dataclasses (frozen at +1h)                    all (§4.4 rules)
  config.py           every tunable constant                                all (§4.5 rules)
  app.py              FastAPI, /ws, main loop, options, run modes           P4
  data.py             load_bars, replay_range                               P1
  finance.py          Hedger, Effectiveness, PnL                            P1
  adviser.py          Adviser, Peer, convergence, trial and revert          P3
  sim.py              offline simulation with several advisers, plots       P3
  mocks.py            VirtualRoom (P3), VirtualAir (P2)                     P3 + P2
  replay.py           Clock                                                 P2
  audio/__init__.py
  audio/engine.py     duplex stream, callback, decoder thread               P2
  audio/modem.py      encode, Decoder, crc8                                 P2
  audio/synth.py      chords and dissonance                                 P2
  audio/chords.py     (stretch) ChordListener                               P2
  tests/              test_<module>.py, one per module                      module owner
frontend/
  src/protocol.ts     WebSocket message types (mirror of §10.2)             P4
  src/App.tsx, src/components/{StatusPanel,StormChart,Controls,Banner}.tsx  P4
  mock/               hello.json, history.json, state.jsonl                 P4
tools/
  tone_probe.py       hall test: play or listen for each channel's tones    P2
  audition.py         dissonance sweep on the speakers                      P2
  sweep.py            all 7 strategies alone through the storm              P3
scripts/prepare_data.py                                                     P1
data/chf2015.csv      committed;  data/raw/ is gitignored                    P1
sensors/lid.c         (post-MVP) lid angle reader                           P2
.github/workflows/ci.yml                                                    P4
requirements.txt                                                            all (§12.3 rule 3)
README.md             how to run, for judges and teammates                  P4
```

**Running a Mac for the demo:**
```bash
pip install -r requirements.txt
(cd frontend && npm install && npm run build)
python -m backend.app --channel 1                 # add --conductor on exactly one Mac
open http://localhost:8000
```

---

## 12. Team and agent plan
Four people (**P1–P4**, names assigned after review). Each person runs **2–3 agents in parallel** and is the human owner of everything those agents produce.

### 12.1 The three roles
| | Role | Owns (only they and their agents edit these) | Done when |
| --- | --- | --- | --- |
| **P1 + P3** | **Data and finance** (two people, one shared role) | `scripts/`, `data/`, `backend/data.py`, `finance.py`, `adviser.py`, `sim.py`, `tools/sweep.py`, `VirtualRoom` in `mocks.py` | The sweep passes §6.4. The simulation passes §7.6. The finance tests pass. |
| **P2** | **Audio and music** (the critical path) | `backend/audio/`, `replay.py`, `VirtualAir` in `mocks.py`, `tools/tone_probe.py`, `tools/audition.py`, `sensors/` | Packets decode at least 90% of the time Mac to Mac at 1 m **in the hall, with the chord playing**. Followers stay within 8 bars of the conductor. The dissonance sweep sounds like a smooth slide from "fine" to "wrong" to the team. Levels are calibrated. |
| **P4** | **UI, integration and demo** | `frontend/`, `backend/app.py`, CI, `README.md`, the demo script (§14) | Two Macs run the whole arc from the UI. `--smoke` passes in CI. The demo has been rehearsed 3 times. |

- **Finance is two people.** P1 leads the numbers (data, hedge ratio, score, P&L). P3 leads the strategies (the adviser, convergence, sweep, simulation). They review each other's pull requests.
- **Audio is one person, and it's the riskiest work.** The chord and pilot tones share one speaker, mic and audio engine, so one owner keeps them consistent.
  - **If the hall test at +2h fails or looks shaky, P3 moves to help P2** once the sweep has passed (about +6h).
  - P3 takes over the clock lane (P2-C) first.
- **P4 leads the skeleton pull request** at the start: package layout, `contracts.py`, `config.py`, `requirements.txt`, the frontend scaffold, CI, and empty modules with the §4.6 signatures that raise `NotImplementedError`. All four people agree on it before +1h.

### 12.2 Agent lanes
- **One agent = one git worktree = one branch = one slice of one person's files.**
- In Agent Wrangler: one **task** per person, one **session** per lane, with **Git worktree** ticked. Use the session checklist for the lane's progress, and the task memory for decisions in that workstream.
- **Every lane's first prompt** SHOULD be: "Read SPEC.md §0–§3 and §12, then the sections listed for your lane. Work only in the files listed. Stop and ask if the spec is unclear."

| Lane | Branch | Read | Delivers | Done when |
| --- | --- | --- | --- | --- |
| **P1-A** | `feat/data-prep` | §5 | `scripts/prepare_data.py`, `data/chf2015.csv`, `data.py` | Every check in §5.2 passes. `load_bars` returns about 1,520 bars. |
| **P1-B** | `feat/finance-core` | §6.1–6.3 | `Hedger`, `Effectiveness` | The §13 finance tests pass, and the output matches the reference `run()` to 1e−9 |
| **P1-C** | `feat/pnl-and-history` | §6.3 step 6, §10.2 | `PnL`, and a `history_payload(bars)` helper (rebased to 100, replay window only) | The tests pass. P4 can call the helper. |
| **P3-A** | `feat/adviser` | §7.1–7.5 | `Adviser`, `Peer`, `snapshot` and `restore` | The §13 adviser tests pass |
| **P3-B** | `feat/strategy-sweep` | §6.4 | `tools/sweep.py`, `sweep.png`, the printed table | The §6.4 pass criteria are checked and the result is posted in the pull request (as a table and an image). Uses the reference `run()` until P1-B lands. |
| **P3-C** | `feat/sim` | §7.6 | `VirtualRoom`, `sim.py` | The §7.6 pass criteria are met, with `sim.png` in the pull request |
| **P2-A** | `feat/modem` then `feat/audio-engine` | §9.1–9.3, §4.7 | First `tools/tone_probe.py` (by +2h), then `modem.py`, then `engine.py` and `VirtualAir` | The §13 modem tests pass. Two real Macs exchange packets. |
| **P2-B** | `feat/synth` | §8 | `synth.py`, `tools/audition.py` | The §13 synth tests pass, and the team agrees it sounds right |
| **P2-C** | `feat/clock-sync` | §9.4 | `replay.py` | The §13 clock tests pass. In loopback, the follower stays within 8 bars. |
| **P4-A** | `feat/ui` | §10 | The frontend, built against the mock | It renders the whole mock arc. `npm run build` passes. |
| **P4-B** | `feat/app-wiring` | §4.7, §4.8 | `app.py` with every run mode and option | `--loopback --smoke` exits 0. `--fake-neighbour` works on a real Mac. |
| **P4-C** | `chore/ci-and-docs` | §11, §13 | `ci.yml`, `README.md`, the demo script | CI runs pytest, the smoke test and the frontend build on every pull request |

**Later lanes for P2 (after +12h):** `feat/chord-listener` (§9.5). After the MVP: `feat/lid` (§7.7).

### 12.3 Rules for agents (also copy them into `AGENTS.md`)
1. **Stay in your lane's files.** If you need a change elsewhere, stop and tell your human. Never edit another role's files.
2. **Never edit `contracts.py` or `config.py`** except through the processes in §4.4 and §4.5.
3. **Shared files change only in small pull requests:**
   - `requirements.txt`: one pull request per new dependency, with a one-line reason;
   - `frontend/package.json`: P4 only.
4. **Claim work with GitHub issues, not by editing `AGENTS.md`.** Each issue gets an area label (`area:data`, `area:finance`, `area:adviser`, `area:audio`, `area:music`, `area:ui`) and an assignee. `AGENTS.md`'s ownership table lists **people only**.
5. **Keep pull requests small:** under about 300 lines, one purpose each, with the test that proves it. Rebase on `main` before opening one. Use the template's "How to test" section.
6. **`main` must always run.** Before merging, `pytest` and `python -m backend.app --loopback --smoke` MUST pass. CI enforces this once P4-C has landed.
7. **Use mocks, don't wait.** If code you depend on isn't merged yet, code against the contract and the §4.8 modes. Never copy another lane's unfinished work.
8. **No magic numbers.** Every constant comes from `config.py`.
9. **No `print` in `backend/`.** Use `logging`. `tools/` and `scripts/` MAY print.
10. **Type hints on every public function.** Docstrings only where the code isn't obvious.
11. **Don't add features the spec doesn't ask for.** Suggest them in the pull request description instead.
12. **When the spec is unclear,** follow §0 "Changing this document". Don't guess silently.

### 12.4 How the work depends on itself
```
 +0–1h  skeleton: contracts.py, config.py, empty modules, CI, frontend scaffold (P4 leads, all agree)
         │ frozen
 ┌───────┴───────────────────────────────────────────────────────────────────────────┐
 P1-A data ──▶ P1-B finance ──▶ P1-C P&L/history ─────────────────────────────┐
                  │ (until it lands, P3 uses the reference run())                │
 P3-B sweep ◀─────┘──▶ P3-A adviser ──▶ P3-C sim (VirtualRoom)                  │
                                                                                ▼
 P2-A tone_probe ──(+2h hall go/no-go)──▶ modem ──▶ engine + VirtualAir ──▶ loopback mode
 P2-B synth + audition ───────────────────────────────────────────────────┤
 P2-C clock ───────────────────────────────────────────────────────────────┤
 P4-A UI on mock ──▶ P4-B app wiring ──▶ P4-C CI ──────────────────────────┤
                                                                           ▼
                                +8h  single Mac with --fake-neighbour
                                +12h MVP: two Macs, sound only, full arc
```

### 12.5 Timeline and checkpoints (the event starts at 12:00)
At each checkpoint, P4 runs a 10-minute stand-up and **all four people stop**.

| Time | Clock | Checkpoint | Pass means |
| --- | --- | --- | --- |
| **+1h** | 13:00 | Skeleton frozen | The skeleton pull request is merged. CI is green on the empty modules. All 12 lanes have started. |
| **+2h** | 14:00 | **Hall go/no-go** (P2) | At 1 m, in the real hall at normal noise, `tone_probe.py` detects every channel's tones 0 and 15 at ≥ 15 dB above the channel median. **No-go** → raise the level, lower `PILOT_BASE_BIN`, move the Macs closer, and decide on a quieter demo spot. Data prepared (P1-A). |
| **+4h** | 16:00 | Pieces in isolation | The sweep passes §6.4. The modem loopback tests pass. `audition.py` plays. The UI renders the mock. |
| **+6h** | 18:00 | Adviser ready | The simulation passes §7.6. The finance tests pass. P3 is free to help P2 if needed. |
| **+8h** | 20:00 | Single Mac, end to end | `--channel 0 --conductor --fake-neighbour 3` runs the whole arc from the UI, using the real speaker and mic, and the adviser converges towards the fake neighbour when it leads. |
| **+12h** | 00:00 | **MVP** | Two Macs, sound only: calm, then the shock, then convergence. **Scope freezes:** after this, only stretch goals, tuning and polish. |
| **+18h** | 06:00 | Room | 4 Macs with the conductor clock, tuned in the hall. Stretch goals merge only if they don't break the MVP. |
| **+22h** | 10:00 | Code freeze | Only fixes after this. Rehearse the demo 3 times. Write the submission. |
| **+24h** | 12:00 | Submission | |

### 12.6 How each person works
- **Every 1–2 hours:** review your agents' pull requests, merge what passes, and restart or redirect any lane that's stuck. You're the reviewer and decision-maker. Your agents write the code.
- **Watch the Agent Wrangler board** for sessions flagged as needing you, so a blocked agent doesn't wait an hour.
- **Ask for help early** if an interface from another role blocks you. Fix the contract, don't work around it.
- **Sleep in shifts:** at least 2 people awake at all times. Never sleep with a red `main`.

---

## 13. Tests and acceptance criteria
Each module has one test file, `backend/tests/test_<module>.py`. Tests MUST run without sound hardware and finish in under 30 s in total.

| File | Test | Passes when |
| --- | --- | --- |
| `test_data.py` | Load the committed CSV | About 1,520 bars, times increasing, `replay_range` inside the data, the shock bar has `|rS| > 0.03` |
| `test_finance.py` | **Converges to the regression slope** | Synthetic data: `rF ~ N(0, 1e−3)` and `rS = 0.6·rF + N(0, 0.8e−3)` (seed 0), 3,000 bars, H = 64. The mean `h` over the last 1,000 bars is within 5% of 0.6, and the mean E is 0.36 ± 0.06 (= ρ²). |
| | **No look-ahead** | For every t, `rH[t] == rS[t] − h_after(t−1) · rF[t]` exactly |
| | **Edge cases** | `rS = rF` gives E → 1. Forcing `h = 0` gives E = 0. A huge outlier keeps h within [0, 2]. |
| | **Matches the reference** | `Hedger` + `Effectiveness` give the same output as §6.4 `run()` to 1e−9 on the real data, for steps 0, 3 and 6 |
| `test_adviser.py` | **Move** | A peer 0.1 ahead at dial 5, us at dial 0: after `decide`, dial = 1.0 and a trial has started |
| | **No move** | A peer 0.03 ahead: the dial doesn't change |
| | **Snap** | A peer at dial 3.05, us at 3.0: dial = 3.05 |
| | **Revert** | Make the gap worsen by 0.1 after 16 bars: the dial is restored and the peer is blacklisted for 10 s |
| | **Lost** | A peer silent for 11 s isn't used as leader |
| | **Alone** | No peers: the dial never changes over the whole replay |
| | **Hysteresis** | Dial 2.55 → step stays 2. Dial 2.61 → step 3. |
| `test_modem.py` | **CRC** | `crc8(b"123456789") == 0xF4` |
| | **Round trip** | Every channel, both packet types, edge values (score 0 and 1, dial 0 and 6, bar 4095, speed 7): with no noise, the decoded packet equals the original (after quantisation) |
| | **Noise** | 200 packets with white noise at 0 dB in-band SNR: ≥ 95% decoded, **0 wrong packets** |
| | **Corruption** | Flip one data symbol's tone: no `Heard` produced |
| | **Two at once** | Channels 1 and 2 transmitting together: both decoded |
| | **Self** | A decoder on channel 1 ignores channel 1 |
| | **Timing** | `received_at` is within ±30 ms of the true end of the last tone |
| `test_synth.py` | **Shape and level** | `render(480)` is float32, length 480, peak ≤ 1.0, for every step and for E in {0, 0.5, 1} |
| | **Band limit** | Over 1 s of audio at E = 0, energy above 8 kHz is at least 60 dB below the total |
| | **Smooth** | Changing the step adds no sample-to-sample jump bigger than 0.1 |
| `test_replay.py` | **Speed** | At speed 4, `tick(1.0)` returns 8 bars |
| | **Follow** | Errors of +20, −20, +3 and −200 bars give, respectively: catch-up, hold, trim > 1, reset |
| | **Lost** | 11 s with no clock packet → status `free`, the speed is kept |
| `test_app.py` | **Smoke** | `--loopback --smoke` exits 0 |
| Frontend | **Build** | `npm run build` succeeds (no frontend unit tests) |

**CI** (`.github/workflows/ci.yml`, Ubuntu):
- `pip install -r requirements.txt`, `pytest`, `python -m backend.app --loopback --smoke`, then `cd frontend && npm ci && npm run build`.
- sounddevice is imported only inside `Engine.start()`, so CI needs no PortAudio.

---

## 14. Demo script (P4 owns it. About 3 minutes.)
| Time | Say or do |
| --- | --- |
| 0:00 | "Each of these Macs is an FX hedging adviser. They're not networked. They only talk through sound." |
| 0:15 | "It's January 2015. A UK company owes Swiss francs and hedges with euros, because the franc was pinned to the euro. Each adviser has a different strategy: how much history it trusts. You hear the strategy as the chord's root, and how well it's working as how clean the chord sounds." The conductor presses **Start**. |
| 0:25–1:05 | Calm: four clean chords. Point at the storm chart. "The correlation is almost 1, so every strategy works." |
| about 1:05 | **The shock.** Everything turns harsh. "The Swiss National Bank removed the floor. The franc jumped more than 10% in minutes. No hedge could absorb that." |
| 1:20–2:00 | Point at the screens: "Listening: 3 · leader Mac 2". "They're listening to each other. Mac 2's strategy is holding up best, so the others move towards it. You can hear the roots converge." |
| 2:00–2:20 | Unison. "They've found the strategy that weathers the storm together, without a server." |
| 2:20–2:40 | **Resilience:** cover one Mac's speaker, or quit its backend. The others mark it lost and carry on. |
| 2:40 | "Open questions" slide: herding, and which strategy dimensions to add next. Then Q&A. |

Rehearse at the real speed. If the shock arrives too late, raise the speed during calm (step 5 or 6), then drop back to 4 just before 15 January.

---

## 15. Risks and fallbacks
| Risk | Signal | Fallback |
| --- | --- | --- |
| The hall is too loud for pilot tones | The +2h probe is under 15 dB | Raise the pilot level. Lower `PILOT_BASE_BIN`. Move the Macs to 0.5 m. Send each packet twice. As a last resort, demo in a quieter corner, and say in the pitch that the sound link is the hard part. |
| MacBook speakers weak near 18–19 kHz | Channel 3 fails the probe and the others pass | Lower `PILOT_BASE_BIN` so all channels move down |
| The data download or its terms are a problem | P1-A blocked | ECB daily rates (§5.1). The replay is less dramatic, but the logic still works. |
| The strategies don't differ enough | The sweep fails a MUST | Follow the fix order in §6.4 |
| Convergence looks boring | The simulation passes but sounds flat | Tune `STEP_FRACTION` and `DECISION_PERIOD_S`. Make sure the starting dials are well apart. |
| Followers drift out of sync | More than 8 bars apart in the room test | Check the 1.54 s latency constant, and the conductor's packet rate |
| The macOS mic permission is missing | No audio input, or all zeros | Grant it to the terminal app (§4.8). Check after every restart. |
| The audio callback overruns | `stats()["xruns"]` rising | Remove work from the callback. Raise `BLOCK` to 960. |
| Herding: everyone converges on one strategy | Shown in the demo | It's a known limitation. Mention it in the pitch, along with the post-MVP diversity ideas (§7.7). |

---

## 16. Open questions (owner, answer by)
| Question | Owner | By |
| --- | --- | --- |
| Do HistData's terms allow committing the prepared CSV? | P1 | +1h |
| Which Mac is the conductor, and which channel does each Mac use? | P4 | +12h |
| What do the sweep results show? Do `START_DIALS` need to change? | P3 | +4h |
| What pilot and chord levels does the hall need? | P2 | +18h |
| Are any team Macs Intel, or old enough that their speakers or mic behave differently? | All | +2h |

---

## 17. Implementation notes (audio lanes, 2026-11-14)
Written by the P2 agents' PRs (#7 clock, #8 synth, #10 modem). They record where code goes beyond or differs from the spec. Other agents SHOULD build on these. Remove a note when it's folded into the section it belongs to.

### Merge order
- All three PRs carry the skeleton commit (`backend/contracts.py`, `backend/config.py`, `requirements.txt`). Land the skeleton first; rebase the others after.
- `backend/mocks.py` holds only `VirtualAir`. P3 adds `VirtualRoom` to the same file (expect a merge there).

### Synth (`audio/synth.py`)
- **Noise filter differs from §8.2:** one 2 kHz one-pole low-pass gives only about −53 dB above 8 kHz and fails the band-limit test (§13). It's a cascade of 6 one-pole stages, normalised to unit rms before the 0.15 gain. Marked `ponytail:` in the code.
- **Constants not in `config.py`** (breaks §12.3 rule 8 until moved; P2 owns them): detune 30 cents, E smoothing 200 ms, crossfade 150 ms, headroom scale 0.3.
- `render()` does **not** apply `CHORD_GAIN_DB`. The engine does.
- `render()` returns the **same preallocated float32 buffer** every call. Copy it if you keep it.
- A `set()` step change that arrives during a crossfade is held until the fade ends.
- `tools/audition.py`: final four-chord section lasts 6 s (spec gave no length). Not played on hardware yet.

### Modem and engine (`audio/modem.py`, `audio/engine.py`, `mocks.py`)
- Decoder tries every 10 ms alignment, gated by the two sync tones and CRC-8, and takes the middle of the valid alignments as the timing.
- `Decoder.stats` is `{"packets", "crc_fail"}`. `crc_fail` also counts false sync candidates.
- `Engine(synth, on_frames, chord_gain_db, pilot_gain_db, input_device, output_device)`. `on_frames(block, t)` runs on the engine's decoder thread. The callback is exposed as `_callback`.
- `VirtualAir(snr_db=0.0, tone_amplitude=1.0, seed=0).mix(buffers) -> float32`. `snr_db` is measured inside one 1.2 kHz channel against a pure tone of `tone_amplitude`. **Loopback callers pass the pilot gain as `tone_amplitude`.**
- Measured: 0 dB SNR → 200/200 decoded, 0 wrong; −3 dB → 100/100; **−6 dB → 4/100**. Little margin in a loud hall. `received_at` error ≤ 16 ms.
- **Not tested on hardware:** `engine.py` (only a stub-synth check) and `tools/tone_probe.py` (never run). Both MUST run on a real Mac before the +2h hall go/no-go (§12.5).

### Clock (`replay.py`)
- `Clock` has no channel, so `packet()` returns `ClockPacket(channel=0, ...)`. **P4's `app.py` MUST substitute the Mac's own channel** before encoding.
- Latency correction uses `PACKET_S = 10·TONE_MS + 9·GAP_MS = 1.54 s` (the spec's 1.54 s constant).
- Bar numbers and `position` are indices into the `bars` list. `position` is the next bar to emit.
- On a reset (conductor ≥ `RESET_BACK_BARS` behind), the tick returns `reset=True` plus all bars from `REPLAY_START` to the conductor's bar, **uncapped** (the 200-bar cap applies only to catch-up).
- A follower starts on its first clock packet and doesn't need `start()`.
