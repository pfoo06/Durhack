# Brief: sensor-driven music for a niche problem

## The idea in one line
Pick a real, niche problem and solve it by turning a MacBook's built-in sensor readings into music, or music into control. Either the sensors **control** a musical element (input), or a musical element **reports on** something the sensors measure (output, i.e. sonification).

## Your job
1. Propose **3 niche problems** this approach solves well. Each one needs the problem (who has it, and why it matters), the sensor(s), the musical element, and the direction (sensor → music, or music → feedback).
2. Recommend one, with the reason.
3. Wait for the team to pick before building.

## What a good pick looks like
- **Solves a real problem.** A specific person with a specific pain point, not "it's cool". For example, a tool that makes focus, posture, overheating or a room's noise level something you *hear* instead of having to check.
- **The music carries the meaning.** Pitch, tempo, harmony, rhythm, timbre or volume should map to the data in a way a listener understands without being told. Avoid "a sensor triggers a random sound".
- **Easy to demo in 3 minutes,** live, to judges at a table.
- **Can be built in a hackathon:** a working core in about 6 hours, then polish. Uses the sensors marked easy below, with at most one risky one.
- **Bonus: links multiple Macs** (the team has 3), for example a shared beat or each Mac playing one part.

## Musical elements to map to
| Element | Good for |
| --- | --- |
| Pitch | A continuous value going up or down (angle, temperature, pressure) |
| Tempo / rhythm density | Rate, activity, urgency |
| Harmony (major ↔ minor, consonant ↔ dissonant) | Good ↔ bad state, in tune ↔ drifting |
| Filter / brightness | Openness, intensity (for example lid angle opening a low-pass filter) |
| Volume | Closeness, magnitude |
| Instrument / layers | Which source or person, how many things are active |
| Triggers (notes, drums) | Discrete events (taps, clicks, Touch ID pass) |

## Sensors on the team lead's Mac (14" MacBook Pro, M4 Pro), checked on 2026-11-14
| Sensor | Status | Access | Difficulty |
| --- | --- | --- | --- |
| **Lid angle** (degrees, about 0–135) | ✅ **Reads correctly** | `sensors/lid.c`. Uses IOHID with VID `0x05AC`, PID `0x8104`, usage page `0x20`, usage `0x8A`, reading feature report 1 (bytes 1–2, little-endian). Prints one angle per line at 30 Hz. No admin needed. | Easy |
| **Force Touch trackpad** (x/y, finger count, pressure) | ✅ | AppKit `NSEvent` pressure, or in a browser: pointer events plus Safari's `webkitmouseforcechanged` | Easy |
| **Camera** | ✅ | AVFoundation, or the browser's `getUserMedia`. Asks permission. | Easy (computer vision adds effort) |
| **Microphones** | ✅ | AVFoundation, or the browser's `getUserMedia` with Web Audio `AnalyserNode` for loudness and frequencies | Easy |
| **Battery** (temperature, cycles, health, voltage, current) | ✅ Read, no admin | `ioreg -rn AppleSmartBattery`. Example reading: 29.8°C, 178 cycles, 87% health, 12.1 V | Easy |
| **Touch ID** | ✅ yes/no result only | LocalAuthentication. No raw finger data. | Easy |
| **Wi-Fi location** | ✅ | CoreLocation. Asks permission. | Easy |
| **Temperatures, fan speed, power draw** | ✅ present | Read from the System Management Controller (SMC) through IOKit. `powermetrics` works too, but needs `sudo`. | Medium |
| **Bluetooth signal strength** | ✅ present, **currently off** | CoreBluetooth. Gives rough distance to nearby devices. | Medium |
| **Ambient light** (VD6286, a colour-capable chip) | ✅ present | Undocumented, an SPU HID device (usage page `0xFF00`, usage 4) | Medium–hard |
| **Accelerometer** | ✅ present | Undocumented, an SPU HID device (usage page `0xFF00`, usage 3). Other projects needed `sudo`. | Hard / risky |
| **Gyroscope** | ⚠️ unconfirmed | Probably the SPU device with usage page `0xFF00`, usage 9 | Hard / risky |

**Other team members' Macs may differ.** Lid sensors are only on newer MacBooks, and MacBook Airs have no fans. Check with `hidutil list | grep 8104`.

## Technical constraints
- **Swift won't compile on the team lead's Mac** because of a broken Command Line Tools install. Use **C** (clang works) for native sensor readers, and keep each reader a tiny program that prints one value per line.
- The recommended setup:
  - a small native C reader for each sensor, printing values to stdout;
  - a Node server that runs those readers and relays the values over a WebSocket;
  - a browser page that makes the sound with Web Audio.
  
  This keeps the native code tiny, and lets the browser handle audio, the UI and the camera and mic.
- **Linking Macs:** a WebSocket relay over the local Wi-Fi is simplest. For a shared beat, quantise notes to the system clock, which is synced by NTP, usually to within tens of milliseconds. Alternatives are OSC, macOS Network MIDI, or Ableton Link.
- **Existing work** on the local branch `feat/laptop-orchestra` (untested): `sensors/lid.c` (working), plus a rough `server.js` relay and `public/index.html` Web Audio prototype. Reuse it or throw it away.

## Rules
- Follow `AGENTS.md`: use a branch and a pull request, never push to `main`, and claim your area in the ownership table.
- Every permission prompt (camera, mic, Bluetooth, location) must be explained in the UI the first time it appears.
- Keep each sensor optional: if a sensor is missing on a Mac, the app still runs with the others.
