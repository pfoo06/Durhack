// Writes mock/hello.json, mock/history.json and mock/state.jsonl (SPEC §10.3).
// Synthetic data shaped like the Jan 2015 franc shock — NOT the real HistData series.
// Four in-process advisers follow the §7.3 rule so the arc (calm → shock → convergence) is visible.
// Run: npm run mock:generate
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Values mirrored from backend/config.py for the mock only.
const BAR_MINUTES = 15;
const SPEEDS = [0, 1, 2, 4, 8, 16, 32, 64];
const START_DIALS = [0, 3, 4, 5];
const SCORE_WINDOW = 96;
const RHO_WINDOW = 96;
const H_CLAMP = [0, 2];
const MOVE_THRESHOLD = 0.05;
const STEP_FRACTION = 0.2;
const SNAP_DISTANCE = 0.1;
const TRIAL_BARS = 16;
const DECISION_BARS = 16; // DECISION_PERIOD_S (2 s) at the default 8 bars/s
const CHORDS = ["A", "Bm", "C♯m", "D", "E", "F♯m", "G♯dim"];
const OWN = 1; // the mock Mac is channel 1

// Weekday trading days, Fri 2 Jan – Fri 23 Jan 2015.
const DAYS = [2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20, 21, 22, 23];
const N = DAYS.length * 96;
const START = 6 * 96; // Mon 12 Jan 00:00
const END = 15 * 96 + 87; // Fri 23 Jan 21:45
const SHOCK = 9 * 96 + 38; // Thu 15 Jan 09:30

const iso = (i) => {
  const m = (i % 96) * BAR_MINUTES;
  return new Date(Date.UTC(2015, 0, DAYS[Math.floor(i / 96)], Math.floor(m / 60), m % 60)).toISOString().replace(".000Z", "Z");
};

let seed = 20150115 >>> 0;
const rnd = () => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 4294967296);
const gauss = () => Math.sqrt(-2 * Math.log(Math.max(rnd(), 1e-9))) * Math.cos(2 * Math.PI * rnd());

// Returns: S = GBP per CHF, F = GBP per EUR.
const rS = new Float64Array(N), rF = new Float64Array(N), lS = new Float64Array(N), lF = new Float64Array(N);
for (let i = 1; i < N; i++) {
  const c = gauss() * 0.0006;
  let s, f;
  if (i < SHOCK) { s = c + gauss() * 0.00012; f = c + gauss() * 0.0001; }
  else {
    // After the shock the link survives but weaker (beta ~0.45) and noisier, so fast advisers re-learn h first.
    const k = i - SHOCK, d = Math.exp(-k / 220), c2 = c * (1 + 2 * d);
    s = 0.45 * c2 + gauss() * 0.00015 * (1 + d);
    f = c2 + gauss() * 0.0001;
    if (k < 4) s += [0.095, 0.07, 0.04, 0.02][k];
    else if (k < 44) s -= 0.0022;
  }
  rS[i] = s; rF[i] = f; lS[i] = lS[i - 1] + s; lF[i] = lF[i - 1] + f;
}

// Rolling correlation for the chart.
const rho = new Float64Array(N);
{
  let a = 0, b = 0, aa = 0, bb = 0, ab = 0;
  for (let i = 1; i < N; i++) {
    a += rS[i]; b += rF[i]; aa += rS[i] ** 2; bb += rF[i] ** 2; ab += rS[i] * rF[i];
    if (i > RHO_WINDOW) { const o = i - RHO_WINDOW; a -= rS[o]; b -= rF[o]; aa -= rS[o] ** 2; bb -= rF[o] ** 2; ab -= rS[o] * rF[o]; }
    const n = Math.min(i, RHO_WINDOW);
    const cv = ab / n - (a / n) * (b / n), va = aa / n - (a / n) ** 2, vb = bb / n - (b / n) ** 2;
    rho[i] = va * vb > 0 ? cv / Math.sqrt(va * vb) : 0;
  }
}

function makeAdviser(ch) {
  return { ch, dial: START_DIALS[ch], step: START_DIALS[ch], cov: 0, vf: 1e-10, h: 1, rH: [], rSw: [], score: 1,
    pnlU: 0, pnlH: 0, trialUntil: -1 };
}

