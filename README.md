# stackchan-agent

[中文说明](README.zh-CN.md)

Firmware, CLI and a local agent that let an AI (Claude Code, Codex, or any OpenAI-compatible model) see, talk and move a StackChan with Feetech STS bus-servo arms.

- **Firmware** (`firmware/stackchan_agent/`, M5Stack CoreS3): an animated two-eye face (pluggable styles), the camera, STS3215 servos through a Waveshare Bus Servo Adapter A on a Grove port (found automatically), Wi-Fi + mDNS `stackchan.local`.
- **Protocol** (`docs/protocol.md`): NDJSON requests, replies and a state stream, identical over USB serial and WebSocket :81.
- **CLI** (`./stackchan`): JSON in, JSON out, including camera and screen snapshots. Agent guide: `AGENTS.md`.
- **Live page** (`./stackchan dash`): camera, face, a 3D twin, servo states, faults and the agent's thinking and steps in a browser; any machine on the LAN can open it.
- **Agent** (`dash --llm-url ...`): each turn sends what it heard plus the camera frame to an LLM; the answer streams back as one primitive step per line (say, face, gesture, head, arm), executed as each line arrives. Gestures are keyframes in `cli/gestures.py`, so new moves need no firmware change.
- **Voice** (`dash --whisper-model ...`): say "Hey Dude" to wake it; it answers "Listening", looks up, and replies through its own speaker. Speech-to-text is whisper.cpp, text-to-speech is Kokoro (both run locally).
- **Episodes**: every agent turn is recorded (frame, state, heard, thinking, steps) under `~/.stackchan/episodes`; format in `docs/episodes.md`.

## Hardware
- M5Stack CoreS3 (the StackChan head), USB-C to the computer.
- Waveshare Bus Servo Adapter A, UART side wired to a Grove port (C, A or B): adapter TX/RX/GND to the port. Set the adapter's switch to the UART (ESP32) side.
- STS3215 servos on the adapter, powered from the adapter's own supply. Never feed the servo supply into the Grove 5 V pin.

## Build and flash
```sh
arduino-cli core install esp32:esp32        # 3.3.x
arduino-cli lib install M5Unified M5GFX ArduinoJson WebSockets
./flash.sh                                  # or ./flash.sh --build-only
```

## First run
```sh
python3 -m venv cli/.venv && cli/.venv/bin/pip install -r cli/requirements.txt
./stackchan info                 # over USB
./stackchan wifi scan            # the networks the robot sees
./stackchan wifi set "MySSID"    # asks for the password; stored on the robot only
./stackchan scan                 # servo ids on the bus
./stackchan selftest             # each servo: +-10 deg at half torque, checks it got there
```
New STS3215 servos all ship as id 1. With several on the bus, connect one at a time and give each its own id: `./stackchan set-id 1 2`.

## Agent and voice
```sh
brew install whisper-cpp ffmpeg              # speech-to-text (local)
# Kokoro TTS model files -> ~/.cache/stackchan-agent/ (kokoro-v1.0.onnx, voices-v1.0.bin from thewh1teagle/kokoro-onnx releases)
./stackchan --host stackchan.local dash \
  --llm-url http://localhost:8000/v1 --llm-model my-vision-model \
  --whisper-model ~/models/ggml-large-v3-turbo.bin --agent
./stackchan agent say "wave at me"            # type instead of talking
./stackchan agent off | on | status
./stackchan view simple | full                # 3D twin: two shoulder servos, or the full r7 arms
```
The model needs image input (vision) for the camera frame. `--no-motion` keeps every servo still (faces and speech only); `--no-record` turns off episode recording. `STACKCHAN_LLM_URL`, `STACKCHAN_LLM_MODEL`, `STACKCHAN_LLM_KEY` and `STACKCHAN_WHISPER_MODEL` work instead of the flags.

## Face styles
The face engine (`face.cpp`) animates blinking, gaze and expressions; a style only draws one frame into a 320 × 240 sprite.
To add your own: write `void drawMine(LGFX_Sprite &canvas, const face::Look &look)` in a new `.cpp`, add `{"mine", drawMine}` to `STYLES` in `face_styles.cpp`, flash, then select it with `face.set {"style": "mine"}` (`./stackchan raw face.set '{"style":"mine"}'`). The default style `eyes` is two eyes and nothing else.

## Back to the stock firmware
Before the first flash, read the whole 16 MB flash:
`esptool --port PORT read-flash 0 0x1000000 backup.bin`, and restore it with `esptool --port PORT write-flash 0 backup.bin`.

## License
Not decided yet (private for now). Uses M5Unified / M5GFX (MIT), three.js (MIT), Kokoro-82M (Apache-2.0) and whisper.cpp (MIT) at runtime,, the CoreS3 camera pin map from M5CoreS3 (MIT), ArduinoJson (MIT), arduinoWebSockets (LGPL-2.1).
