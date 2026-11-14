import type { ClientMsg, Modem } from "../protocol";
import { fmtTime } from "../theme";

interface Props {
  paused: boolean;
  speed: number;
  speeds: number[];
  modem: Modem;
  time: string;
  error: string | null;
  send: (m: ClientMsg) => void;
}

/** Start/Pause/Reset and speed. Enabled on every Mac (SPEC §10.1). */
export function Controls({ paused, speed, speeds, modem, time, error, send }: Props) {
  const setSpeed = (s: number) => send({ type: "speed", step: Math.max(0, Math.min(speeds.length - 1, s)) });

  return (
    <footer className="controls">
      <div className="ctl-group">
        <button className="ctl-play" aria-label={paused ? "Start replay" : "Pause replay"}
          onClick={() => send({ type: "control", action: paused ? "start" : "pause" })}>
          {paused
            ? <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M4 2 L12 7 L4 12 Z" fill="currentColor" /></svg>
            : <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><rect x="3" y="2" width="2" height="10" fill="currentColor" /><rect x="9" y="2" width="2" height="10" fill="currentColor" /></svg>}
        </button>
        <button className="ctl-icon" aria-label="Reset replay" onClick={() => send({ type: "control", action: "reset" })}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" aria-hidden="true"><path d="M4 12a8 8 0 1 0 2.4-5.7" /><path d="M4 4v4h4" /></svg>
        </button>
        <span className="ctl-sep" />
        <div className="speed" role="group" aria-label="Replay speed">
          <button className="ctl-arrow" disabled={speed <= 0} aria-label="Slower" onClick={() => setSpeed(speed - 1)}>‹</button>
          <div className="dots">
            {speeds.map((_, k) => (
              <button key={k} aria-label={`Speed ${k}, ${speeds[k]} bars per second`} aria-pressed={k === speed}
                className={k === speed ? "dot on" : "dot"} onClick={() => setSpeed(k)}>
                <i style={{ width: 5 + k * 1.2, height: 5 + k * 1.2 }} />
              </button>
            ))}
          </div>
          <button className="ctl-arrow" disabled={speed >= speeds.length - 1} aria-label="Faster" onClick={() => setSpeed(speed + 1)}>›</button>
          <span className="caps speed-label">Speed {speed} · {speeds[speed] ?? 0} bars/s</span>
        </div>
      </div>
      <button className="ctl-toggle caps" aria-pressed={modem === "melody"}
        title="On: send strategy as a quiet melody. Off: send it as high pilot tones."
        onClick={() => send({ type: "modem", mode: modem === "melody" ? "pilot" : "melody" })}>
        Melody {modem === "melody" ? "on" : "off"}
      </button>
      {error && <div className="ctl-error" role="status">{error}</div>}
      <div className="mono ctl-time">{time ? fmtTime(time) : "—"}</div>
    </footer>
  );
}
