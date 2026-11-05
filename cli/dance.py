"""The default dance (10 s): a fixed choreography on a beat clock, with the music played by the robot's own speaker.

No model, no camera: the same 10 s every time.  Started by the CLI or by saying "music" after the wake word.  Every pose sits on a beat of the timeline below;
the move toward it starts at the previous pose and takes exactly the time between them, so poses land on
the beat.  Arms use the STS speed + acceleration ramp (soft start and stop), the head its travel time.

  ./stackchan dance --dry-run        print the timeline and check limits, no robot needed
  ./stackchan dance --amp 0.5        half amplitude (and so half speed): a first, careful run
  ./stackchan dance                  full dance;  --loop 3 repeats it;  --music FILE changes the song
  ./stackchan dance stop             emergency stop: music off, servos ease back to neutral

To use another song: set BPM and MUSIC_OFFSET_S (time of the first beat) for it, and BEATS for its length.
"""
import subprocess
import threading
import time
from pathlib import Path

# --- tuning -------------------------------------------------------------------------------------
BPM = 140                    # the song's tempo (measured; one beat = 0.43 s)
MUSIC_OFFSET_S = 0.295       # the first beat, seconds after the music starts
BEATS = 23                   # length: 23 beats = 10.2 s; the song (20 s) is cut there with a fade-out
FADE_S = 1.2                 # music fade-out at the end
MUSIC = Path.home() / ".cache" / "stackchan-agent" / "dance.mp3"
VOLUME = 200                 # speaker 0..255 (the agent uses 180)
ARM_MAX, YAW_MAX, PITCH_MAX = 100, 28, 30    # deg from neutral; arms: 0 = down, toward the middle of travel
ARM_SPEED_MAX = 3200         # STS steps/s (~280 deg/s)
HEAD_SNAP_S = 0.12           # the head snaps to each pose this fast, then holds it (crisper than gliding)
ARM_ACC = 200                # x100 steps/s^2: the soft start / stop of every arm move (60 was too soft: arms fell behind the beat)
ARMS = {"l": 1, "r": 5}      # servo ids: left, right shoulder
RATE = 16000

# --- choreography: (beat, pose, face).  Pose keys: l, r (arms, deg up), yaw (+ = its left), pitch (+ = up).
# Keys left out keep their value.  Beat 0 is the first beat of the music.
def _timeline():
    t = [(-1.0, {"l": 0, "r": 0, "yaw": 0, "pitch": 0}, "neutral")]
    add = lambda b, face=None, **pose: t.append((b, pose, face))

    def bounce(b, side, hi=60, lo=30, yaw=18):      # a DJ head bob: nod down hard on the beat, then throw the head
        add(b, l=hi if side > 0 else lo, r=lo if side > 0 else hi, yaw=yaw * side * 0.3, pitch=-12)
        add(b + 0.5, yaw=yaw * side, pitch=26)          # up and swing it to one side on the "and"; arms shift weight

    add(0, "excited", l=20, r=20, pitch=-12)          # 0-2: crouch, arms to the ready pose, eyes light up
    add(1, l=40, r=40, pitch=26)
    for b in range(2, 6):
        bounce(b, 1 if b % 2 else -1)
    add(6, l=100, r=100, yaw=0, pitch=30)            # hit 1: both arms up, head up, then a head wiggle
    add(6.5, yaw=12)
    add(7, l=45, r=45, yaw=-12, pitch=0)
    add(7.5, yaw=0)
    for b in range(8, 12):
        bounce(b, 1 if b % 2 else -1)
    add(12, l=80, r=20, yaw=20, pitch=-6)            # the drop: two big swings, freeze, open up on the strong beat
    add(13, l=30, r=80, yaw=-20, pitch=-6)
    add(13.25, r=80, yaw=-20, pitch=-6)              # freeze a quarter beat (the left arm already rises to open up)
    add(14, "surprised", l=95, r=95, yaw=0, pitch=30)
    add(14.5, "excited")
    add(15, l=45, r=45, pitch=0)
    add(16, "wink", l=100, r=30, yaw=18, pitch=22)   # a wave, left -> right -> left; the head follows the high arm
    add(16.5, pitch=-10)
    add(17, l=30, r=100, yaw=-18, pitch=22)
    add(17.5, pitch=-10)
    add(18, l=100, r=30, yaw=18, pitch=22)
    add(18.5, pitch=-10)
    add(19, "happy", l=45, r=45, yaw=0, pitch=0)
    add(20, l=100, r=20, yaw=0, pitch=26)            # one arm high, one low: freeze half a beat
    add(20.5, l=100, r=20, yaw=0, pitch=26)
    add(22, "neutral", l=0, r=0, yaw=0, pitch=0)     # together back to neutral, on the last strong beat
    return sorted(t, key=lambda f: f[0])


