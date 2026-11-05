"""Small "talking hands" while the robot speaks: a little arm flick or head nod on the stressed parts of the speech.

People move their hands and head with what they say; the robot does it from the speech audio itself (loud
moments = stress), so every sentence gets it without asking the model.  Moves are small and gentle (the
arms are LEGO on a servo horn: big fast flicks could shake them loose) and always return to where they were.
The model's own head / arm steps win: while one runs (agent.motion_until), no flick starts.
"""
import array
import json
import math
import random
import sys
import threading
import time

RATE = 16000
ARM_DEG = 10                 # arm flick, deg around where the arm is
NOD_DEG, TILT_DEG = 4, 5     # head nod (pitch) and tilt (yaw), deg
GAP_S = 0.5                  # at most one move per half second
ARM_SPEED, ARM_ACC = 500, 20  # STS steps/s and ramp: slow and soft
ARMS = {"left": 1, "right": 5}


def stresses(pcm, frame_s=0.05):
    """Seconds into the audio where the speech is loudest (local peaks), at least GAP_S apart."""
    n = int(RATE * frame_s)
    a = array.array("h", pcm)
    rms = [math.sqrt(sum(x * x for x in a[i:i + n]) / n) for i in range(0, len(a) - n, n)]
    if len(rms) < 3:
        return []
    loud = sorted(rms)[len(rms) // 2] * 1.4         # 1.4 x the median level
    out = []
    for i in range(1, len(rms) - 1):
        t = i * frame_s
        if rms[i] > loud and rms[i] >= rms[i - 1] and rms[i] >= rms[i + 1] and (not out or t - out[-1] >= GAP_S):
            out.append(t)
    return out


class Talk:
    """Plays the moves for one sentence in its own thread; stop() ends it and puts everything back."""

    def __init__(self, robot, agent, pcm):
        self.robot, self.agent, self.end = robot, agent, threading.Event()
        self.cal = robot.snapshot().get("calibration", {})
        self.times = stresses(pcm)
        self.rng = random.Random(len(pcm))
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.t0 = time.monotonic()
        self.thread.start()
        return self

    def stop(self):
        self.end.set()
        self.thread.join(2)

    def _free(self):
        return time.monotonic() > getattr(self.agent, "motion_until", 0)

    def _run(self):
        moves = ["left", "nod", "right", "tilt"]
        for k, t in enumerate(self.times):
            if self.end.wait(max(0.0, self.t0 + t - 0.12 - time.monotonic())):
                return
            if not self._free():
                continue
            move = moves[k % 4] if self.rng.random() < 0.7 else self.rng.choice(moves)
            print(json.dumps({"talk": move, "t": round(t, 2)}), file=sys.stderr, flush=True)
            try:
                self._flick(move)
            except (RuntimeError, TimeoutError):
                pass

    def _flick(self, move):
        r, h, snap = self.robot, self.cal.get("head", {}), self.robot.snapshot()   # where it is now: the base
        if move in ARMS:
            sid = ARMS[move]
            base = snap.get("servos", {}).get(str(sid), {}).get("deg")
            j = self.cal.get("joints", {}).get(str(sid))
            if base is None or not j:
                return
            up, raised = j.get("up", 1), (base - j["zero"]) * j.get("up", 1)
            d = ARM_DEG if raised + ARM_DEG <= 100 else -ARM_DEG      # up a little, or down if it is already high
            r.request("servo.move", id=sid, deg=base + up * d, speed=ARM_SPEED, acc=ARM_ACC)
            self.end.wait(0.3)
            r.request("servo.move", id=sid, deg=base, speed=ARM_SPEED, acc=ARM_ACC)
        else:
            key, hid = ("pitch", 2) if move == "nod" else ("yaw", 1)
            base = snap.get("head", {}).get(key)
            if base is None:
                return
            off = -NOD_DEG if move == "nod" else self.rng.choice((-1, 1)) * TILT_DEG
            r.request("head.move", id=hid, deg=base + h.get(f"{key}_sign", 1) * off, ms=180)
            self.end.wait(0.25)
            r.request("head.move", id=hid, deg=base, ms=250)
