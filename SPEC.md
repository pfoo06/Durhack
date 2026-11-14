# Storm Chorus: technical spec

> Status: draft v1, 2026-11-14. Built from the team Q&A. Work isn't assigned yet (team of 4). See [Workstreams](#10-workstreams).

## 1. What we're building
Several Macs act as independent FX hedging advisers, all replaying the **same historical storm**: the Swiss franc in January 2015.
- Each adviser hedges a franc exposure using euros, with its own **reaction speed**.
- Each adviser plays a chord. The **root note** is its reaction speed, and **how dissonant it sounds** shows how well its hedge is working.
- The Macs communicate **only through sound**. Each one decodes the others' status from the microphone, then moves its reaction speed towards whoever is doing best.
- The room goes from harmony (calm), to dissonance (storm), to unison (they've converged on a better strategy).

Targets: the DurHack theme "Composition", SGX FX (market storm), and Marshall Wace (New Worlds). Stretch goal: Neptune North (independent actors that keep working when communication fails).

## 2. Architecture
```
┌───────────────────────── one Mac (all Macs are the same) ─────────────────────────┐
│                                                                                   │
│  React UI (browser, localhost) ◀── WebSocket (state at ~10 Hz) ──▶ Python backend │
│   - own adviser status                     controls (speed, start)  - replay clock│
│   - storm chart                                                     - finance     │
│                                                                     - adviser     │
│                                                                     - audio I/O ──┼──▶ speaker: chord + pilot tones
│                                                                                ◀──┼─── microphone: other Macs
└───────────────────────────────────────────────────────────────────────────────────┘
        no network between Macs. Sound is the only link.
```

- **Each Mac runs its own backend and its own UI.** Nothing is shared over the network.
- **Python owns all audio input and output** (`sounddevice` plus `numpy`). That keeps all the timing-critical work in one process, uses numpy for the signal processing, and avoids browsers slowing down background tabs.
- **React only displays and controls.** It makes no sound.

### Stack
| Part | Choice |
| --- | --- |
| Backend | Python 3.11+, FastAPI + uvicorn (WebSocket), numpy, pandas, scipy, sounddevice |
| Frontend | React + Vite, one charting library (e.g. Recharts) |
| Data prep | A one-off pandas script that writes a small CSV the backend loads at startup |

### Components and data flow
```
                       ┌──────────── backend (one Python process) ─────────────────────────┐
 data/chf2015.csv ──▶  │ data.load_bars ──▶ replay.Clock ──bar──▶ adviser.Adviser          │
                       │                       ▲   ▲               │  uses finance.*    │
                       │       ClockPacket ────┘   │               │                    │
                       │                     speed (UI)            ▼ AdviserState       │
                       │                                   app (state hub) ──▶ WebSocket ──▶ React
                       │                                      │       ▲                   │
                       │            AdviserPacket / ClockPacket│       │ Heard[]          │
                       │                                      ▼       │                   │
                       │  audio.engine ◀── synth.Synth (chord)   modem.Decoder ◀── mic    │
                       │      │      ◀── modem.encode (pilot)         ▲                   │
                       │      └──▶ speaker                    mic frames (queue)          │
                       └────────────────────────────────────────────────────────────────────┘
```

### Contracts (`backend/contracts.py`)
These dataclasses are the **only** things that cross between workstreams. They're **frozen at +1h**. After that, changing one needs a pull request approved by the owner of every workstream that uses it.

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class Bar:            # one replay step, produced by data / replay
    i: int            # bar index from the start of the data file
    time: datetime
    S: float          # GBP value of 1 CHF
    F: float          # GBP value of 1 EUR
    rS: float         # log return of S
    rF: float         # log return of F
    rho: float        # rolling correlation of rS, rF (96 bars), for the chart

@dataclass
class AdviserState:   # produced by adviser, read by app, synth and UI
    channel: int
    dial: float       # continuous, 0.0–6.0
    step: int         # round(dial), 0–6, the chord
    half_life_bars: float
    h: float          # current hedge ratio
    score: float      # rolling effectiveness E, 0–1
    pnl_hedged: float
    pnl_unhedged: float

@dataclass(frozen=True)
class AdviserPacket:  # what goes over the air about an adviser
    channel: int; seq: int; score: float; dial: float

@dataclass(frozen=True)
class ClockPacket:    # what the conductor sends
    channel: int; seq: int; bar: int; speed_step: int

@dataclass(frozen=True)
class Heard:          # what the decoder reports
    packet: AdviserPacket | ClockPacket
    snr_db: float
    received_at: float  # time.monotonic() when the packet ENDED
```

### Module interfaces
| Module | Interface | Owner |
| --- | --- | --- |
| `data.py` | `load_bars(path) -> list[Bar]` | P1 |
| `finance.py` | `Hedger(half_life_bars).update(bar) -> (h_prev, r_hedged)`, `set_half_life(bars)`; `Effectiveness(window=96).update(rS, rH) -> float` | P1 |
| `adviser.py` | `Adviser(channel, start_dial)`: `on_bar(bar) -> AdviserState`, `on_heard(heard: Heard)`, `decide(now) -> None`, `packet() -> AdviserPacket` | P1 |
| `audio/modem.py` | `encode(packet) -> np.ndarray[float32]` (48 kHz mono); `Decoder(own_channel).feed(frames) -> list[Heard]` | P2 |
| `audio/engine.py` | `Engine(synth, on_frames)`: a full-duplex `sounddevice` stream. `send(samples)` queues pilot audio. Mic frames go to `on_frames` **outside** the audio callback. | P2 |
| `replay.py` | `Clock(bars, conductor: bool)`: `tick(dt) -> list[Bar]` (the bars passed since the last tick), `set_speed(step)`, `on_clock(heard)`, `status -> "conductor" \| "following" \| "free"`, `packet() -> ClockPacket` | P2 |
| `audio/synth.py` | `Synth()`: `set(step: int, score: float)`, `render(n) -> np.ndarray[float32]`. It must be real-time safe: no allocation-heavy work and no locks inside `render`. | P3 |
| `audio/chords.py` | (stretch goal) `ChordListener().feed(frames) -> int \| None` (the chord step heard) | P3 |
| `app.py` | FastAPI app, `/ws`, the main loop and the wiring. **Only P4 edits this file.** | P4 |
| `mocks.py` | `VirtualRoom(loss=0.1, delay_s=1.5)`, see below | P1 + P2 |

### Threads and timing
- **Audio callback** (sounddevice, about every 10 ms): `out = synth.render(n) + next pilot samples`. It copies the mic frames into a queue and returns. **No FFTs and no I/O in the callback.**
- **Decoder thread:** drains the mic queue, runs `Decoder.feed` and `ChordListener.feed`, and posts each `Heard` to the asyncio loop with `loop.call_soon_threadsafe`.
- **The asyncio main loop** (`app.py`) runs at 20 Hz:
  1. `clock.tick(dt)`, then `adviser.on_bar(bar)` for every new bar;
  2. `synth.set(state.step, state.score)`;
  3. `adviser.decide(now)` every 2 seconds;
  4. when nothing is being sent, `engine.send(modem.encode(adviser.packet()))`, alternating with `clock.packet()` on the conductor;
  5. the WebSocket broadcast, at 10 Hz.
- **Latency correction:** a `Heard` carries the time the packet *ended*, so the clock adds the packet's length when it re-locks.

### Run modes (so everyone can work without the others' code)
| Mode | Flag | What's real | What's faked | Who needs it |
| --- | --- | --- | --- | --- |
| **Offline simulation** | `python -m backend.sim --advisers 4 --loss 0.1` | finance, adviser, clock | the air, via `VirtualRoom` (packets with loss and delay, no audio) | P1 tuning convergence |
| **Software loopback** | `--loopback` | everything, including modem encode and decode | the speaker and mic: samples are mixed with noise in memory | P2, and continuous integration |
| **Single Mac** | `--channel N` | everything | other Macs: `--echo` replays this Mac's own packets on another channel as a fake neighbour | P3, P4 |
| **Room** | `--channel N [--conductor]` | everything | nothing | final integration |
| **UI mock** | `npm run dev:mock` | the UI | the backend (a mock WebSocket replaying `frontend/mock/state.jsonl`) | P4, from hour 1 |

## 3. Data
- **Source:** HistData.com free 1-minute bars for **EUR/CHF, EUR/GBP and GBP/CHF**, December 2014 to January 2015. The files are downloaded by hand from their site. **Check their terms before committing the raw files**; if unsure, commit only the prepared output, or just the script.
- **Fallback:** European Central Bank daily reference rates (free CSV). These are daily only, so the storm is less dramatic.
- **Preparation** (`scripts/prepare_data.py`):
  - Align the three series on timestamp and drop gaps.
  - Resample to a configurable bar size (default **15 minutes**, about 1,300 bars for 2–23 January 2015).
  - Write `data/chf2015.csv`.
- **The position (seen from a UK company):**
  - **Exposure S** = the GBP value of a CHF receivable = 1 / (GBP/CHF).
  - **Proxy F** = the GBP value of EUR = EUR/GBP.
  - While the euro-franc cap held, S and F moved almost together. On 15 January 2015 that link broke.
- **Returns:** log returns per bar, `r = ln(p_t / p_{t-1})`. **All correlation and variance maths uses returns, never prices.**

## 4. Finance engine (one per adviser)
### The strategy dial: reaction speed
- The dial is a **half-life H in bars**: how quickly the adviser forgets old data. Its EWMA decay factor is `λ = 0.5^(1/H)`.
- The dial runs from **H = 4 bars** (1 hour, reacts fast) to **H = 256 bars** (about 2.7 days, steady), on a **log scale** split into **7 steps**. It moves continuously, but for the music it's rounded to the nearest step.

### At every bar t
1. Update the exponentially weighted estimates:
   - `cov_SF ← λ·cov_SF + (1−λ)·r_S·r_F`
   - `var_F ← λ·var_F + (1−λ)·r_F²`
2. **Hedge ratio:** `h_t = cov_SF / var_F`. This is the minimum-variance ratio, ρ·σ_S/σ_F.
3. **Hedged return:** `r_H = r_S − h_{t−1}·r_F`.
   - ⚠️ **Use the *previous* bar's ratio.** Using `h_t` would let the adviser see the future.
4. **Score: rolling hedge effectiveness** over a fixed window of **W = 96 bars** (1 day), the same window for every adviser:
   - `E = 1 − var(r_H) / var(r_S)`, clipped to [0, 1].
   - 1 means a perfect hedge. 0 means the hedge isn't helping, or is making things worse.
   - W is deliberately **separate from the dial**, so all the advisers are judged by the same yardstick.
5. Also track cumulative unhedged and hedged P&L, for the UI.

Warm-up: run the first 2 days of data silently, before the replay starts, so the estimates have settled.

## 5. Adviser behaviour
### Starting positions
Configurable per Mac (`--dial <step>`). Defaults for 4 Macs: steps **0, 3, 4, 5**. In A major those are the A, D, E and F♯m chords, which sound fine together.

### MVP convergence rule: step a fraction
Every **decision period** (about 2 seconds, or after each round of heard advisers):
1. **Who's the leader?** The best score among this Mac and every adviser heard within the last **6 seconds**.
2. If the leader isn't this Mac, and the leader's score is better than this Mac's by at least **0.05**:
   - Move the dial: `dial ← dial + 0.2·(leader_dial − dial)`.
3. **Trial and revert:** keep a note of the dial before the move. If, after **K = 16 bars**, this Mac's score is worse than before by more than 0.05, move back and ignore that leader for 10 seconds.
4. **If no other adviser can be heard:** keep the current dial and carry on alone. That's resilience.

### After the MVP (keep the design open for these)
- **Full particle swarm optimisation:** velocity, inertia, each adviser's own best and the group's best.
- **Probabilistic jumps:** jump straight to the leader's dial with a probability that rises with the score gap.
- **Lid angle as risk appetite:** the lid nudges this Mac's dial by hand. The reader already exists at `sensors/lid.c`.

## 6. Music
- **Key: A major.** Dial steps 0–6 map to the chords built on each note of the scale: **A, Bm, C♯m, D, E, F♯m, G♯dim**.
  - Because every chord stays in the key, advisers moving between strategies still sound musical.
  - (The original idea had each Mac on a major chord, such as A major and B major. Staying in one key avoids clashes when the market is calm.)
- **Register:** 3-note chords voiced in **200–1,500 Hz**, which is where MacBook speakers sound good.
- **Dissonance from the score E.** It increases smoothly, so the change is gradual:
  - **Beating:** detune the upper voices by up to **±30 cents × (1 − E)**. This is the "physics of dissonance" point from the pitch.
  - **Clashing notes:**
    - below E = 0.7: add a note a semitone above the root;
    - below E = 0.4: also add a tritone;
    - below E = 0.2: add filtered noise (roughness).
- **Transitions:** when the rounded root changes, move the chord in a 150-millisecond step rather than a smooth glide.
- **Volume:** the chord sits well below the pilot tones. Each Mac has a calibration setting for its own level.

## 7. Communication through sound
### 7a. Pilot tones (the data channel, MVP)
- **Frequency plan:** 4 channels between **14.0 and 18.8 kHz**, each **1.2 kHz** wide. Each Mac has its own channel (`--channel 0–3`), and ignores its own.
- **Modulation:** 16-tone frequency-shift keying (16-FSK) within a channel, tones **75 Hz apart**. Each symbol carries 4 bits.
- **Symbol timing:** **100 ms** of tone plus a **20 ms** gap, with smooth (raised-cosine) edges so there are no clicks.
- **Decoding:**
  - FFT size **2048 at 48 kHz** (23.4 Hz per bin), with a Hann window.
  - In each symbol, pick the strongest of the 16 tone bins.
  - It counts as a valid tone only if it's at least **10 dB above that channel's noise floor**, which is measured as the median energy across the channel.
- **Packet (about 48 bits, about 1.5 seconds):**
  | Field | Bits |
  | --- | --- |
  | Start marker: a fixed 2-symbol pattern | 8 |
  | Packet type (adviser or clock) | 2 |
  | Sequence number | 4 |
  | Adviser: score E, scaled 0–63 | 6 |
  | Adviser: dial, scaled 0–63 | 6 |
  | Clock only: bar number | 12 |
  | Clock only: speed step | 4 |
  | Error check (CRC-8) | 8 |
  - Packets that fail the CRC are dropped.
  - Upgrade path: add error correction (Hamming(7,4)) if too many packets are lost in the hall.
- **Robustness:**
  - Turn off every automatic audio process on the microphone (echo cancellation, noise suppression, auto volume). They wreck tones.
  - Band-pass the input to 13.5–19.3 kHz before decoding.
  - Each heard adviser's state includes its last packet, how strong its signal was, and its age. After 6 seconds with no packet it's marked **lost** and isn't used.
  - Log decode statistics (packets heard, CRC failures) to help with tuning.
- **⚠️ Many young people can hear 14–19 kHz as a faint whine.** Keep the level as low as decoding allows, and set it on the day.

### 7b. Chord analysis (stretch goal: "it really is listening")
- Analyse the mic input in **100–2,000 Hz** to see which notes are present, then match that against the 7 chords in the key.
- Use it to **cross-check**: a pilot packet says an adviser is on dial step 3, so the room should contain a D chord. Show "✓ heard" when the audio confirms it.
- **It's never used for decisions.** In unison every Mac plays the same chord, so chords alone can't tell the advisers apart.

### 7c. Shared replay clock
- **One Mac is the conductor** (`--conductor`). It sends a clock packet about once every 3 seconds, carrying the bar number and the speed step.
- **The other Macs follow it:**
  - If they're more than **8 bars** out, they jump to the heard bar number, corrected for the packet's length.
  - Otherwise they adjust speed by up to ±10% until they catch up.
- **If the clock is lost,** a Mac keeps going at the last speed it heard. When the clock returns, it re-locks.
- **Speed:** 8 steps from 0 (paused) to about 40 bars per second. The default lets the storm part of the replay take about **90 seconds**. Only the conductor's UI shows the speed control.

## 8. User interface (each Mac)
1. **Own adviser status:**
   - this Mac's name or channel, and whether it's the conductor;
   - the dial, shown as the half-life in hours, plus its step and chord name (e.g. "D major");
   - the score E as a meter, and the current hedge ratio h;
   - unhedged versus hedged P&L;
   - the clock status: "following conductor", "free-running", or "conductor".
2. **Storm chart:**
   - S and F, rebased to 100 at the start of the replay;
   - the rolling correlation underneath;
   - a marker for the replay position, and a fixed marker at **15 January 2015, 09:30 UTC**.
3. **Controls:** start, pause, reset, and (on the conductor only) the speed control.

Not in v1: a list of the other advisers, or a debug spectrum view. Add one if it's needed for tuning.

### Backend ↔ frontend messages (WebSocket `/ws`, JSON)
```jsonc
// backend → UI, about 10 times a second
{ "type": "state", "bar": 812, "time": "2015-01-15T09:45:00Z", "speed": 4,
  "clock": "following",                       // "conductor" | "following" | "free"
  "series": { "S": 101.2, "F": 99.7, "rho": 0.31 },
  "adviser": { "channel": 1, "dial": 3.4, "step": 3, "halfLifeHours": 8.0,
               "chord": "D", "h": 0.62, "score": 0.44, "pnlHedged": -0.8, "pnlUnhedged": -11.9 } }
// backend → UI, once when connecting: the whole chart history
{ "type": "history", "bars": [{ "time": "...", "S": 100, "F": 100, "rho": 0.97 }, ...] }
// UI → backend
{ "type": "control", "action": "start" | "pause" | "reset" }
{ "type": "speed", "step": 0-7 }              // conductor only
```

## 9. Repository layout
```
backend/
  contracts.py      shared dataclasses (frozen at +1h)                      all
  app.py            FastAPI app, WebSocket, main loop, run modes            P4
  mocks.py          VirtualRoom, echo neighbour                              P1+P2
  data.py           load_bars                                                P1
  finance.py        EWMA hedge ratio, hedged returns, rolling effectiveness  P1
  adviser.py        dial, convergence rule, trial and revert                 P1
  sim.py            offline simulation with several advisers and plots       P1
  replay.py         clock: bars, speed, following the conductor             P2
  audio/engine.py   full-duplex audio stream, decoder thread                 P2
  audio/modem.py    pilot-tone packets: encode, decode, CRC                  P2
  audio/synth.py    chord and dissonance synthesis                           P3
  audio/chords.py   (stretch goal) chord analysis                            P3
  tests/            one test file per module                                 module owner
frontend/           Vite + React, mock/state.jsonl                           P4
tools/tone_probe.py hall test: play or detect one tone                       P2
tools/audition.py   play the dissonance sweep on the speakers                P3
scripts/prepare_data.py                                                      P1
data/chf2015.csv                                                             P1
sensors/lid.c       (after the MVP) lid angle reader, prints degrees         P3
.github/workflows/  CI: pytest, loopback smoke test, frontend build          P4
```

Run one Mac with `python -m backend.app --channel 1 [--conductor] [--dial 3]`, and run the UI with `npm run dev` in `frontend/`.

## 10. Team and agent plan
Four people (**P1–P4**, names assigned after review). Each person runs **2–3 agents in parallel** and is the human owner of everything those agents produce.

### 10a. The four roles
| | Role | Owns (only they and their agents edit these) | Done when |
| --- | --- | --- | --- |
| **P1** | **Data and finance** | `scripts/`, `data/`, `backend/data.py`, `finance.py`, `adviser.py`, `sim.py` | In the offline simulation, the 4 advisers' dials converge after 15 January and the average score goes up |
| **P2** | **Audio link** (the critical path) | `backend/audio/modem.py`, `audio/engine.py`, `replay.py`, `tools/tone_probe.py` | Packets from one Mac decode on another 1 m away **in the hall** at least 90% of the time, and followers stay within 8 bars of the conductor |
| **P3** | **Music** | `backend/audio/synth.py`, `audio/chords.py`, `tools/audition.py`, `sensors/` | Dissonance from E = 1 to 0 sounds like a smooth slide from "fine" to "wrong" to the team, the pilot tones stay audible to the decoder underneath the chord, and the volume is calibrated |
| **P4** | **UI, integration and demo** | `frontend/`, `backend/app.py`, `backend/mocks.py` (shared with P1/P2), CI, `README.md`, the demo script | Two Macs run the whole arc started from the UI, and the demo is rehearsed 3 times |

P2 has the riskiest work. **If the hall test at +2h fails or looks shaky, P1 moves to help P2** once the finance work is stable (around +8h).

### 10b. Agent lanes for each person
**One agent = one git worktree = one branch = one slice of that person's folders.** Agent Wrangler: one **task** per person, one **session** per lane, with **Git worktree** ticked. Use the session checklist to track the lane's progress, and the task memory for decisions in that workstream.

| Person | Lane A | Lane B | Lane C |
| --- | --- | --- | --- |
| **P1** | `feat/data-prep`: download, align and resample the data; write `data/chf2015.csv`, with a check that 15 January is present | `feat/finance-core`: `Hedger`, `Effectiveness`, and the finance tests in §12 | `feat/adviser-sim`: `Adviser`, `VirtualRoom`, `sim.py`, and a plot of dials and scores over time for tuning |
| **P2** | `feat/modem`: `encode`, `Decoder`, CRC, the noise test | `feat/audio-engine`: the duplex stream, the mic settings, the decoder thread; `tone_probe.py` for the hall test | `feat/clock-sync`: `Clock`, following the conductor, the loopback test with two clocks |
| **P3** | `feat/synth`: chords, dissonance mapping, smooth transitions; `audition.py` (sweep E from 1 to 0 on the speakers) | `feat/chord-listener` (stretch goal, start after +8h) | `feat/lid` (post-MVP): connect `sensors/lid.c` to the dial nudge |
| **P4** | `feat/ui`: the status panel and storm chart, built against mock state | `feat/app-wiring`: `app.py`, the WebSocket, run modes, `--echo` | `chore/ci-and-docs`: a GitHub Action (pytest plus frontend build), `README.md` run steps, the demo script |

### 10c. Rules for agents (also add these to `AGENTS.md`)
1. **Stay in your lane's files.** If you need a change somewhere else, stop and tell your human. Don't edit another workstream's folders.
2. **Never edit `contracts.py`** after +1h, unless your human has an approved contract pull request.
3. **Shared files are append-only, in small pull requests:**
   - `requirements.txt`: one pull request per new dependency, with a one-line reason;
   - `frontend/package.json`: P4 only.
4. **Claim work with GitHub issues, not by editing `AGENTS.md`.** Twelve agents editing one table guarantees merge conflicts. Each issue gets an area label (`area:finance`, `area:audio`, `area:music`, `area:ui`) and an assignee. `AGENTS.md`'s ownership table lists **people only**.
5. **Keep pull requests small:** under about 300 lines, one purpose each, with the test that proves it. Rebase on `main` before opening one.
6. **`main` must always run.** Before merging, `pytest` and `python -m backend.app --loopback --smoke` (runs 200 bars, then exits 0) must pass. CI enforces this once lane P4-C has landed.
7. **Use mocks, don't wait.** If code you depend on isn't merged yet, code against the contract and the mock modes in §2. Never copy another lane's work in progress.

### 10d. How the work depends on itself
```
 +0–1h   contracts.py + repo skeleton (P4 leads, all 4 people agree)  ──┐
                                                                         │ frozen
 ┌───────────────┬─────────────────┬──────────────────┬───────────────────┘
 P1 data ─▶ finance ─▶ adviser+sim      P2 tone_probe ─▶ modem ─▶ engine ─▶ clock
 │                         │               │ (hall test +2h: go / no-go)   │
 │                         ▼               ▼                               ▼
 │                     VirtualRoom ◀──── shared mock ────▶ loopback mode
 P3 synth + audition ──────────────────────────────┐
 P4 UI on mock ──▶ app wiring ──▶ CI ──────────────┤
                                                   ▼
                       +8h first integration: single Mac with --echo
                       +12h MVP: two Macs, sound only, full arc
```

### 10e. Integration checkpoints
P4 runs each one, and **all four people stop for 10 minutes**:
| Time | Checkpoint | Pass means |
| --- | --- | --- |
| **+1h** | Contracts frozen | `contracts.py` merged, the skeleton runs, every agent lane is started |
| **+2h** | Hall go/no-go (P2) | `tone_probe.py` detects a 16 kHz tone at 1 m in the real hall at normal busyness. If it fails: raise the level, move the Macs closer, add error correction, and decide whether the demo needs a quieter spot. |
| **+4h** | Pieces in isolation | The offline simulation converges, the modem loopback passes, `audition.py` plays the dissonance sweep, and the UI renders mock state |
| **+8h** | Single Mac, end to end | `--channel 0 --echo` runs the whole arc from the UI, with the real speaker and mic |
| **+12h** | **MVP** | Two Macs, sound only, calm → storm → convergence. **Freeze scope:** after this, only stretch goals and polish. |
| **+18h** | Room | 4 Macs, conductor clock, tuned in the hall. Stretch goals (chord listener, lid) merge only if they don't break the MVP. |
| **+22h** | Code freeze | Rehearse the demo three times and write the submission. Only fixes after this. |

### 10f. Daily rhythm for each person
- **Every 1–2 hours:** review your agents' pull requests, merge what passes, and restart or redirect any lane that's stuck. You're the reviewer and decision-maker, and your agents write the code.
- **Watch the Agent Wrangler board** for sessions flagged as needing you, so a blocked agent doesn't wait an hour.
- **Ask for help early** if a lane is blocked by another workstream's interface. Fix the contract, don't work around it.
- **Sleep in shifts** (at least 2 people awake), and never sleep with a red `main`.


## 11. Milestones (24 hours from 12:00)
| By | Milestone |
| --- | --- |
| **+2h** | Repo set up, data prepared. **Hall test:** a 16 kHz tone played on one Mac is detected on another at 1 m (pass/fail decides how far to push sound-only communication). |
| **+8h** | Each workstream works on its own: the offline convergence simulation, two-Mac modem tests, the chord synth, and the UI running on mock state. |
| **+12h** | **MVP:** two Macs, sound-only, full arc (calm → storm → convergence). |
| **+18h** | 4 Macs, conductor clock, tuning in the real hall. Start the stretch goals: chord analysis, lid. |
| **+22h** | Code freeze. Rehearse the demo three times. Write the submission. |

## 12. Tests (one small runnable check for each risky part)
- **Finance:** with a constant correlation in synthetic data, `h` converges to the regression slope (within 5%), and `E` comes out close to ρ².
- **Modem:** encode, add white noise at 0 dB SNR within the band, decode, and check that at least 95% of packets survive. Also check a CRC failure is detected when a symbol is flipped.
- **Convergence:** with 4 advisers on the real data and perfect communication, the spread of dials shrinks after 15 January.

## 13. Risks and fallbacks
| Risk | Fallback |
| --- | --- |
| The hall is too loud for pilot tones | Move the Macs closer, raise the level, add error correction. If all else fails, demo in a quieter corner, and say clearly in the pitch that the sound link is the hard part. |
| The data download or terms are a problem | European Central Bank daily rates |
| Convergence looks boring | Tune the step fraction and decision period. Choose starting dials so the leader changes at least once. |
| macOS microphone permission | Grant the terminal app microphone access before the demo, and test after every restart. |
| Advisers all converge on one strategy (herding) | It's a known limitation: mention it in the pitch, and mention the post-MVP diversity options. |
