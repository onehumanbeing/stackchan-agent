"""Touching the head, read from the head servos' positions (the dashboard reads them 5 times a second).

When nothing has told the head to move for a while and it moves anyway, a hand moved it:
  asleep (waiting for the wake word) and the head lifted up  -> it wakes up, as if it heard "Hey Buddy"
  otherwise                                                  -> shy: a shy face and, once the hand lets go, it hides
                                                                its face behind its arms and turns its head away a bit
No speech.  Needs a dashboard robot (head positions, last_move_at) and the agent; the voice loop for waking up.
"""
import threading
import time

QUIET_S = 2.0                # a move we sent ends within this (head and arm moves take at most 1.5 s)
TOUCH_DEG = 3.0              # moved this much (yaw + pitch) between two reads without a command: a hand
LIFT_DEG = 4.0               # asleep, lifted up this much: wake up
LET_GO_S, COOLDOWN_S = 0.6, 5.0
SHY_ARM_DEG, SHY_YAW_DEG = 70, 10


class Touch(threading.Thread):
    def __init__(self, robot, agent, voice=None):
        super().__init__(daemon=True)
        self.robot, self.agent, self.voice = robot, agent, voice

    def run(self):
        prev, start, last_touch, done_at = None, None, 0.0, 0.0
        while True:
            time.sleep(0.2)
            head = self.robot.snapshot().get("head", {})
            pos = (head.get("yaw"), head.get("pitch"))
            if None in pos:
                continue
            now = time.monotonic()
            ours = now - getattr(self.robot, "last_move_at", 0.0) < QUIET_S
            moved = prev and abs(pos[0] - prev[0]) + abs(pos[1] - prev[1]) >= TOUCH_DEG
            prev = pos
            if ours or not self.agent.on:
                start = None
                continue
            if moved and now - done_at > COOLDOWN_S:
                if start is None:
                    start = pos
                    if not self._asleep():
                        self._face("shy")
                last_touch = now
                if self._asleep() and self._up(start, pos) >= LIFT_DEG:
                    self.voice.wake_up()     # "Listening", then it waits for a command
                    start, done_at = None, now
            elif start is not None and now - last_touch > LET_GO_S:   # the hand let go
                if not self._asleep():
                    self._shy()
                start, done_at = None, time.monotonic()

    def _asleep(self):
        return self.voice is not None and self.voice.mode == "idle" and self.agent.idle.is_set()

    def _up(self, a, b):
        return (b[1] - a[1]) * self.robot.snapshot().get("calibration", {}).get("head", {}).get("pitch_sign", 1)

    def _face(self, expression, ms=0):
        try:
            self.robot.request("face.set", expression=expression, **({"ms": ms} if ms else {}))
        except (RuntimeError, TimeoutError):
            pass

    def _shy(self):
        """Hides its face behind its arms and turns away a little, then back."""
        if not (self.agent.motion and self.agent.idle.is_set() and not self.agent.holding):
            return self._face("neutral")
        snap = self.robot.snapshot()
        cal, servos, yaw = snap.get("calibration", {}), snap.get("servos", {}), snap.get("head", {}).get("yaw")
        try:
            for sid in ("1", "5"):
                j = cal.get("joints", {}).get(sid)
                if j and sid in servos:
                    self.robot.request("servo.move", id=int(sid), deg=j["zero"] + j.get("up", 1) * SHY_ARM_DEG, speed=1500, acc=40)
            if yaw is not None:
                self.robot.request("head.move", id=1, deg=yaw + cal.get("head", {}).get("yaw_sign", 1) * SHY_YAW_DEG, ms=400)
            time.sleep(1.4)
            if yaw is not None:
                self.robot.request("head.move", id=1, deg=yaw, ms=700)
            self.agent.rest_arms()
        except (RuntimeError, TimeoutError):
            pass
        time.sleep(0.8)
        self._face("neutral")
