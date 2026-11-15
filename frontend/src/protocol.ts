// WebSocket message types. Mirror of SPEC §10.2 — change both together.

export type ClockStatus = "free";
export type Modem = "pilot" | "melody"; // how this Mac sends its strategy: high tones, or a quiet melody

export interface HelloMsg {
  type: "hello";
  channel: number;
  replayStart: string;
  replayEnd: string;
  shockTime: string;
  speeds: number[]; // bars per second for speed steps 0–7
  chords: string[]; // chord name per dial step 0–6
  simulated?: boolean; // --storm demo: the aftermath after the crash is made up
}

export interface HistoryBar {
  i: number;
  time: string;
  S: number; // rebased to 100 at replayStart
  F: number;
  rho: number;
}

export interface HistoryMsg {
  type: "history";
  bars: HistoryBar[];
}

export interface AdviserView {
  channel: number;
  dial: number;
  step: number;
  chord: string;
  halfLifeHours: number;
  h: number;
  score: number;
  pnlUnhedgedPct: number;
  pnlHedgedPct: number;
  leaderChannel: number;
  heard: number;
  inTrial: boolean;
}

/** Another Mac this one hears (from its adviser packets): its strategy and score. */
export interface PeerView {
  channel: number;
  dial: number;
  score: number;
  ageS: number; // seconds since its last packet
}

export interface StateMsg {
  type: "state";
  bar: number;
  time: string;
  speed: number;
  paused: boolean;
  clock: ClockStatus;
  modem: Modem;
  adviser: AdviserView;
  peers?: PeerView[]; // optional: the mock backend doesn't send it
}

export interface ErrorMsg {
  type: "error";
  message: string;
}

export type ServerMsg = HelloMsg | HistoryMsg | StateMsg | ErrorMsg;

export type ClientMsg =
  | { type: "control"; action: "start" | "pause" | "reset" }
  | { type: "speed"; step: number }
  | { type: "modem"; mode: Modem };
