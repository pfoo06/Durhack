import { useEffect, useRef, useState } from "react";
import type { PeerView } from "../protocol";
import {
  C, CHORD_NOTES, CLASH_BELOW, SPARKLE, TRITONE_BELOW,
  chordQuality, chordShort, clamp01, clashNote, macColor, mix, prefersReducedMotion, tritoneNote,
} from "../theme";

/**
 * The centrepiece: an arch, a glowing orb (the chord) and one star per note on its own orbit.
 * Everything is driven by the score E (smoothed here) so dissonance is visible:
 *   as the hedge fails the orbits swell and pull apart, the note stars grow and drift away from each other,
 *   the orb wobbles and turns pink; E<0.7 adds a clash star, E<0.4 a tritone star. As it recovers everything
 *   settles back. Warmth (0–1) turns everything gold when the room converges.
 */
interface Props {
  score: number;
  step: number;
  chords: string[];
  dial: number;
  warmth: number;
  channel: number;
  peers: PeerView[]; // the other Macs it hears, drawn as beads on the dial
  color: string; // this Mac's colour
  leaderChannel: number;
  heard: number;
}

const CX = 300, CY = 330, R = 120;
const SPREAD_FROM = 0.85; // above this score the orbits sit in their calm shape
const ARCH_CY = 250, DIAL_R = 222;
const ORB = [
  { rx: 200, ry: 50, rot: -16, w: 0.42, grow: 1.45, fan: -14 },
  { rx: 240, ry: 75, rot: 13, w: 0.31, grow: 1.3, fan: 10 },
  { rx: 172, ry: 38, rot: 36, w: 0.56, grow: 1.6, fan: 18 },
  { rx: 262, ry: 102, rot: -52, w: 0.74, grow: 1.2, fan: -8 },
  { rx: 150, ry: 120, rot: 72, w: 0.93, grow: 1.5, fan: 12 },
];
// Where each channel's star sits around the arch (the own channel's slot stays empty).
const SLOTS: [number, number][] = [[44, 40], [556, 40], [548, 596], [52, 596]];

function blob(cx: number, cy: number, r: number, e: number, t: number, seed: number, lobe: number): string {
  const n = 72, amp = (1 - e) * r * 0.17, br = 1 + 0.035 * Math.sin(t * 1.5708 + seed);
  const la = 0.6 + 0.25 * Math.sin(t * 0.3);
  let d = "";
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2;
    let rr = r * br + amp * (0.55 * Math.sin(3 * a + t * 0.9 + seed) + 0.3 * Math.sin(5 * a - t * 1.3 + seed * 2) + 0.15 * Math.sin(8 * a + t * 2.2));
    if (lobe > 0) { const c = Math.cos(a - la); if (c > 0) rr += lobe * r * 0.4 * c * c * c; }
    d += `${i ? "L" : "M"}${(cx + rr * Math.cos(a)).toFixed(1)} ${(cy + rr * Math.sin(a)).toFixed(1)}`;
  }
  return d + "Z";
}

function moon(k: number): string {
  const r = 7, p = (k + 1) / 7, rx = Math.abs(1 - 2 * p) * r, sweep = p < 0.5 ? 0 : 1;
  return `M0 ${-r} A${r} ${r} 0 0 1 0 ${r} A${rx.toFixed(2)} ${r} 0 0 ${sweep} 0 ${-r}Z`;
}

