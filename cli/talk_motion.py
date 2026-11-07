"""Talking motion while the robot speaks: the head nods and sways on the beats of the speech, an arm now and then.

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
ARM_DEG = 20                 # arm flick, deg around where the arm is
NOD_DEG, SWAY_DEG = 6, 6     # head beat: a nod (pitch) while the head sways to the other side (yaw), deg
SWAY_MS, NOD_MS, UP_MS = 900, 380, 520   # slow and overlapping: the next beat starts before the sway ends
GAP_S, FILL_S = 0.6, 1.0     # beats at stresses at least 0.5 s apart, and one at least every 0.9 s while it talks
ARM_P = 0.3                  # chance that an arm joins a beat
ARM_SPEED, ARM_ACC = 450, 12  # STS steps/s and ramp: slow and soft (20 deg in about 0.5 s)
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
    """Moves with one sentence in its own thread: on every beat the head nods and sways to the other side together
    (like a person talking), now and then an arm joins; stop() puts the head back where it was."""

    def __init__(self, robot, agent, pcm):
        self.robot, self.agent, self.end = robot, agent, threading.Event()
        self.cal = robot.snapshot().get("calibration", {})
        self.times, self.dur = stresses(pcm), len(pcm) / (2 * RATE)
        self.rng = random.Random(len(pcm))
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.t0 = time.monotonic()
        self.thread.start()
        return self

    def more(self, pcm, offset_s):
        """More audio of the same sentence (streamed TTS), starting offset_s into it."""
        self.times += [offset_s + t for t in stresses(pcm)]
        self.dur = offset_s + len(pcm) / (2 * RATE)

    def stop(self):
        self.end.set()
        self.thread.join(2)

    def _free(self):
        return time.monotonic() > getattr(self.agent, "motion_until", 0)

    def _beat_after(self, last):
        """When the next beat is: the next stress, or FILL_S after the last one; None while no audio is that far yet."""
        t = next((t for t in self.times if t >= last + GAP_S), None)
        t = last + FILL_S if t is None or t > last + FILL_S else t
        return t if t < self.dur - 0.3 else None

    def _run(self):
        h = self.cal.get("head", {})
        head = self.robot.snapshot().get("head", {})
        yaw0, pitch0 = head.get("yaw"), head.get("pitch")
        if yaw0 is None or pitch0 is None:
            return
        ys, ps = h.get("yaw_sign", 1), h.get("pitch_sign", 1)
        if "pitch_zero" in h:                    # never below the lowest pitch (calibration pitch_min, deg from home)
            pitch0 = h["pitch_zero"] + ps * max((pitch0 - h["pitch_zero"]) * ps, h.get("pitch_min", -10))
        side, last, moved = self.rng.choice((-1, 1)), -GAP_S, False
        try:
            while not self.end.is_set():
                t = self._beat_after(last)
                if t is None:                    # streamed audio still coming (or the sentence is ending)
                    self.end.wait(0.1)
                    continue
                if self.end.wait(max(0.0, self.t0 + t - 0.15 - time.monotonic())):
                    return
                last = t
                if not self._free():             # the model's own move runs
                    continue
                print(json.dumps({"talk": "beat", "t": round(t, 2)}), file=sys.stderr, flush=True)
                yaw = yaw0 + ys * side * SWAY_DEG * self.rng.uniform(0.5, 1.0)
                side, moved = -side, True
                self.robot.fire("head.move", id=1, deg=yaw, ms=SWAY_MS)          # sway and nod at once
                self.robot.fire("head.move", id=2, deg=pitch0 + ps * NOD_DEG * self.rng.uniform(0.6, 1.0), ms=NOD_MS)   # up, then back down: a nod from the lowest pose
                if self.rng.random() < ARM_P:
                    threading.Thread(target=self._arm, args=(self.rng.choice(list(ARMS)),), daemon=True).start()
                if self.end.wait(NOD_MS / 1000):
                    return
                self.robot.fire("head.move", id=2, deg=pitch0, ms=UP_MS)
        finally:
            if moved:
                self.robot.fire("head.move", id=1, deg=yaw0, ms=700)
                self.robot.fire("head.move", id=2, deg=pitch0, ms=600)

    def _arm(self, side):
        sid, snap = ARMS[side], self.robot.snapshot()
        base = snap.get("servos", {}).get(str(sid), {}).get("deg")
        j = self.cal.get("joints", {}).get(str(sid))
        if base is None or not j:
            return
        up, raised = j.get("up", 1), (base - j["zero"]) * j.get("up", 1)
        d = ARM_DEG if raised + ARM_DEG <= 100 else -ARM_DEG      # up a little, or down if it is already high
        try:
            self.robot.request("servo.move", id=sid, deg=base + up * d, speed=ARM_SPEED, acc=ARM_ACC)
            time.sleep(0.5)
            self.robot.request("servo.move", id=sid, deg=base, speed=ARM_SPEED, acc=ARM_ACC)
        except (RuntimeError, TimeoutError):
            pass
