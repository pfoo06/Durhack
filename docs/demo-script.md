# Demo script (about 3 minutes)

Source: SPEC §14 and §15. Rehearse at the real speed.

## Before you start
- [ ] Every Mac has a different `--channel`; press Start on any one
- [ ] Terminal has microphone permission; Mic Mode is Standard (not Voice Isolation)
- [ ] `http://localhost:8000` open on each Mac
- [ ] Macs close together (about 0.5 m if the hall is loud)

## Script
| Time | Say | Do |
| --- | --- | --- |
| 0:00 | "Each of these Macs is an FX hedging adviser. They're not networked. They only talk through sound." | |
| 0:15 | "It's January 2015. A UK company owes Swiss francs and hedges with euros, because the franc was pinned to the euro. Each adviser has a different strategy: how much history it trusts. You hear the strategy as the chord's root, and how well it's working as how clean the chord sounds." | Conductor presses **Start** |
| 0:25-1:05 | "The correlation is almost 1, so every strategy works." | Point at the storm chart. Four clean chords. |
| about 1:05 | "The Swiss National Bank removed the floor. The franc jumped more than 10% in minutes. No hedge could absorb that." | **The shock.** Everything turns harsh. |
| 1:20-2:00 | "They're listening to each other. Mac 2's strategy is holding up best, so the others move towards it. You can hear the roots converge." | Point at the screens: "Listening: 3 / leader Mac 2" |
| 2:00-2:20 | "They've found the strategy that weathers the storm together, without a server." | Unison. |
| 2:20-2:40 | "The others mark it lost and carry on." | **Resilience:** cover one Mac's speaker, or quit its backend. |
| 2:40 | Herding, and which strategy dimensions to add next. | Show the "Open questions" slide. Then Q&A. |

Timing tip: if the shock arrives too late, raise the speed during calm (step 5 or 6), then drop back to 4 just before 15 January.

## Fallbacks (SPEC §15)
| If | Then |
| --- | --- |
| Hall too loud for pilot tones | Raise the pilot level, lower `PILOT_BASE_BIN`, Macs to 0.5 m, send each packet twice. Last resort: quieter corner, and say the sound link is the hard part. |
| Channel 3 (18-19 kHz) fails, others pass | Lower `PILOT_BASE_BIN` so all channels move down |
| Followers drift out of sync (more than 8 bars) | Check the 1.54 s latency constant and the count-in |
| No audio input, or all zeros | Grant mic permission to the terminal app; check after every restart |
| Audio callback overruns (`xruns` rising) | Remove work from the callback; raise `BLOCK` to 960 |
| Convergence sounds flat | Tune `STEP_FRACTION` and `DECISION_PERIOD_S`; make sure starting dials are well apart |
| Everyone converges on one strategy (herding) | Known limitation: mention it in the pitch, with the post-MVP diversity ideas (SPEC §7.7) |
