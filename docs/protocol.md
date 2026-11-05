# StackChan agent protocol (v0.2)

One JSON object per line (NDJSON). The same messages travel over:
- **USB serial**: CoreS3 native USB, any baud, `\n`-terminated lines;
- **Wi-Fi**: WebSocket `ws://stackchan.local:81` (or the IP shown on the face), one text frame per message.

Several clients can be connected at once (USB + up to 4 WebSocket clients). Each one gets its own replies and its own state stream.

## Messages
| Kind | Shape |
|---|---|
| Request | `{"id": 7, "cmd": "servo.move", "args": {"id": 1, "deg": 10}}` (`id` optional, echoed back) |
| Reply | `{"id": 7, "ok": true, "result": {...}}`, or `{"id": 7, "ok": false, "error": "no reply"}` |
| Event | `{"ev": "hello" \| "state" \| "fault", ...}` (no `id`) |
| Binary frame | WebSocket only. First byte is the type: `J` camera JPEG (after `camera.start`), `A` microphone audio (after `mic.start`), `S` speaker audio (client → robot). Audio: 16 kHz mono int16 little endian. |

## Units
- Position `raw`: 0..4095 over 360°. `deg`: (raw − 2048) × 360 / 4096, so 0° is the middle of travel.
- `speed`: steps/s (0 = maximum). `acc`: ×100 steps/s² (0 = maximum).
- `load`: 0.1 % of maximum torque, signed. `volt`: V. `temp`: °C.

## Commands
| cmd | args | result |
|---|---|---|
| `ping` | – | `pong` (ms since boot) |
| `hello`, `sys.info` | – | `fw`, `mac`, `uptime_s`, `heap`, `wifi{connected,ssid,ip,rssi}`, `bus{ok,port,rx,tx,baud,errors}`, `face` |
| `sys.reboot` | – | restarts (no reply) |
| `bus.detect` | – | searches Grove ports C, A, B, then the body's internal head-servo bus (GPIO6/7) (both TX/RX orders, 1 Mbps), saves the result |
| `bus.probe` | – | `probes: [{port, rx, tx, baud, bytes}]`: raw bytes heard after a broadcast ping on every pin pair at 1M / 500k / 115200. Garbled bytes usually mean several servos share an id. |
| `bus.scan` | `from`, `to` (0..253) | `ids`, `checksum_errors` (> 0 usually means two servos share an id) |
| `servo.read` | `id` | `pos`, `deg`, `speed`, `load`, `volt`, `temp`, `moving`, `status` (if nonzero), `limits_deg` |
| `servo.move` | `id`, `deg` or `raw`, `speed` (600), `acc` (20) | `raw`, `deg`, `clamped` |
| `servo.sync_move` | `targets: [{id, deg\|raw}]` (≤ 8), `speed`, `acc` | `count`. One packet, servos start together, no per-servo reply. |
| `servo.torque` | `id`, `on` | – |
| `servo.torque_limit` | `id`, `permille` (0..1000) | – (RAM: resets at power-off) |
| `servo.set_id` | `id`, `new_id` | – (refused if `new_id` already answers) |
| `servo.limits` | `id`, optional `lo_deg` + `hi_deg` | `lo_deg`, `hi_deg` (soft limits, saved in NVS; moves are clamped to them) |
| `head.read` | – | `servos: [{id, raw, deg}]` (StackChan body head servos: 1 = yaw, 2 = pitch; SCS0009, raw 0..1023 over 300°) |
| `head.move` | `id`, `deg` or `raw`, `ms` (travel time, 400) | `raw` |
| `head.torque` | `id`, `on` | – |
| `stream.start` | `ids` (≤ 16), `hz` (1..100, default 20) | `hz`, `count` |
| `stream.stop` | – | – |
| `face.set` | `expression` (neutral happy sad angry doubt sleepy surprised listening thinking), `style`, `gaze: [v, h]` (−1..1), `mouth` (0..1), `blink`, `say` (caption, "" clears), `ms` (caption time, 0 = keep) | `expression`, `style` |
| `face.styles` | – | `styles` (names) |
| `face.snap` | – | `jpeg` (base64, what the screen shows), `bytes` |
| `camera.snap` | `quality` (10..95) | `jpeg` (base64, 320 × 240), `bytes`, `seq` |
| `camera.start` | `fps` (1..15, default 5), `quality` | `fps`, `quality`. **WebSocket only**: frames arrive as binary messages. |
| `camera.stop` | – | – |
| `camera.config` | `quality`, `hmirror`, `vflip` | `quality` |
| `mic.start` | – | `rate`, `chunk` (samples). **WebSocket only**: `A` frames every 40 ms. Fails while the speaker plays (half duplex). |
| `mic.stop` | – | – |
| `speaker.status` | – | `playing`, `mic` |
| `speaker.stop` | – | – (drops queued audio) |
| `speaker.volume` | `volume` (0..255, 180) | – |
| `wifi.scan` | – | `networks: [{ssid, rssi, open}]`, strongest first |
| `wifi.set` | `ssid`, `pass` | – (**USB only**; up to 5 networks in NVS; passwords are never sent back) |
| `wifi.forget` | `ssid` | – |
| `wifi.list` | – | `saved` (SSIDs only) |
| `wifi.status` | – | same as `sys.info` |

## Events
- `hello`: sent on USB at boot and to each WebSocket client when it connects; same fields as `sys.info` (plus `camera`, `face_style`).
- `state`: after `stream.start`, every 1/hz s:
  `{"ev":"state","t":12345,"servos":[{"id":1,"pos":2050,"deg":0.2,"speed":0,"load":-12,"volt":12.1,"temp":31,"moving":false}]}`.
  A servo that does not answer is left out of `servos`.
- `fault`: `{"ev":"fault","id":3,"fault":"no reply"}` when a streamed servo stops answering, `"back"` when it answers again.

## Safety
- Every move is clamped to the servo's soft limits (`servo.limits`).
- When a client disconnects its state and camera streams stop. The servos keep their last goal: nothing moves on its own.
- The firmware never turns torque on by itself; only `servo.torque` and `servo.move` (a new goal) do.
