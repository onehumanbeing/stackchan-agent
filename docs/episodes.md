# Episodes

With the agent running (`dash --llm-url ...`, unless `--no-record`), each session writes
`~/.stackchan/episodes/<YYYYmmdd-HHMMSS>/`:

- `steps.jsonl`: one line per agent turn:
  `{"t": unix_s, "n": 3, "heard": "...", "thinking": "...", "answer": "<raw model lines>", "steps": [{"act": {...}, "ok": true, "ms": 812}], "state": {"servos": {"1": 162.0}, "head": {"yaw": -16.1, "pitch": 23.4}}, "seconds": 2.9, "frame": "00003.jpg"}`
- `<n>.jpg`: the camera frame the model saw in turn n (320 × 240 JPEG).

`act` is exactly what the model asked for (see `cli/agent.py`); `skipped` marks steps not executed (`--no-motion`).
