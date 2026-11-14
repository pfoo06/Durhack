// Palette, music facts and small helpers shared by the components.

export const C = {
  ink: "#05060f",
  midnight: "#0b1030",
  dusk: "#1b1f4d",
  lavender: "#c9c3ff",
  periwinkle: "#8f9bff",
  ice: "#a8ecff",
  moon: "#f3e3c3",
  gold: "#e8c48a",
  flare: "#ff6b8b",
  flareSoft: "#ffb3c2",
  flareCyan: "#4ff0ff",
} as const;

// Score thresholds where the synth adds dissonance layers (SPEC §8.2). The UI marks the same points.
export const CLASH_BELOW = 0.7;
export const TRITONE_BELOW = 0.4;
export const NOISE_BELOW = 0.2;

// Chord notes per dial step (SPEC §8.1).
export const CHORD_NOTES: string[][] = [
  ["A3", "C♯4", "E4"],
  ["B3", "D4", "F♯4"],
  ["C♯4", "E4", "G♯4"],
  ["D4", "F♯4", "A4"],
  ["E4", "G♯4", "B4"],
  ["F♯4", "A4", "C♯5"],
  ["G♯4", "B4", "D5"],
];
const PITCH = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];
const ROOT_PC = [9, 11, 1, 2, 4, 6, 8];
export const clashNote = (step: number) => PITCH[(ROOT_PC[step] + 1) % 12];
export const tritoneNote = (step: number) => PITCH[(ROOT_PC[step] + 6) % 12];

export const chordQuality = (name: string) =>
  name.endsWith("dim") ? "diminished" : name.endsWith("m") ? "minor" : "major";
export const chordShort = (name: string) => name.replace("dim", "°");

export const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

export function mix(a: string, b: string, t: number): string {
  const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
  const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
  return `rgb(${pa.map((v, j) => Math.round(v + (pb[j] - v) * t)).join(",")})`;
}

export const fmtPct = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}%`;
export const fmtHours = (h: number) => (h < 10 ? h.toFixed(1) : Math.round(h).toString());

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  const t = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return `${day} — ${t} UTC`;
}

// The four-pointed sparkle used for stars, drawn at unit size.
export const SPARKLE = "M0 -1 C0.1 -0.1 0.1 -0.1 1 0 C0.1 0.1 0.1 0.1 0 1 C-0.1 0.1 -0.1 0.1 -1 0 C-0.1 -0.1 -0.1 -0.1 0 -1Z";

export type Phase = 0 | 1 | 2; // harmony, dissonance, unison
export const PHASES: { word: string; color: string }[] = [
  { word: "Harmony", color: C.lavender },
  { word: "Dissonance", color: C.flareSoft },
  { word: "Unison", color: C.gold },
];

export const prefersReducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
