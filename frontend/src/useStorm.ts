import { useCallback, useEffect, useRef, useState } from "react";
import type { ClientMsg, HelloMsg, HistoryBar, ServerMsg, StateMsg } from "./protocol";

export type Conn = "connecting" | "open" | "closed";

const RETRY_MS = 1000; // SPEC §10.1: retry every 1 s
const ERROR_SHOW_MS = 4000;

/** Where the backend lives: same host in production (served by FastAPI), :8000 in Vite dev. `?ws=` overrides. */
export function backendUrl(): string {
  const override = new URLSearchParams(location.search).get("ws");
  if (override) return override;
  return import.meta.env.DEV ? "ws://localhost:8000/ws" : `ws://${location.host}/ws`;
}

export function useStorm(url: string) {
  const [conn, setConn] = useState<Conn>("connecting");
  const [hello, setHello] = useState<HelloMsg | null>(null);
  const [history, setHistory] = useState<HistoryBar[]>([]);
  const [state, setState] = useState<StateMsg | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let errTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const sock = new WebSocket(url);
      ws.current = sock;
      sock.onopen = () => setConn("open");
      sock.onmessage = (e) => {
        let msg: ServerMsg;
        try { msg = JSON.parse(e.data); } catch { return; }
        if (msg.type === "hello") setHello(msg);
        else if (msg.type === "history") setHistory(msg.bars);
        else if (msg.type === "state") setState(msg);
        else if (msg.type === "error") {
          setError(msg.message);
          clearTimeout(errTimer);
          errTimer = setTimeout(() => setError(null), ERROR_SHOW_MS);
        }
      };
      sock.onclose = () => {
        setConn("closed");
        if (!stopped) retry = setTimeout(connect, RETRY_MS);
      };
      sock.onerror = () => sock.close();
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearTimeout(errTimer);
      ws.current?.close();
    };
  }, [url]);

  const send = useCallback((msg: ClientMsg) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(msg));
  }, []);

  return { conn, hello, history, state, error, send };
}

/** A value that updates at most every `ms` — the chart re-renders at most 4×/s (SPEC §10.1). */
export function useThrottled<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  const last = useRef(0);
  useEffect(() => {
    const now = performance.now();
    const wait = Math.max(0, ms - (now - last.current));
    const id = setTimeout(() => { last.current = performance.now(); setV(value); }, wait);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}
