import type { Conn } from "../useStorm";

/** Shown while the WebSocket is down. useStorm retries every second (SPEC §10.1). */
export function Banner({ conn }: { conn: Conn }) {
  if (conn === "open") return null;
  return (
    <div className="banner" role="status">
      <span className="banner-dot" />
      <span className="serif">{conn === "connecting" ? "Connecting to the backend…" : "Backend not running"}</span>
      <span className="mono">RETRYING EVERY 1 S</span>
    </div>
  );
}
