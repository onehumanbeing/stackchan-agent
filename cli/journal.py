"""Episode recorder: one directory per agent session, steps.jsonl plus the camera frame of each turn.

Layout (see docs/episodes.md): ~/.stackchan/episodes/<YYYYmmdd-HHMMSS>/{steps.jsonl, <n>.jpg}
"""
import json
import time
from pathlib import Path

ROOT = Path.home() / ".stackchan" / "episodes"


class Journal:
    def __init__(self, enabled=True):
        self.dir = ROOT / time.strftime("%Y%m%d-%H%M%S") if enabled else None
        self.n = 0

    def write(self, record, jpeg=None):
        if not self.dir:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n += 1
        if jpeg:
            (self.dir / f"{self.n:05d}.jpg").write_bytes(jpeg)
            record = {**record, "frame": f"{self.n:05d}.jpg"}
        with open(self.dir / "steps.jsonl", "a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "n": self.n, **record}, ensure_ascii=False) + "\n")
