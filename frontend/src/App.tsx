import { useState } from "react";
import { Banner } from "./components/Banner";
import { Controls } from "./components/Controls";
import { Orb } from "./components/Orb";
import { Sky } from "./components/Sky";
import { StatusPanel } from "./components/StatusPanel";
import { StormChart } from "./components/StormChart";
import { CLASH_BELOW, type Phase } from "./theme";
import { backendUrl, useStorm, useThrottled } from "./useStorm";

const CHART_MS = 250; // ≤ 4 chart renders per second (SPEC §10.1)
const debug = new URLSearchParams(location.search).has("debug");

export default function App() {
  const { conn, hello, history, state, error, send } = useStorm(backendUrl());
  const [preview, setPreview] = useState<number | null>(null);
  const chartBar = useThrottled(state?.bar ?? -1, CHART_MS);

  const a = state?.adviser;
  const score = preview ?? a?.score ?? 1;
  const afterShock = !!(state && hello && Date.parse(state.time) >= Date.parse(hello.shockTime));
  const phase: Phase = !afterShock ? 0 : score < CLASH_BELOW ? 1 : 2;
  const warmth = phase === 2 ? 1 : 0;
  const clockText = state?.clock === "free" ? "running" : "waiting for count-in";

  return (
    <div className="app">
      <Sky score={score} warmth={warmth} />
      <Banner conn={conn} />

      <header className="top">
        <div>
          <span className="caps brand">Storm Chorus</span>
          <span className="caps dim"> · Mac {hello?.channel ?? "?"} (channel {hello?.channel ?? "?"}) · {clockText}</span>
        </div>
        <div className={`conn conn-${conn}`}><i />{conn === "open" ? "connected" : "disconnected"}</div>
      </header>

      <main className="grid">
        {a ? <StatusPanel a={preview === null ? a : { ...a, score }} phase={phase} /> : <section className="panel status"><p className="sub">Waiting for the backend…</p></section>}
        <div className="stage">
          {a && hello && (
            <Orb score={score} step={a.step} chords={hello.chords} dial={a.dial} warmth={warmth}
              channel={a.channel} leaderChannel={a.leaderChannel} heard={a.heard} />
          )}
        </div>
        <aside className="side">
          {hello && <StormChart history={history} bar={chartBar} shockTime={hello.shockTime} />}
          {debug && (
            <label className="panel debug">
              <span className="caps">Preview score (debug only)</span>
              <input type="range" min={0} max={100} value={Math.round(score * 100)} onChange={(e) => setPreview(Number(e.target.value) / 100)} />
              <button className="link" onClick={() => setPreview(null)}>use live score</button>
            </label>
          )}
        </aside>
      </main>

      <Controls paused={state?.paused ?? true} speed={state?.speed ?? 0} speeds={hello?.speeds ?? []}
        modem={state?.modem ?? "pilot"} time={state?.time ?? ""} error={error} send={send} />
    </div>
  );
}