export function Orb({ score, step, chords, dial, warmth, channel, leaderChannel, heard, peers, color }: Props) {
  const sim = useRef({ t: 0, e: score, w: warmth, phi: [0, 2.1, 4.2, 1, 3], beat: [0, 0, 0, 0, 0], step, prevStep: step, changeAt: -10 });
  const [, setFrame] = useState(0);
  const target = useRef({ score, step, warmth });
  target.current = { score, step, warmth };
  const reduce = useRef(prefersReducedMotion());

  useEffect(() => {
    let raf = 0, last = performance.now();
    const loop = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      const s = sim.current;
      s.t += dt;
      s.e += (target.current.score - s.e) * (1 - Math.exp(-dt * 5));
      s.w += (target.current.warmth - s.w) * (1 - Math.exp(-dt * 0.7));
      const det = 30 * (1 - s.e);
      for (let i = 0; i < 5; i++) {
        s.beat[i] += dt * (0.4 + det * 0.16) * (1 + i * 0.35);
        const drift = i === 0 ? 0 : (i % 2 ? 1 : -1) * (det / 30) * 1.1;
        s.phi[i] += dt * ORB[i].w * (1 + drift);
      }
      if (target.current.step !== s.step) { s.prevStep = s.step; s.step = target.current.step; s.changeAt = s.t; }
      setFrame((f) => (f + 1) % 1e6);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const s = sim.current, t = s.t, E = s.e, det = 30 * (1 - E), red = reduce.current, w = s.w;
  const lobe = clamp01((CLASH_BELOW - E) / CLASH_BELOW);
  // 0 when calm, 1 when the hedge has fully broken: drives how far the orbits swell and the notes spread.
  const spread = clamp01((SPREAD_FROM - E) / SPREAD_FROM);
  const clashVis = clamp01((CLASH_BELOW - E) / 0.12), triVis = clamp01((TRITONE_BELOW - E) / 0.1);
  const lav = mix(C.lavender, C.moon, w), ice = mix(C.ice, C.moon, w), halo = mix(C.periwinkle, C.gold, w);
  const flash = Math.max(0, 1 - (t - s.changeAt) / 0.45);
  const ct = clamp01((t - s.changeAt) / 0.4);
  const cur = s.step, notes = CHORD_NOTES[cur] ?? CHORD_NOTES[0];
  const labels = [notes[0], notes[1], notes[2], `${clashNote(cur)} · clash`, `${tritoneNote(cur)} · tritone`];
  const name = chordShort(chords[cur] ?? "?"), prevName = chordShort(chords[s.prevStep] ?? "");
  const fs = (n: string) => (n.length > 2 ? 150 : 190);

  const orbits = ORB.map((o, i) => {
    const vis = i < 3 ? 1 : i === 3 ? clashVis : triVis;
    const grow = 1 + spread * (o.grow - 1); // each orbit swells by a different amount, so they separate
    const rot = o.rot + spread * o.fan * (red ? 0.5 : 1) + (-10 - o.rot) * w;
    const rx = o.rx * grow * (1 + (det / 30) * 0.05 * Math.sin(s.beat[i]));
    const ry = o.ry * grow * (1 + spread * 0.25) * (1 + (det / 30) * 0.08 * Math.cos(s.beat[i] * 1.3));
    const al = (rot * Math.PI) / 180, ph = s.phi[i];
    const x = CX + rx * Math.cos(ph) * Math.cos(al) - ry * Math.sin(ph) * Math.sin(al);
    const y = CY + rx * Math.cos(ph) * Math.sin(al) + ry * Math.sin(ph) * Math.cos(al);
    const front = Math.sin(ph) > 0;
    return { i, vis, rot, rx, ry, x, y, front, size: (front ? 11 : 8) * (1 + spread * 0.7) * (1 + flash * 0.9) * (i < 3 ? 1 : 0.85), color: i < 3 ? "#ffffff" : C.flare };
  });

  // The room: the leader (if not us) glows gold; other heard Macs are anonymous (the backend only sends a count).
  const others = [0, 1, 2, 3].filter((c) => c !== channel);
  const leaderIsOther = leaderChannel !== channel && others.includes(leaderChannel);
  let anon = Math.max(0, heard - (leaderIsOther ? 1 : 0));
  const room = others.map((c, k) => {
    const [x, y] = SLOTS[c];
    const lead = c === leaderChannel;
    const on = lead || anon-- > 0;
    const age = (t + k * 0.5) % 1.6;
    return { c, x, y, lead, on, age };
  });

  const bth = Math.PI + (dial * Math.PI) / 6;
  const beadX = CX + DIAL_R * Math.cos(bth), beadY = ARCH_CY + DIAL_R * Math.sin(bth);

  return (
    <svg className="orb" viewBox="0 -40 600 740" role="img"
      aria-label={`Playing ${chords[cur]} ${chordQuality(chords[cur] ?? "")}, hedge score ${E.toFixed(2)}`}>
      <defs>
        <filter id="oBlurXL" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="36" /></filter>
        <filter id="oBlurL" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="16" /></filter>
        <filter id="oBlurM" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="7" /></filter>
        <filter id="oTextGlow" x="-30%" y="-30%" width="160%" height="160%">
          <feGaussianBlur stdDeviation="10" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
        <radialGradient id="oCore" cx="50%" cy="46%" r="55%">
          <stop offset="0%" stopColor="#ffffff" /><stop offset="38%" stopColor={lav} /><stop offset="100%" stopColor={lav} stopOpacity="0.15" />
        </radialGradient>
        <radialGradient id="oHalo"><stop offset="0%" stopColor={ice} stopOpacity="0.9" /><stop offset="100%" stopColor={halo} stopOpacity="0" /></radialGradient>
        <radialGradient id="oPink" r="55%"><stop offset="0%" stopColor={C.flare} /><stop offset="100%" stopColor={C.flare} stopOpacity="0" /></radialGradient>
        <path id="oCapArc" d="M 90 712 Q 300 742 510 712" />
      </defs>

      {/* the room */}
      {room.map((m) => (
        <g key={m.c} opacity={m.on ? 1 : 0.28}>
          {m.on && (
            <>
              <circle cx={m.x} cy={m.y} r={m.age * 55} fill="none" stroke={m.lead ? C.gold : lav} strokeWidth="1" opacity={Math.max(0, 1 - m.age / 1.6) * 0.5} />
              <circle cx={m.x} cy={m.y} r={12} fill={m.lead ? C.gold : "#dfe3ff"} opacity={m.lead ? 0.85 : 0.45} filter="url(#oBlurM)" />
            </>
          )}
          <path d={SPARKLE} transform={`translate(${m.x} ${m.y}) scale(${m.lead ? 11 : 7})`} fill={m.lead ? C.gold : "#dfe3ff"} />
          <text x={m.x} y={m.y + 30} textAnchor="middle" className="t-mono" fontSize="11" fill={m.lead ? C.gold : "rgba(243,227,195,0.8)"}>
            {m.lead ? `CH ${m.c}` : m.on ? "heard" : "silent"}
          </text>
          {m.lead && <text x={m.x} y={m.y + 44} textAnchor="middle" className="t-caps" fontSize="9" fill={C.gold}>DOING BEST</text>}
        </g>
      ))}

      {/* arch */}
      <path d={`M 110 610 V ${ARCH_CY} A 190 190 0 0 1 490 ${ARCH_CY} V 610`} fill="none" stroke={lav} strokeWidth="1" opacity="0.3" />
      <path d={`M 122 610 V ${ARCH_CY} A 178 178 0 0 1 478 ${ARCH_CY} V 610`} fill="none" stroke={lav} strokeWidth="0.6" opacity="0.12" />
      <line x1="70" y1="610" x2="530" y2="610" stroke={lav} strokeWidth="0.6" opacity="0.22" />

      {/* dial (display only: the UI can't move it, SPEC §10.2) */}
      <path d={`M ${CX - DIAL_R} ${ARCH_CY} A ${DIAL_R} ${DIAL_R} 0 0 1 ${CX + DIAL_R} ${ARCH_CY}`} fill="none" stroke={lav} strokeWidth="1" opacity="0.16" />
      {dial > 0.01 && <path d={`M ${CX - DIAL_R} ${ARCH_CY} A ${DIAL_R} ${DIAL_R} 0 0 1 ${beadX.toFixed(1)} ${beadY.toFixed(1)}`} fill="none" stroke={lav} strokeWidth="1.4" opacity="0.65" />}
      <text x={CX - DIAL_R - 20} y={ARCH_CY + 46} textAnchor="middle" className="t-caps" fontSize="8" fill="rgba(201,195,255,0.55)">FAST</text>
      <text x={CX + DIAL_R + 20} y={ARCH_CY + 46} textAnchor="middle" className="t-caps" fontSize="8" fill="rgba(201,195,255,0.55)">STEADY</text>
      {chords.map((c, k) => {
        const th = Math.PI + (k * Math.PI) / 6, active = k === cur;
        const x = CX + DIAL_R * Math.cos(th), y = ARCH_CY + DIAL_R * Math.sin(th);
        const lx = CX + (DIAL_R + 32) * Math.cos(th), ly = ARCH_CY + (DIAL_R + 32) * Math.sin(th) + (k === 0 || k === 6 ? 5 : 0);
        return (
          <g key={c}>
            <g transform={`translate(${x.toFixed(1)} ${y.toFixed(1)})`} opacity={active ? 1 : 0.55}>
              <circle r="7.5" fill="rgba(5,6,15,0.85)" stroke={active ? C.moon : lav} strokeWidth="0.8" />
              <path d={moon(k)} fill={active ? C.moon : lav} />
            </g>
            <text x={lx} y={ly} textAnchor="middle" className="t-serif" fontSize={active ? 22 : 14} fill={C.moon} opacity={active ? 1 : 0.45}>{chordShort(c)}</text>
            {active && <text x={lx} y={ly + 15} textAnchor="middle" className="t-mono" fontSize="10" fill="rgba(201,195,255,0.85)">{2 ** k} H</text>}
          </g>
        );
      })}
      {/* the other Macs' strategies on the same dial: convergence is their beads sliding onto ours */}
      {peers.filter((p) => p.channel !== channel).map((p) => {
        const th = Math.PI + (p.dial * Math.PI) / 6, lead = p.channel === leaderChannel;
        const x = CX + DIAL_R * Math.cos(th), y = ARCH_CY + DIAL_R * Math.sin(th);
        return (
          <g key={p.channel}>
            {lead && <circle cx={x} cy={y} r="13" fill="none" stroke={C.gold} strokeWidth="1.6" />}
            <circle cx={x} cy={y} r="7" fill={macColor(p.channel)} opacity="0.9" />
            <text x={x} y={y - 16} textAnchor="middle" className="t-mono" fontSize="10" fill={macColor(p.channel)}>{p.channel}</text>
          </g>
        );
      })}
      <circle cx={beadX} cy={beadY} r="16" fill={color} opacity="0.5" filter="url(#oBlurM)" />
      <circle cx={beadX} cy={beadY} r="6" fill={color} stroke="#ffffff" strokeWidth="1.5" />

      {/* the orb */}
      <g>
        <path d={blob(CX, CY, R * 1.5, E, t * 0.8, 1.3, lobe * 0.6)} fill="url(#oHalo)" opacity="0.55" filter="url(#oBlurXL)" />
        <path d={blob(CX, CY, R, E, t, 0, lobe)} fill="url(#oPink)" opacity={0.15 + 0.5 * spread} filter="url(#oBlurL)" style={{ mixBlendMode: "screen" }} />
        <path d={blob(CX, CY, R, E, t, 0, lobe)} fill="url(#oCore)" opacity="0.92" filter="url(#oBlurL)" style={{ mixBlendMode: "screen" }} />
        <circle cx={CX} cy={CY} r={R * 0.42 * (1 + 0.05 * Math.sin(t * 1.5708))} fill="#ffffff" opacity={0.35 + 0.35 * E} filter="url(#oBlurXL)" />
      </g>

      {/* orbits and note stars */}
      {orbits.map((o) => (
        <ellipse key={`o${o.i}`} cx={CX} cy={CY} rx={o.rx} ry={o.ry} transform={`rotate(${o.rot.toFixed(2)} ${CX} ${CY})`}
          fill="none" stroke={o.i < 3 ? lav : C.flare} strokeWidth={o.i < 3 ? 0.9 : 0.8} opacity={(o.i < 3 ? 0.34 + 0.12 * spread : 0.5) * o.vis} />
      ))}
      {orbits.map((o) => (
        <g key={`s${o.i}`} opacity={o.vis}>
          <circle cx={o.x} cy={o.y} r={14 + flash * 18} fill={o.i < 3 ? lav : C.flare} opacity={o.front ? 0.8 : 0.35} filter="url(#oBlurM)" />
          <path d={SPARKLE} transform={`translate(${o.x.toFixed(1)} ${o.y.toFixed(1)}) scale(${o.size.toFixed(2)})`} fill={o.color} opacity={o.front ? 1 : 0.45} />
          <text x={o.x + 14} y={o.y - 10} className="t-mono" fontSize="11" fill={o.color} opacity={o.front ? 0.8 : 0.3}>{labels[o.i]}</text>
        </g>
      ))}


      {/* chord name */}
      {s.prevStep !== cur && <text x={CX} y="666" textAnchor="middle" className="t-serif" fontSize={fs(prevName)} fill={C.moon} opacity={1 - ct} filter="url(#oTextGlow)">{prevName}</text>}
      <text x={CX} y={666 + (1 - ct) * 12} textAnchor="middle" className="t-serif" fontSize={fs(name)} fill={C.moon} opacity={ct} filter="url(#oTextGlow)">{name}</text>
      <text className="t-caps" fontSize="11" fill="rgba(243,227,195,0.78)">
        <textPath href="#oCapArc" startOffset="50%" textAnchor="middle">
          {`${chordQuality(chords[cur] ?? "").toUpperCase()}   ·   ${notes.map((n) => n.replace(/\d/, "")).join("  ·  ")}`}
        </textPath>
      </text>
    </svg>
  );
}