TIMELINE = _timeline()
LIMITS = {"l": (0, ARM_MAX), "r": (0, ARM_MAX), "yaw": (-YAW_MAX, YAW_MAX), "pitch": (-PITCH_MAX, PITCH_MAX)}


def arm_speed(steps, dur):
    """Cruise speed (steps/s) for a move of `steps` to land in `dur` s on the STS ramp (accelerate, cruise, brake),
    with 10 % to spare; None when even ARM_SPEED_MAX cannot make it."""
    a = ARM_ACC * 100
    disc = (a * dur) ** 2 - 4 * a * steps
    if disc < 0:
        return None
    v = (a * dur - disc ** 0.5) / 2 * 1.1
    return v if v <= ARM_SPEED_MAX else None


def beat_s(b):
    return MUSIC_OFFSET_S + b * 60.0 / BPM


def poses(amp=1.0):
    """[(beat, full pose, face)]: every keyframe with the joints it leaves out carried over, clamped."""
    out, pose = [], {}
    for b, p, face in TIMELINE:
        pose = {**pose, **{k: max(LIMITS[k][0], min(LIMITS[k][1], v * amp)) for k, v in p.items()}}
        out.append((b, dict(pose), face))
    return out


def schedule(amp=1.0):
    """Time-sorted events: ("move", t, joint, value, seconds) starts a move at t that lands `seconds` later,
    on the joint's own next keyframe (a keyframe that leaves a joint out does not cut its move short);
    ("face", t, name).  A keyframe repeating the joint's value is a hold: nothing is sent."""
    events, last = [], {}
    for b, p, face in TIMELINE:
        if face:
            events.append(("face", beat_s(b), face))
        for k, v in p.items():
            v = max(LIMITS[k][0], min(LIMITS[k][1], v * amp))
            pb, pv = last.get(k, (b - 1, None))
            if v != pv:
                t0 = beat_s(pb) if k in ARMS else max(beat_s(pb), beat_s(b) - HEAD_SNAP_S)   # the head snaps in late, on the beat
                events.append(("move", t0, k, v, max(0.08, beat_s(b) - t0), pv, b))
            last[k] = (b, v)
    return sorted(events, key=lambda e: e[1])


def check(amp=1.0):
    """Problems with the timeline (empty = fine): limits, arm speed, the end pose."""
    errs = []
    for e in schedule(amp):
        if e[0] != "move":
            continue
        _, t, k, v, dur, frm, b = e
        if frm is None:
            continue                               # the first pose: reached before the music starts
        lo, hi = LIMITS[k]
        if not lo <= v <= hi:
            errs.append(f"beat {b}: {k}={v} outside {lo}..{hi}")
        if k in ARMS and arm_speed(abs(v - frm) * 4096 / 360, dur) is None:
            errs.append(f"beat {b}: arm {k} {frm:.0f}->{v:.0f} in {dur:.2f} s is too fast (max {ARM_SPEED_MAX} steps/s, acc {ARM_ACC})")
    end = poses(amp)[-1][1]
    if any(end.values()):
        errs.append(f"does not end at neutral: {end}")
    return errs


def dry_run(amp=1.0, out=print):
    out(f"BPM {BPM}, first beat {MUSIC_OFFSET_S} s, {BEATS} beats = {beat_s(BEATS):.1f} s, amp {amp}")
    out("   time   beat   left  right   yaw  pitch  face")
    for b, pose, face in poses(amp):
        out(f"{beat_s(b):7.2f} {b:6.2f} {pose['l']:6.0f} {pose['r']:6.0f} {pose['yaw']:5.0f} {pose['pitch']:6.0f}  {face or ''}")
    errs = check(amp)
    moves = sum(e[0] == "move" for e in schedule(amp))
    out(f"check: ok ({moves} moves; limits, arm speed, ends at neutral)" if not errs else "check FAILED:\n  " + "\n  ".join(errs))
    return not errs


