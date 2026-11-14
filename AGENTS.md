# Shared agent context

Every agent working in this repo (Claude Code, Codex, Gemini, Cursor, ...) reads this file.
Read it before starting work and update it when you change something others need to know.
Keep it short: facts, decisions, and who's working on what. Not a diary.

## Project
Durhack hackathon project. Team: Peter Foo, Erinna Anthony, Xin Jie.
- Idea: _TBD_
- Stack: _TBD_
- Run: `python -m backend.app --channel N [--conductor]`, then open http://localhost:8000 (build the UI first). No sound hardware: `python -m backend.app --loopback [--smoke]`. Spec: SPEC.md.
- `backend/app.py` uses a stand-in adviser that never moves until `backend/adviser.py` (P3-A) lands; it switches automatically.
- Test: `python -m pytest backend` (25 pass: modem, synth, replay).
- UI: `cd frontend && npm install && npm run dev:mock` (mock backend + Vite on :5173). Build: `npm run build`. See `frontend/README.md`.

## Who's working on what
Claim an area before starting so agents don't collide. Remove the line when it's done.

| Person / agent | Working on | Files / area |
| --- | --- | --- |
| | | |

## Decisions
Newest first. One line each: what was decided and why.

- 

## Workflow
`main` is protected: no direct pushes, no force pushes, no deleting it. Everything goes through a PR.

1. Pick or open a GitHub issue. Keep it small: a few hours of work at most.
2. Branch off the latest `main`: `feat/<short-name>`, `fix/<short-name>` or `chore/<short-name>`.
3. Commit small and often. Messages say what changed: `Add login form`, not `stuff`.
4. Open a PR using the template and link the issue (`Closes #12`).
5. Ask a teammate to review. The ruleset requires 0 approvals (you can merge your own PR once CI is green), but review anything touching another person's area. Resolve every review comment. A new push dismisses old approvals.
6. Squash-merge, delete the branch, pull `main`.

Agents: never push to `main`, never force-push, and never approve your own team's PR on a human's behalf.

## Conventions
- Rebase your branch on `main` instead of letting it drift.
- Don't rewrite another person's area without checking with them first.
- Put secrets in `.env` (git-ignored) and never commit them.

## Gotchas
Things that wasted time and shouldn't waste it twice.

- 
