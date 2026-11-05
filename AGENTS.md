# Driving StackChan from an AI agent (Claude Code, Codex, ...)

Use the CLI: every command prints one JSON object (or NDJSON lines for `stream`), so you can read the result directly.

```sh
./stackchan info                       # firmware, Wi-Fi (ip), servo bus
./stackchan scan                       # which servo ids answer
./stackchan read 1                     # one servo: deg, load, volt, temp, moving
./stackchan move 1 15 --wait           # go to +15 deg, print the final state
./stackchan sync 1=10 5=-10            # several servos at once
./stackchan torque 1 off               # limp (lets a person pose the arm)
./stackchan stream --ids 1,5 --hz 20 --seconds 3
./stackchan face happy --say "hi" --ms 3000
./stackchan face --list                # 24 expressions; `face demo` plays them all
./stackchan gesture wave                # wave / nod / shake: keyframes in cli/gestures.py, add your own there
./stackchan status                     # info + every servo, one JSON: is it working?
./stackchan snap -o /tmp/cam.jpg       # what the camera sees (open the file to look)
./stackchan face-snap -o /tmp/face.jpg # what the screen shows
./stackchan dash                       # live page: camera, face, servos (http://<this-machine>:8765/)
./stackchan --host 192.168.1.23 info   # over Wi-Fi instead of USB
```

Rules:
- Move in small steps (≤ 30° at a time, `--speed` ≤ 600) and read back. The arms can hit the head, the table or each other; the firmware only knows the soft limits set with `limits`.
- Before moving a servo you have not moved yet in this session, `read` it and check `volt` (≈ 12 V) and `temp` (< 60 °C).
- `ok: false` / `no reply`: the servo is unpowered, unplugged, or has another id. Do not retry the move blindly: `scan` first.
- New STS3215 servos all ship as id 1. Connect a new one alone and give it its id (`set-id 1 <id>`) before chaining it with the others.
- Servo ids (suggested by `cad-gripper`): left shoulder 1, elbow 2, wrist 3, gripper 4; right shoulder 5, gripper 6.
- Never run `wifi set` with a password in the command line or in a file in this repo.

With a running `dash` that has an agent (`--llm-url`):
```sh
./stackchan agent say "look at the cup and nod"   # one agent turn, as if spoken
./stackchan agent status                          # what it heard, its thinking, each step (ok / error / ms)
./stackchan agent on | off
./stackchan agent lang zh | en                    # language it speaks and listens for
./stackchan view simple | full                    # 3D twin body variant
```

Protocol details (for writing your own client): `docs/protocol.md`.
