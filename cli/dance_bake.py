"""The default dance baked into a file the robot plays on its own (firmware dance.cpp): no computer while it dances.

  ./stackchan --host ROBOT dance upload        bake cli/dance.py + calibration.json + the music, upload as "dance_1"
  ./stackchan dance                            the dash plays it on the robot when the upload is current, else streams it

The file holds raw servo goals sampled from dance.curves() (calibration applied), so after changing the
choreography, the calibration or the music, upload again.  The last upload's fingerprint is kept in
~/.cache/stackchan-agent/uploaded.json; the dash streams the dance instead while it is out of date.
"""
import hashlib
import json
import struct
import time
from pathlib import Path

import dance

HZ = 25
NAME = "dance_1"
UPLOADED = Path.home() / ".cache" / "stackchan-agent" / "uploaded.json"
CHUNK = 12 * 1024                # bytes per 'U' frame (the firmware takes up to 15 KB)


def fingerprint(calibration, music=dance.MUSIC):
    """Changes when anything baked into the file changes: the choreography, its tuning, the calibration, the music."""
    h = hashlib.sha256(Path(dance.__file__).read_bytes())
    h.update(Path(__file__).read_bytes())
    h.update(json.dumps({k: calibration.get(k) for k in ("joints", "head")}, sort_keys=True).encode())
    if Path(music).exists():
        h.update(Path(music).read_bytes())
    return h.hexdigest()[:16]


def bake(calibration, music=dance.MUSIC, amp=1.0):
    """The dance file (bytes), see firmware/stackchan_agent/dance.h for the layout."""
    cs, j, h = dance.curves(amp), calibration.get("joints", {}), calibration.get("head", {})
    arm = {k: j.get(str(sid), {}) for k, sid in dance.ARMS.items()}
    n = int((dance.beat_s(dance.BEATS) + 0.3) * HZ)
    samples = bytearray()
    for i in range(n):
        t = i / HZ
        raws = []
        for k in ("l", "r"):
            deg = arm[k].get("zero", 0) + arm[k].get("up", 1) * cs[k](t + dance.ARM_LEAD_S)
            raws.append(round(deg * 4096 / 360) + 2048)
        for k in ("yaw", "pitch"):
            deg = h.get(f"{k}_zero", 0) + h.get(f"{k}_sign", 1) * cs[k](t + 1 / HZ)
            raws.append(max(0, min(1023, 512 + round(deg * 1024 / 300))))
        speed = max(cs[k].speed(t + dance.ARM_LEAD_S) for k in ("l", "r")) * 4096 / 360 * 1.5 + 150
        samples += struct.pack("<5h", *raws, int(min(dance.ARM_SPEED_MAX, speed)))
    faces = [(round(dance.beat_s(b) * 1000), f) for b, _, f in dance.TIMELINE if f and b >= 0]
    pcm = dance.decode(music)
    head = b"SCD1" + struct.pack("<3H2BI", HZ, n, len(faces), dance.ARMS["l"], dance.ARMS["r"], len(pcm))
    return head + bytes(samples) + b"".join(struct.pack("<I12s", ms, f.encode()[:12]) for ms, f in faces) + pcm


def upload(link, calibration, name=NAME, music=dance.MUSIC, out=print):
    """Bake and send it as 'U' frames; check the size the robot reports; remember the fingerprint."""
    blob, nb = bake(calibration, music), name.encode()
    for off in range(0, len(blob), CHUNK):
        part = blob[off:off + CHUNK]
        link.ws.send(b"U" + bytes([len(nb)]) + nb + struct.pack("<II", off, len(blob)) + part)
        end = time.time() + 10
        while True:
            m = link.recv(max(0.1, end - time.time()))
            if m is None:
                raise TimeoutError(f"upload: no reply at {off} bytes")
            if m.get("ev") == "upload":
                if m.get("error"):
                    raise RuntimeError(f"upload: {m['error']}")
                break
        out(f"\r{m['got'] * 100 // len(blob):3d} %", end="")
    out("")
    stored = {d["name"]: d for d in link.request("dance.list")["dances"]}
    if stored.get(name, {}).get("bytes") != len(blob):
        raise RuntimeError(f"upload: the robot has {stored.get(name)}, expected {len(blob)} bytes")
    done = json.loads(UPLOADED.read_text()) if UPLOADED.exists() else {}
    done[name] = fingerprint(calibration, music)
    UPLOADED.write_text(json.dumps(done, indent=1))
    return {"name": name, "bytes": len(blob), "seconds": round(dance.beat_s(dance.BEATS) + 0.3, 1)}


def current(calibration, name=NAME):
    """True when the robot's copy matches what would be baked now."""
    done = json.loads(UPLOADED.read_text()) if UPLOADED.exists() else {}
    return done.get(name) == fingerprint(calibration)


class OnRobot:
    """Same shape as dance.Dance (run(), stop, amp, loops) for the dash: one command, the robot does the rest."""

    def __init__(self, robot, name=NAME, loops=1):
        import threading
        self.robot, self.name, self.amp, self.loops, self.stop = robot, name, 1.0, loops, threading.Event()

    def run(self):
        for _ in range(self.loops):
            if self.stop.is_set():
                break
            self.robot.request("dance.play", name=self.name)
            time.sleep(1.0)                          # it eases into the first pose first
            while not self.stop.is_set() and self.robot.request("dance.status").get("playing"):
                time.sleep(0.2)
        if self.stop.is_set():
            self.robot.request("dance.stop")
