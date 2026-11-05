"""Short-arm StackChan as a small kinematic + static model (pure Python, no dependencies).

Robot: base -> head yaw -> head pitch -> head; on each side of the head a shoulder STS3215 (left id 1,
right id 5) in a LEGO Technic frame.  One joint per arm, axis = the head's left-right axis.
The arms ride on the head: head pitch tilts them, head yaw turns them.

Angles are the CLI's "neutral" degrees (cli/dance.py): arm 0 = hanging down, 90 = straight forward,
100 = a little above; yaw + = the robot's left; pitch + = up.  Servo goals come from cli/calibration.json.

Frame (same as the dashboard twin, cli/twin/model.js): mm, y up, z forward, +x = the robot's left,
table at y = 0.

Every dimension and mass below is APPROXIMATE (taken from the twin, which is drawn "nicer than
accurate", and from datasheets / estimates).  Measure your robot and replace them.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cli"))
import dance  # noqa: E402  (limits and speeds: ARM_MAX, YAW_MAX, PITCH_MAX, ARM_SPEED_MAX, ARM_ACC, ARMS)

CALIBRATION = json.loads((ROOT / "cli" / "calibration.json").read_text())
LIMITS = dance.LIMITS                 # {"l": (0, 100), "r": (0, 100), "yaw": (-28, 28), "pitch": (-18, 18)}

# --- geometry (mm).  TODO: measure on the real robot; these are the twin's numbers ------------------
YAW_Y = 38.0                          # yaw axis base height above the table
PITCH_Y = 60.0                        # pitch axis height (y), at x = z = 0 in the yaw frame
HEAD_C = (0.0, 30.0, 0.0)             # head centre, pitch frame
HEAD_HALF = (27.0, 27.0, 27.0)        # 54 mm cube
NECK_C, NECK_HALF = (0.0, 14.0, 0.0), (17.0, 8.0, 15.0)   # servo block under the head, yaw frame
SHOULDER = (32.0, 34.0, 0.0)          # left shoulder pivot (horn on the head's side pin), pitch frame; right = mirrored x
# The arm (servo body + LEGO frame) as one box in the shoulder frame: x outward from the pivot,
# y across the arm, z along the arm (z > 0 points forward at 90 deg, down at 0 deg).
ARM_X = (6.0, 35.0)                   # TODO: inner / outer face, outward from the pivot
ARM_HALF_Y = 25.0                     # TODO: half width across the arm (beams at +-21 mm)
ARM_Z = (-16.0, 40.0)                 # TODO: back end / tip, along the arm
ARM_COM = (18.0, 0.0, 10.0)           # TODO: centre of mass (servo body centre), shoulder frame
TABLE_CLEARANCE = 5.0                 # report a collision closer than this to the table
# Static obstacles in the world frame (your drive base etc.): list of (centre, half size), axis-aligned.
# TODO: add your chassis.  The twin's procedural chassis is NOT used: it is decorative and its wheels
# would overlap the hanging arms.
CHASSIS = []                          # e.g. [((0, 30, 0), (32, 8, 29))]

# --- masses (kg) and servo specs.  Estimates. ----------------------------------------------------
M_ARM = 0.075                         # STS3215 55 g + LEGO frame
M_HEAD = 0.15                         # CoreS3 head
M_BASE = 0.07                         # stock servo base (yaw/pitch servos)
SUPPORT_HALF = (25.0, 23.0)           # TODO: support rectangle half size (x, z) on the table: stock base 50 x 46
STS_STALL_NM = 2.9                    # STS3215 12 V datasheet stall torque
HEAD_STALL_NM = 0.18                  # TODO: head pitch servo stall torque (SG90-class estimate)
HEAD_SPEED_DPS = 570.0                # TODO: head servo no-load speed (deg/s), estimate
G = 9.81
STEPS_PER_DEG = 4096 / 360


# --- tiny 4x4 algebra --------------------------------------------------------------------------
def mat_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def translate(x, y, z):
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]


def apply(m, p):
    return tuple(sum(m[i][k] * p[k] for k in range(3)) + m[i][3] for i in range(3))


def inverse_rigid(m):
    r = [[m[j][i] for j in range(3)] for i in range(3)]          # transpose of the rotation
    t = [-sum(r[i][k] * m[k][3] for k in range(3)) for i in range(3)]
    return [r[0] + [t[0]], r[1] + [t[1]], r[2] + [t[2]], [0, 0, 0, 1]]


# --- kinematics --------------------------------------------------------------------------------
def frames(pose):
    """World transforms of the yaw, pitch and both shoulder frames for pose {l, r, yaw, pitch}."""
    yaw = mat_mul(translate(0, YAW_Y, 0), rot_y(pose.get("yaw", 0)))
    pitch = mat_mul(yaw, mat_mul(translate(0, PITCH_Y - YAW_Y, 0), rot_x(-pose.get("pitch", 0))))
    out = {"yaw": yaw, "pitch": pitch}
    for side, s in (("l", 1), ("r", -1)):
        sx, sy, sz = SHOULDER
        out[side] = mat_mul(pitch, mat_mul(translate(s * sx, sy, sz), rot_x(90 - pose.get(side, 0))))
    return out


def arm_points(side, n=(3, 3, 6)):
    """Sample points of the arm box (shoulder frame)."""
    s = 1 if side == "l" else -1
    xs = [s * (ARM_X[0] + (ARM_X[1] - ARM_X[0]) * i / (n[0] - 1)) for i in range(n[0])]
    ys = [-ARM_HALF_Y + 2 * ARM_HALF_Y * i / (n[1] - 1) for i in range(n[1])]
    zs = [ARM_Z[0] + (ARM_Z[1] - ARM_Z[0]) * i / (n[2] - 1) for i in range(n[2])]
    return [(x, y, z) for x in xs for y in ys for z in zs]


def tip(pose, side):
    """World position of the arm tip (middle of the far end), mm."""
    s = 1 if side == "l" else -1
    return apply(frames(pose)[side], (s * sum(ARM_X) / 2, 0, ARM_Z[1]))


def servo_goal(key, value):
    """The servo goal (deg) the CLI would send for neutral angle `value` (same mapping as cli/dance.py)."""
    if key in dance.ARMS:
        j = CALIBRATION["joints"][str(dance.ARMS[key])]
        return j["zero"] + j.get("up", 1) * value
    h = CALIBRATION["head"]
    return h[f"{key}_zero"] + h[f"{key}_sign"] * value


# --- checks ------------------------------------------------------------------------------------
def _inside(p, centre, half):
    """Penetration depth of p into the box (> 0 = inside), mm."""
    return min(half[i] - abs(p[i] - centre[i]) for i in range(3))


def collisions(pose):
    """Clearances (mm) of each arm to the table, the head, the neck and CHASSIS; negative = collision."""
    f = frames(pose)
    obstacles = [("head", f["pitch"], HEAD_C, HEAD_HALF), ("neck", f["yaw"], NECK_C, NECK_HALF)]
    obstacles += [(f"chassis{i}", translate(0, 0, 0), c, h) for i, (c, h) in enumerate(CHASSIS)]
    out = {}
    for side in ("l", "r"):
        world = [apply(f[side], p) for p in arm_points(side)]
        res = {"table": round(min(p[1] for p in world) - TABLE_CLEARANCE, 1)}
        for name, m, c, h in obstacles:
            inv = inverse_rigid(m)
            res[name] = round(-max(_inside(apply(inv, p), c, h) for p in world), 1)   # sampled: approximate
        out[side] = res
    return out


def _torque_about(axis_point, axis_dir, com, mass):
    """Gravity torque (N m) of `mass` at `com` (mm) about an axis."""
    r = [(com[i] - axis_point[i]) / 1000 for i in range(3)]
    fy = -mass * G
    t = (-r[2] * fy, 0.0, r[0] * fy)                      # r x (0, fy, 0)
    return abs(sum(t[i] * axis_dir[i] for i in range(3)))


def _com(pose):
    f = frames(pose)
    parts = [(apply(f["pitch"], HEAD_C), M_HEAD), ((0.0, YAW_Y / 2, 0.0), M_BASE)]
    for side, s in (("l", 1), ("r", -1)):
        parts.append((apply(f[side], (s * ARM_COM[0], ARM_COM[1], ARM_COM[2])), M_ARM))
    return parts


def statics(pose):
    """Holding torques (N m) and the static balance margin (mm) for a pose."""
    f = frames(pose)
    parts = _com(pose)
    pitch_axis = tuple(f["pitch"][i][0] for i in range(3))
    pitch_point = apply(f["pitch"], (0, 0, 0))
    carried = parts[0:1] + parts[2:]                      # head + both arms ride on the pitch servo
    r = [sum((c[i] - pitch_point[i]) * m for c, m in carried) for i in range(3)]   # net moment arm, signed
    out = {"pitch_Nm": round(abs(-r[2] * G / 1000 * pitch_axis[0] + r[0] * G / 1000 * pitch_axis[2]), 4)}
    for side, part in (("l", parts[2]), ("r", parts[3])):
        axis = tuple(f[side][i][0] for i in range(3))
        out[f"{side}_shoulder_Nm"] = round(_torque_about(apply(f[side], (0, 0, 0)), axis, *part), 4)
    mass = sum(m for _, m in parts)
    cx, cz = (sum(c[i] * m for c, m in parts) / mass for i in (0, 2))
    out["com_xz_mm"] = [round(cx, 1), round(cz, 1)]
    out["balance_margin_mm"] = round(min(SUPPORT_HALF[0] - abs(cx), SUPPORT_HALF[1] - abs(cz)), 1)
    return out


def check_pose(pose):
    """Everything about one pose; `problems` empty = fine (within this model's accuracy)."""
    pose = {k: float(pose.get(k, 0)) for k in LIMITS}
    problems = []
    for k, (lo, hi) in LIMITS.items():
        if not lo <= pose[k] <= hi:
            problems.append(f"{k}={pose[k]:g} outside {lo}..{hi}")
    col, st = collisions(pose), statics(pose)
    for side, res in col.items():
        problems += [f"{side} arm hits {name} ({d} mm)" for name, d in res.items() if d < 0]
    if st["pitch_Nm"] > 0.5 * HEAD_STALL_NM:
        problems.append(f"pitch servo holds {st['pitch_Nm']} N m (> half of its est. {HEAD_STALL_NM} stall)")
    if st["balance_margin_mm"] < 0:
        problems.append(f"centre of mass outside the support ({st['balance_margin_mm']} mm)")
    return {"pose": pose, "servo_goal_deg": {k: round(servo_goal(k, v), 1) for k, v in pose.items()},
            "tip_mm": {s: [round(v, 1) for v in tip(pose, s)] for s in ("l", "r")},
            "clearance_mm": col, "statics": st, "problems": problems}


# --- servo timing ------------------------------------------------------------------------------
def arm_move_time(delta_deg, speed, acc):
    """Seconds an STS3215 needs for `delta_deg` with goal speed (steps/s) and acc (x100 steps/s^2):
    trapezoidal profile (triangular when the move is too short to reach `speed`)."""
    d, a = abs(delta_deg) * STEPS_PER_DEG, max(1, acc) * 100.0
    if d == 0:
        return 0.0
    if d >= speed * speed / a:
        return d / speed + speed / a
    return 2 * math.sqrt(d / a)


def arm_position(frm, to, t, speed, acc):
    """Angle (deg) at t seconds into a trapezoidal move frm -> to."""
    d, a, v = abs(to - frm) * STEPS_PER_DEG, max(1, acc) * 100.0, float(speed)
    if d == 0:
        return to
    t_acc = min(v / a, math.sqrt(d / a))
    v = min(v, a * t_acc)
    total = arm_move_time(to - frm, speed, acc)
    if t >= total:
        s = d
    elif t < t_acc:
        s = 0.5 * a * t * t
    elif t < total - t_acc:
        s = 0.5 * a * t_acc ** 2 + v * (t - t_acc)
    else:
        s = d - 0.5 * a * (total - t) ** 2
    return frm + math.copysign(s / STEPS_PER_DEG, to - frm)
