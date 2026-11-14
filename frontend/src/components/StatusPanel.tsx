import type { AdviserView } from "../protocol";
import {
  C, CLASH_BELOW, NOISE_BELOW, PHASES, TRITONE_BELOW, chordQuality, fmtHours, fmtPct, mix, type Phase,
} from "../theme";

/** Own adviser (SPEC §10.1): strategy, dial/step/chord, score, h, P&L, who we hear, the leader, trial. */
export function StatusPanel({ a, phase }: { a: AdviserView; phase: Phase }) {
  const E = a.score, pct = Math.round(E * 100);
  const [line1, line2] =
    phase === 2 ? ["The hedge is holding again.", "The room is converging."]
    : E >= CLASH_BELOW ? [`Your hedge is cancelling ${pct}%`, "of the franc’s swings."]
    : E >= TRITONE_BELOW ? [`The hedge is slipping — only ${pct}%`, "of the swings are cancelled."]
    : ["The hedge has broken. The franc", "and the euro have split apart."];
  const leads = a.leaderChannel === a.channel;
  const line3 = leads && phase !== 0 ? "You’re doing best — the others are listening."
    : a.inTrial ? `Trying CH ${a.leaderChannel}’s strategy…`
    : phase !== 0 && !leads ? `Listening to CH ${a.leaderChannel} — it’s coping better.` : "";
  const P = PHASES[phase];
  const marker = mix(C.flareSoft, C.ice, E);
  const bar = (v: number) => {
    const w = Math.min(50, Math.abs(v) * 2.5);
    return { left: `${v >= 0 ? 50 : 50 - w}%`, width: `${Math.max(0.5, w)}%` };
  };

  return (
    <section className="panel status" aria-label="This Mac's adviser">
      <div className="caps">This Mac · channel {a.channel}</div>
      <h1 className="serif strategy">{fmtHours(a.halfLifeHours)} h memory</h1>
      <div className="sub">
        Dial <span className="mono">{a.dial.toFixed(1)}</span> · step <span className="mono">{a.step}</span> · {a.chord} {chordQuality(a.chord)}
      </div>

      <div className="caps gap-top">How the hedge is holding</div>
      <div className="serif phase" style={{ color: P.color }}>{P.word}</div>
      <p className="sentence">{line1}<br />{line2}</p>
      <p className="serif hint" style={{ color: leads ? C.gold : "rgba(243,227,195,0.7)" }}>{line3}</p>

      <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(E.toFixed(2))} aria-label="Hedge score E">
        <div className="meter-ticks">
          {[[NOISE_BELOW, "noise"], [TRITONE_BELOW, "tritone"], [CLASH_BELOW, "clash"]].map(([v, l]) => (
            <span key={l} className={E < (v as number) ? "tick on" : "tick"} style={{ left: `${(v as number) * 100}%` }}>{l}</span>
          ))}
        </div>
        <div className="meter-track">
          <div className="meter-dot" style={{ left: `${E * 100}%`, boxShadow: `0 0 14px 4px ${marker}` }} />
        </div>
        <div className="meter-ends"><span className="storm">Storm</span><span className="mono">E {E.toFixed(2)}</span><span className="calm">Calm</span></div>
      </div>

      <div className="caps gap-top">The ledger · % of exposure</div>
      <div className="ledger">
        <div className="row"><span>Without a hedge</span><span className="mono pink">{fmtPct(a.pnlUnhedgedPct)}</span></div>
        <div className="pbar"><i style={{ ...bar(a.pnlUnhedgedPct), background: C.flareSoft }} /></div>
        <div className="row"><span>With this hedge</span><span className="mono">{fmtPct(a.pnlHedgedPct)}</span></div>
        <div className="pbar"><i style={{ ...bar(a.pnlHedgedPct), background: C.lavender }} /></div>
        <div className="row"><span>Hedge ratio h</span><span className="mono">{a.h.toFixed(2)}</span></div>
        <div className="caps tiny">Euros held for every franc owed</div>
      </div>

      <div className="caps gap-top">The room</div>
      <div className="room-lines">
        <div>Listening: <span className="mono">{a.heard}</span> other Mac{a.heard === 1 ? "" : "s"}</div>
        <div style={{ color: leads ? C.gold : undefined }}>{leads ? "Leader: this Mac" : `Leader: CH ${a.leaderChannel}`}</div>
        <div className="serif" style={{ color: a.inTrial ? C.gold : "rgba(201,195,255,0.55)" }}>
          {a.inTrial ? "Trial in progress" : "No trial running"}
        </div>
      </div>
    </section>
  );
}
