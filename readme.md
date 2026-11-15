Shared hackathon project: Peter Foo, Erinna Anthony, Xin Jie, Keya

Stack: Python backend (FastAPI, numpy) and a React + Vite frontend.

## What it is
Storm Chorus: four MacBooks each play an FX hedging adviser replaying the day the Swiss central bank removed the euro-franc floor (15 January 2015). Each adviser protects the same currency position but starts with a different strategy. Each Mac plays a chord: the root shows its strategy, and how dissonant it sounds shows how well that strategy is working. The Macs are not networked and communicate only through sound, listening through the microphone and moving towards the best-performing adviser. The room starts in harmony, turns dissonant in the storm, then converges into unison.

## Run the tests
```bash
pip install -r requirements.txt
python -m pytest backend
```

## Run modes
Command: `python -m backend.app [options]` from the repo root (full option list: SPEC §4.8).

| Mode | How to run | Exists yet? |
| --- | --- | --- |
| Offline simulation | `python -m backend.sim` | No |
| Strategy sweep | `python tools/sweep.py` | Yes |
| Software loopback | `python -m backend.app --loopback [--smoke]` | Yes |
| Single Mac | `python -m backend.app --channel 0 --fake-neighbour 3` | Yes, not yet tried on a real Mac |
| Room | `python -m backend.app --channel N` on each Mac | Yes, not yet tried on real Macs |
| UI mock | `npm run dev:mock` in `frontend/` | Yes |

## Run the demo on several Macs
Every Mac runs the same command with a **different `--channel`**. The channel sets the Mac's identity, its pilot-tone frequency band, and its starting strategy. Exactly **one** Mac adds `--conductor`, which sends the shared replay clock.

| Channel | Starting strategy (dial) | Memory (half-life) | Command |
| --- | --- | --- | --- |
| 0 | 0 | 2 h (reacts fastest) | `python -m backend.app --channel 0 --conductor` |
| 1 | 3 | 16 h | `python -m backend.app --channel 1` |
| 2 | 4 | 32 h | `python -m backend.app --channel 2` |
| 3 | 5 | 64 h (slowest) | `python -m backend.app --channel 3` |

- Two Macs: use channels 0 and 1. Three: 0, 1, 2.
- Two Macs on the **same channel** would have the same strategy and talk over each other on the same band.
- `--dial 2.5` overrides the starting strategy (0.0–6.0).
- `--storm demo` keeps the real calm and crash but **simulates the aftermath**, tuned so the strategies split clearly and then all converge on the fast one inside the replay. Every Mac must use the same `--storm`. The page looks the same as with real data, so say in the pitch that the aftermath is simulated.
- Each Mac prints its channel, starting dial and half-life when audio starts. Open `http://localhost:8000` on each Mac to see its page. The page needs the built frontend first: `cd frontend && npm install && npm run build` (on laptops where Santa blocks esbuild, copy `frontend/dist` from a teammate).
- Start the followers first, then the conductor, and press Start on the conductor's page. Followers lock to its clock.
- `python -m backend.app --help` lists every option.

## Docs
- [SPEC.md](SPEC.md): the single source of truth.
- [TEAM.md](TEAM.md): roles, lanes and how to start.
- [docs/demo-script.md](docs/demo-script.md): the 3-minute demo rehearsal checklist.
