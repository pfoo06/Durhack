# Team roles and how to start

Who does what, and how to get up to speed fast. The full detail is in [SPEC.md](SPEC.md) (§12 has the lanes). Roles can move; change this file in a PR if they do.

## Who is on what

| Person | Role | Lanes (SPEC §12.2) | Status |
| --- | --- | --- | --- |
| **Erinna** | P1 finance and data | P1-A data prep, P1-B finance core (PR #13), P1-C `PnL` and `history_payload` | Finance core merged (#13). Data (#16) and `PnL` + history in review. |
| **Peter** | P2 audio and music | Modem, engine, synth, clock | Done and merged. |
| **Xin Jie** | P4 frontend and integration | P4-A UI, P4-B `app.py` wiring | UI merged (#20). `app.py` in review. |
| **Keya** | P3 strategy | P3-A `Adviser`, P3-B strategy sweep, P3-C `VirtualRoom` and `sim.py` | Free. Nothing started. |

**P4-B** (`app.py`) is Xin Jie's. **P4-C** (CI, README, demo script) landed in #17.

## Critical path
1. Data (P1-A) feeds the sweep, the adviser and the simulation.
2. The `Adviser` (P3-A) is what makes the piece converge. Nothing sounds right without it.
3. `app.py` (P4-B) joins everything. Nothing runs end to end without it.
4. CI (P4-C) doesn't exist yet, so nothing checks that `main` still runs.

## Use agents to learn your role first
Don't start coding cold. Spend the first 15 minutes making an agent explain your role to you. Then have it build in small pieces you review.

1. **Open one agent session per lane**, in its own git worktree and branch (SPEC §12.2).
2. **First prompt**, filling in your lane:
   > Read SPEC.md §0–§3 and §12, then the sections for lane `<your lane>`. Explain in plain words what this lane builds, what it depends on, and what it hands to other people. Then list the files I will own and the tests that mean I'm done. Don't write code yet.
3. **Check it back.** Ask the agent: "What would break for the rest of the team if my part is wrong?" and "What can I fake with a mock so I don't wait for others?"
4. **Then build** in small PRs (under about 300 lines, one purpose, one test that proves it). Review each agent PR yourself before merging. You are the reviewer; the agent writes the code.
5. **When the spec is unclear,** make the agent write it under "Spec gap" in the PR description. Don't guess silently (SPEC §0).

### Reading list per role
| Role | Read first | Then |
| --- | --- | --- |
| P1 (Erinna) | §5 data, §6 finance | §4.4–4.6, §13 |
| P2 (Peter) | §8, §9 | §4.4–4.8, §13, and §17 for what's already built |
| P3 (Keya) | §6.4, §7 | §6, §4.4–4.8, §13 |
| P4 (Xin Jie, and `app.py`) | §10, §4 | §14, §13 |

## Rules that bite
- Stay in your lane's files. Need a change elsewhere? Tell that person.
- Don't edit `backend/contracts.py` or `backend/config.py` except through the processes in SPEC §4.4 and §4.5.
- Every constant lives in `config.py`. No `print` in `backend/`.
- Before merging: `python -m pytest backend` must pass. Squash-merge, delete the branch.
