Shared hackathon project: Peter Foo, Erinna Anthony, Xin Jie, Keya

Stack will most likely be C# .NET and React, with a Python backend.

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
| Strategy sweep | `python tools/sweep.py` | No |
| Software loopback | `python -m backend.app --loopback [--smoke]` | Yes (stand-in adviser until P3-A) |
| Single Mac | `python -m backend.app --channel 0 --conductor --fake-neighbour 3` | Yes, not yet tried on a real Mac |
| Room | `python -m backend.app --channel N [--conductor]` on each Mac | Yes, not yet tried on real Macs |
| UI mock | `npm run dev:mock` in `frontend/` | Yes |

## Docs
- [SPEC.md](SPEC.md): the single source of truth.
- [TEAM.md](TEAM.md): roles, lanes and how to start.
- [docs/demo-script.md](docs/demo-script.md): the 3-minute demo rehearsal checklist.
