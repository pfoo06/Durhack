import { useMemo } from "react";
import type { HistoryBar } from "../protocol";
import { C, macColor } from "../theme";
import type { Trails } from "../useStorm";

/**
 * S and F rebased to 100, rolling correlation ρ (−1 to 1), the shock marker and the replay position, then the race:
 * this Mac's hedge score E (bold, its colour) against the scores of the Macs it hears (thin, their colours).
 * Only bars up to `bar` are drawn — the chart never reveals the future (SPEC §10.1).
 */
// Every label sits in a strip ABOVE its panel, never over the lines (the franc line runs high after the crash).
const W = 440, TOP = 40, PRICE_H = 200, RHO_TOP = 274, RHO_H = 64, SC_TOP = 372, SC_H = 90, H = 488;

interface Props { history: HistoryBar[]; bar: number; shockTime: string; trails: Trails; channel: number; leading?: boolean }

export function StormChart({ history, bar, shockTime, trails, channel, leading = false }: Props) {
  const geo = useMemo(() => {
    if (history.length < 2) return null;
    const i0 = history[0].i, i1 = history[history.length - 1].i;
    let lo = Infinity, hi = -Infinity;
    for (const b of history) { lo = Math.min(lo, b.S, b.F); hi = Math.max(hi, b.S, b.F); }
    lo = Math.floor(lo - 1); hi = Math.ceil(hi + 1);
    const x = (i: number) => ((i - i0) / (i1 - i0)) * W;
    const y = (v: number) => TOP + PRICE_H - ((v - lo) / (hi - lo)) * PRICE_H;
    const yr = (r: number) => RHO_TOP + RHO_H / 2 - (Math.max(-1, Math.min(1, r)) * RHO_H) / 2;
    const shockMs = Date.parse(shockTime);
    const shock = history.find((b) => Date.parse(b.time) >= shockMs);
    const ticks: number[] = [];
    const stepT = hi - lo > 24 ? 10 : 5;
    for (let v = Math.ceil(lo / stepT) * stepT; v <= hi; v += stepT) ticks.push(v);
    const days = history.filter((b) => b.time.endsWith("T00:00:00Z"));
    return { i0, i1, x, y, yr, shockX: shock ? x(shock.i) : null, ticks, days };
  }, [history, shockTime]);

  if (!geo) return <section className="panel chart"><div className="caps">The storm</div><p className="sub">Waiting for history…</p></section>;

  const shown = history.filter((b) => b.i <= bar);
  const line = (k: "S" | "F") => shown.map((b, n) => `${n ? "L" : "M"}${geo.x(b.i).toFixed(1)} ${geo.y(b[k]).toFixed(1)}`).join("");
  const rhoLine = shown.map((b, n) => `${n ? "L" : "M"}${geo.x(b.i).toFixed(1)} ${geo.yr(b.rho).toFixed(1)}`).join("");
  const last = shown[shown.length - 1];
  const px = last ? geo.x(last.i) : 0;
  const ys = (e: number) => SC_TOP + SC_H - Math.max(0, Math.min(1, e)) * SC_H;
  const trail = (m: Map<number, number>) => [...m.entries()]
    .filter(([i]) => i >= geo.i0 && i <= Math.min(bar, geo.i1))
    .sort((p, q) => p[0] - q[0])
    .map(([i, e], n) => `${n ? "L" : "M"}${geo.x(i).toFixed(1)} ${ys(e).toFixed(1)}`).join("");
  const peerTrails = [...trails.peers.entries()].filter(([ch]) => ch !== channel).sort((p, q) => p[0] - q[0]);
  const ownNow = trails.own.get(bar);

  return (
    <section className="panel chart" aria-label="Storm chart">
      <div className="chart-head">
        <div>
          <div className="caps">The storm · rebased to 100</div>
          <h2 className="serif chart-title">Franc vs euro</h2>
        </div>
        <span className="legend">
          <span><i style={{ background: C.flareSoft }} />S franc {last ? last.S.toFixed(1) : "–"}</span>
          <span><i style={{ background: C.ice }} />F euro {last ? last.F.toFixed(1) : "–"}</span>
        </span>
      </div>
      <svg viewBox={`-30 0 ${W + 34} ${H}`} className="chart-svg" role="img" aria-label="Franc and euro prices with their rolling correlation">
        <defs>
          <filter id="cTrail" x="-10%" y="-60%" width="120%" height="220%"><feGaussianBlur stdDeviation="3" /></filter>
        </defs>
        {geo.ticks.map((v) => (
          <g key={v}>
            <line x1="0" x2={W} y1={geo.y(v)} y2={geo.y(v)} stroke="rgba(201,195,255,0.08)" />
            <text x="-6" y={geo.y(v) + 3} textAnchor="end" className="t-mono" fontSize="10" fill="rgba(201,195,255,0.6)">{v}</text>
          </g>
        ))}
        {geo.shockX !== null && (
          <g>
            <line x1={geo.shockX} x2={geo.shockX} y1={6} y2={SC_TOP + SC_H} stroke={C.flareSoft} strokeDasharray="2 3" opacity="0.75" />
            <text x={geo.shockX + 6} y={16} className="t-serif" fontSize="15" fill="#ffd3dc">the cap breaks</text>
            <text x={geo.shockX + 6} y={29} className="t-mono" fontSize="9" fill="rgba(255,211,220,0.7)">15 JAN · 09:30</text>
          </g>
        )}
        <path d={line("F")} fill="none" stroke={C.ice} strokeWidth="4" opacity="0.3" filter="url(#cTrail)" />
        <path d={line("S")} fill="none" stroke="#ff8fa6" strokeWidth="5" opacity="0.4" filter="url(#cTrail)" />
        <path d={line("F")} fill="none" stroke={C.ice} strokeWidth="1.5" strokeLinejoin="round" />
        <path d={line("S")} fill="none" stroke="#ffd3dc" strokeWidth="1.8" strokeLinejoin="round" />

        <rect x="0" y={RHO_TOP} width={W} height={RHO_H} rx="6" fill="rgba(0,0,0,0.2)" />
        <line x1="0" x2={W} y1={geo.yr(0)} y2={geo.yr(0)} stroke="rgba(201,195,255,0.15)" strokeDasharray="1 4" />
        <text x="-6" y={geo.yr(1) + 6} textAnchor="end" className="t-mono" fontSize="8" fill="rgba(201,195,255,0.5)">1</text>
        <text x="-6" y={geo.yr(0) + 3} textAnchor="end" className="t-mono" fontSize="8" fill="rgba(201,195,255,0.5)">0</text>
        <text x="-6" y={geo.yr(-1)} textAnchor="end" className="t-mono" fontSize="8" fill="rgba(201,195,255,0.5)">−1</text>
        <path d={rhoLine} fill="none" stroke={C.ice} strokeWidth="1.3" opacity="0.9" />
        <text x="0" y={RHO_TOP - 7} className="t-caps" fontSize="8" fill="rgba(168,236,255,0.65)">CORRELATION ρ</text>

        <rect x="0" y={SC_TOP} width={W} height={SC_H} rx="6" fill="rgba(0,0,0,0.2)" />
        <text x="-6" y={ys(1) + 6} textAnchor="end" className="t-mono" fontSize="8" fill="rgba(201,195,255,0.5)">1</text>
        <text x="-6" y={ys(0)} textAnchor="end" className="t-mono" fontSize="8" fill="rgba(201,195,255,0.5)">0</text>
        <text x="0" y={SC_TOP - 7} className="t-caps" fontSize="8" fill="rgba(243,227,195,0.7)">HEDGE SCORE E · THE RACE</text>
        {leading && ownNow !== undefined && (
          <text x={W} y={SC_TOP - 7} textAnchor="end" className="t-caps" fontSize="9" fill={macColor(channel)}>★ THIS MAC IS LEADING</text>
        )}
        {peerTrails.map(([ch, m]) => (
          <path key={ch} d={trail(m)} fill="none" stroke={macColor(ch)} strokeWidth="1.3" opacity="0.6" strokeDasharray="3 2" />
        ))}
        {leading && (
          <path className="lead-glow" d={trail(trails.own)} fill="none" stroke={macColor(channel)} strokeWidth="9" strokeLinejoin="round" filter="url(#cTrail)" />
        )}
        <path d={trail(trails.own)} fill="none" stroke={macColor(channel)} strokeWidth={leading ? 3.4 : 2.6} strokeLinejoin="round" />
        {ownNow !== undefined && (
          <circle cx={geo.x(Math.min(bar, geo.i1))} cy={ys(ownNow)} r={leading ? 5 : 3.5} fill={macColor(channel)}
            style={leading ? { filter: `drop-shadow(0 0 6px ${macColor(channel)})` } : undefined} />
        )}

        {last && (
          <g>
            <line x1={px} x2={px} y1={6} y2={SC_TOP + SC_H} stroke="rgba(255,255,255,0.45)" />
            <circle cx={px} cy={geo.y(last.S)} r="9" fill="#ff8fa6" opacity="0.35" filter="url(#cTrail)" />
            <circle cx={px} cy={geo.y(last.S)} r="3.5" fill="#ffffff" />
            <circle cx={px} cy={geo.y(last.F)} r="2.4" fill={C.ice} />
          </g>
        )}
        {geo.days.filter((_, k) => k % 2 === 0).map((b) => (
          <text key={b.i} x={geo.x(b.i)} y={H - 4} textAnchor="middle" className="t-mono" fontSize="9" fill="rgba(201,195,255,0.55)">
            {new Date(b.time).getUTCDate()} Jan
          </text>
        ))}
      </svg>
      <div className="chart-foot mono">
        ρ {last ? last.rho.toFixed(2) : "–"}
        <span className="legend">
          <span><i style={{ background: macColor(channel) }} />Mac {channel} (this one)</span>
          {peerTrails.map(([ch]) => <span key={ch}><i style={{ background: macColor(ch) }} />Mac {ch}</span>)}
        </span>
      </div>
    </section>
  );
}