def decode(path):
    """Music -> 16 kHz mono int16 (ffmpeg); b"" when there is none: the dance then runs on its clock alone."""
    try:
        end = beat_s(BEATS) + 0.3
        return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-t", f"{end:.2f}",
                               "-af", f"afade=t=out:st={end - FADE_S:.2f}:d={FADE_S}", "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"],
                              check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return b""


class Dance:
    """Runs on any robot object with fire(cmd, **args) (no wait), request(cmd, **args) and send_audio(pcm)."""

    def __init__(self, robot, calibration, amp=1.0, loops=1, music=MUSIC):
        self.robot, self.amp, self.loops, self.music = robot, amp, loops, music
        self.cal, self.stop = calibration, threading.Event()

    def _command(self, key, value, dur, frm=None):
        """The robot command that moves one joint to `value` (deg from neutral) in `dur` s."""
        j, h = self.cal.get("joints", {}), self.cal.get("head", {})
        if key in ARMS:
            sid = ARMS[key]
            zero = j.get(str(sid), {}).get("zero", 0)
            up = j.get(str(sid), {}).get("up", -1 if zero > 0 else 1)
            steps = abs(value - (frm or 0)) * 4096 / 360
            speed = max(100, int(arm_speed(steps, dur) or ARM_SPEED_MAX)) if frm is not None else 600
            return "servo.move", dict(id=sid, deg=zero + up * value, speed=speed, acc=ARM_ACC)
        hid = 1 if key == "yaw" else 2
        return "head.move", dict(id=hid, deg=h.get(f"{key}_zero", 0) + h.get(f"{key}_sign", 1) * value, ms=int(min(dur, HEAD_SNAP_S) * 1000))

    def _start_music(self):
        """Start the song; returns the clock's zero (the moment it is heard), or now if there is no music."""
        pcm = self.pcm
        if not pcm:
            return time.monotonic()
        self.robot.request("speaker.volume", volume=VOLUME)
        head, self.rest = pcm[:RATE * 2 * 2], pcm[RATE * 2 * 2:]      # 2 s now, the rest streamed during the dance
        self.robot.send_audio(head)
        t0 = time.monotonic()
        while time.monotonic() - t0 < 1.5:
            if self.robot.request("speaker.status").get("playing"):
                return time.monotonic() - 0.02
            time.sleep(0.02)
        return time.monotonic()

    def _feed(self, start):
        """Send the rest of the song about 1.5 s ahead of playback, so dance commands are never stuck behind it."""
        sent = 2.0
        while self.rest and not self.stop.is_set():
            if sent - (time.monotonic() - start) < 1.5:
                self.robot.send_audio(self.rest[:RATE * 2])
                self.rest, sent = self.rest[RATE * 2:], sent + 1.0
            time.sleep(0.05)

    def run(self):
        try:
            self.pcm = decode(self.music)
            self.neutral(stop=False)                 # start from neutral (only once: loops flow into each other)
            time.sleep(0.8)
            for _ in range(self.loops):
                if self.stop.is_set():
                    break
                self._once()
        finally:
            self.neutral()

    def _once(self):
        self.rest = b""
        start = self._start_music()
        threading.Thread(target=self._feed, args=(start,), daemon=True).start()
        for e in schedule(self.amp):
            while not self.stop.is_set() and time.monotonic() < start + e[1]:
                time.sleep(min(0.005, max(0.0, start + e[1] - time.monotonic())))
            if self.stop.is_set():
                return
            if e[0] == "face":
                self.robot.fire("face.set", expression=e[2])
            elif e[5] is not None:                       # (the first pose was reached before the music)
                _, _, key, value, dur, frm, _ = e
                cmd, args = self._command(key, value, dur, frm)
                self.robot.fire(cmd, **args)
        while not self.stop.is_set() and time.monotonic() < start + beat_s(BEATS) + 0.3:
            time.sleep(0.01)

    def neutral(self, stop=True):
        """Back to neutral, slowly; music off.  Used at the start, the end and by the emergency stop."""
        if stop:
            self.stop.set()
        for cmd, args in (("speaker.stop", {}), ("speaker.volume", {"volume": 180}), ("face.set", {"expression": "neutral"})):
            try:
                self.robot.request(cmd, **args)
            except (RuntimeError, TimeoutError):
                pass
        for key in LIMITS:
            cmd, args = self._command(key, 0, 0.8)
            try:
                self.robot.request(cmd, **args)
            except (RuntimeError, TimeoutError):
                pass
