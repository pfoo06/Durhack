# Storm Chorus UI (lane P4-A)

React 18 + Vite + TypeScript. One page per Mac; it only draws what its own backend sends over `/ws` (SPEC §10).

```bash
cd frontend
npm install
npm run dev:mock            # mock backend on ws://localhost:8000/ws + Vite on http://localhost:5173 (acts as the conductor)
npm run dev:mock:follower   # same, but acting as a follower: controls are disabled
npm run dev                 # Vite only, against a real backend on :8000
npm run build               # type-check and build to frontend/dist (served by the backend at /)
npm run mock:generate       # regenerate mock/hello.json, history.json, state.jsonl
```

- `src/protocol.ts` mirrors SPEC §10.2. Change both together.
- Add `?debug` to the URL for a slider that previews any score on the visuals (display only).
- Add `?ws=ws://host:port/ws` to point at another backend.
- The mock data is synthetic, shaped like the 15 Jan 2015 shock. It is not the real HistData series.
