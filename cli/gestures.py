"""Gestures: keyframes played from the CLI as primitive moves (no firmware change for a new gesture).

A keyframe is (seconds, {joint: offset_deg}).  Offsets are relative to the pose when the gesture starts,
and arm offsets point toward the middle of travel (so +30 never drives an arm into its end stop).
Joints: "arm:<servo id>" (STS bus), "yaw" / "pitch" (head).  Every gesture ends back at the start pose.
"""
import time

GESTURES = {
    "wave": [
        (0.5, {"arm:1": 30, "arm:5": 30, "yaw": 15, "pitch": -8}),
        (0.4, {"arm:1": 5, "arm:5": 5, "yaw": -15, "pitch": 0}),
        (0.4, {"arm:1": 30, "arm:5": 30, "yaw": 15, "pitch": -8}),
        (0.4, {"arm:1": 5, "arm:5": 5, "yaw": -15, "pitch": 0}),
        (0.4, {"arm:1": 30, "arm:5": 30, "yaw": 0, "pitch": -8}),
        (0.6, {}),
    ],
    "nod": [(0.3, {"pitch": -8}), (0.3, {"pitch": 4}), (0.3, {"pitch": -8}), (0.4, {})],
    "shake": [(0.3, {"yaw": 15}), (0.3, {"yaw": -15}), (0.3, {"yaw": 15}), (0.4, {})],
}
STEPS_PER_DEG = 4096 / 360


def play(link, name, arms=None):
    frames = GESTURES[name]
    joints = {j for _, f in frames for j in f}
    ids = sorted({int(j.split(":")[1]) for j in joints if j.startswith("arm:")})
    if arms is not None:
        ids = [i for i in ids if i in arms]
    start = {i: link.request("servo.read", id=i)["deg"] for i in ids}
    head = {}
    if {"yaw", "pitch"} & joints:
        for s in link.request("head.read")["servos"]:
            head["yaw" if s["id"] == 1 else "pitch"] = s["deg"]
    now = {**{f"arm:{i}": 0.0 for i in ids}, "yaw": 0.0, "pitch": 0.0}
    for dur, frame in frames:
        for i in ids:
            j = f"arm:{i}"
            off = frame.get(j, 0.0)
            sign = -1 if start[i] > 0 else 1                       # toward the middle of travel
            speed = max(50, int(abs(off - now[j]) * STEPS_PER_DEG / dur))
            link.request("servo.move", id=i, deg=start[i] + sign * off, speed=speed, acc=0)
            now[j] = off
        for j, hid in (("yaw", 1), ("pitch", 2)):
            if j in head:
                link.request("head.move", id=hid, deg=head[j] + frame.get(j, 0.0), ms=int(dur * 1000))
        time.sleep(dur)
    return {"gesture": name, "arms": ids, "head": bool(head)}