function onBar(a, i) {
  const lam = Math.pow(0.5, 1 / (4 * 2 ** a.dial));
  const hUsed = a.h;
  const rh = rS[i] - hUsed * rF[i];
  a.cov = lam * a.cov + (1 - lam) * rS[i] * rF[i];
  a.vf = lam * a.vf + (1 - lam) * rF[i] ** 2;
  a.h = Math.min(H_CLAMP[1], Math.max(H_CLAMP[0], a.cov / a.vf));
  a.rH.push(rh); a.rSw.push(rS[i]);
  if (a.rH.length > SCORE_WINDOW) { a.rH.shift(); a.rSw.shift(); }
  const v = (xs) => { const m = xs.reduce((p, x) => p + x, 0) / xs.length; return xs.reduce((p, x) => p + (x - m) ** 2, 0) / xs.length; };
  const vS = v(a.rSw);
  a.score = vS > 0 ? Math.min(1, Math.max(0, 1 - v(a.rH) / vS)) : 1;
  if (i > START) {
    // The company owes francs (D11): a rising S is a loss. Hedge = hold h euros.
    a.pnlU += -rS[i] * 100;
    a.pnlH += -rh * 100;
  }
  if (Math.abs(a.dial - a.step) > 0.6) a.step = Math.round(a.dial);
}

// CH 3 goes quiet for a stretch, to show "lost" and resilience.
const lostCh3 = (i) => i > 1340 && i < 1420;

const advisers = [0, 1, 2, 3].map(makeAdviser);
const lines = [];
for (let i = 1; i <= END; i++) {
  advisers.forEach((a) => onBar(a, i));
  if (i < START) continue;
  const visible = advisers.filter((a) => !(a.ch === 3 && lostCh3(i)));
  const leaderOf = (self) => {
    const cands = visible.includes(self) ? visible : [...visible, self];
    return cands.reduce((best, a) => (a.score > best.score || (a.score === best.score && a.ch < best.ch) ? a : best));
  };
  if ((i - START) % DECISION_BARS === 0 && i > START) {
    for (const a of advisers) {
      if (a.trialUntil > i) continue;
      const lead = leaderOf(a);
      if (lead === a || lead.score - a.score < MOVE_THRESHOLD) continue;
      a.dial = Math.abs(lead.dial - a.dial) <= SNAP_DISTANCE ? lead.dial : a.dial + STEP_FRACTION * (lead.dial - a.dial);
      a.trialUntil = i + TRIAL_BARS;
    }
  }
  if (process.env.DEBUG && (i - START) % 48 === 0) console.log(i, advisers.map((a) => a.dial.toFixed(2) + ':' + a.score.toFixed(2)).join('  '));
  const me = advisers[OWN];
  const r = (x, d = 3) => Number(x.toFixed(d));
  lines.push(JSON.stringify({
    type: "state", bar: i, time: iso(i), speed: 4, paused: false, clock: "conductor",
    adviser: {
      channel: OWN, dial: r(me.dial), step: me.step, chord: CHORDS[me.step],
      halfLifeHours: r((4 * 2 ** me.dial * BAR_MINUTES) / 60, 2), h: r(me.h), score: r(me.score),
      pnlUnhedgedPct: r(me.pnlU, 2), pnlHedgedPct: r(me.pnlH, 2),
      leaderChannel: leaderOf(me).ch, heard: lostCh3(i) ? 2 : 3, inTrial: me.trialUntil > i,
    },
  }));
}

const hello = {
  type: "hello", channel: OWN, conductor: true,
  replayStart: iso(START), replayEnd: iso(END), shockTime: iso(SHOCK),
  speeds: SPEEDS, chords: CHORDS,
};
const history = {
  type: "history",
  bars: Array.from({ length: END - START + 1 }, (_, k) => {
    const i = START + k;
    return { i, time: iso(i), S: Number((100 * Math.exp(lS[i] - lS[START])).toFixed(3)),
      F: Number((100 * Math.exp(lF[i] - lF[START])).toFixed(3)), rho: Number(rho[i].toFixed(3)) };
  }),
};

fs.writeFileSync(path.join(here, "hello.json"), JSON.stringify(hello, null, 2) + "\n");
fs.writeFileSync(path.join(here, "history.json"), JSON.stringify(history) + "\n");
fs.writeFileSync(path.join(here, "state.jsonl"), lines.join("\n") + "\n");
console.log(`wrote ${lines.length} state lines, ${history.bars.length} history bars`);
