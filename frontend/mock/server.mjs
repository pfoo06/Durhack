// `npm run dev:mock`: a stand-in backend on ws://localhost:8000/ws (SPEC §10.3), plus the Vite dev server.
// Sends hello + history on connect, then replays state.jsonl at 10 Hz, honouring start/pause/reset/speed.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import { createServer } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (f) => fs.readFileSync(path.join(here, f), "utf8");

const hello = JSON.parse(read("hello.json"));
const history = read("history.json").trim();
const lines = read("state.jsonl").trim().split("\n");

let pos = 0;
let acc = 0;
let paused = true;
let speed = 4;
let modem = "pilot";

const wss = new WebSocketServer({ port: 8000, path: "/ws" });
const frame = () => {
  const s = JSON.parse(lines[pos]);
  return JSON.stringify({ ...s, speed, paused, modem, clock: "free" });
};

wss.on("connection", (ws) => {
  ws.send(JSON.stringify(hello));
  ws.send(history);
  ws.send(frame());
  ws.on("message", (raw) => {
    let msg;
    try { msg = JSON.parse(String(raw)); } catch { return; }
    if (msg.type === "modem" && (msg.mode === "pilot" || msg.mode === "melody")) { modem = msg.mode; return; }
    if (msg.type === "control") {
      if (msg.action === "start") { if (pos >= lines.length - 1) pos = 0; paused = false; }
      if (msg.action === "pause") paused = true;
      if (msg.action === "reset") { pos = 0; acc = 0; paused = true; }
    } else if (msg.type === "speed" && Number.isInteger(msg.step) && msg.step >= 0 && msg.step <= 7) {
      speed = msg.step;
    }
  });
});

setInterval(() => {
  if (!paused) {
    acc += hello.speeds[speed] / 10;
    while (acc >= 1 && pos < lines.length - 1) { pos++; acc--; }
    if (pos >= lines.length - 1) paused = true;
  }
  const f = frame();
  for (const c of wss.clients) if (c.readyState === 1) c.send(f);
}, 100);

console.log(`mock backend on ws://localhost:8000/ws , ${lines.length} states`);
const vite = await createServer({ root: path.join(here, "..") });
await vite.listen();
vite.printUrls();
