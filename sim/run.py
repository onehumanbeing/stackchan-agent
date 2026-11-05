"""Short-arm simulation tools.  Every command prints JSON (except `svg`, which writes a file).

  python3 sim/run.py pose l=90 r=0 yaw=10 pitch=-10    one pose: tips, clearances, torques, servo goals
  python3 sim/run.py sweep [--step 5] [--arm-max 180]  every pose on a grid: where would the arms hit?
  python3 sim/run.py dance [--amp 1.0]                 cli/dance.py replayed through the servo model
  python3 sim/run.py svg l=100 r=30 -o /tmp/pose.svg   front + side view of a pose
  python3 sim/run.py svg --dance -o /tmp/dance.svg     the dance's joint curves (commanded vs simulated)

No robot, no network: kinematics and statics only (see sim/README.md for what is and is not modelled).
"""

import argparse
import itertools
import json
import sys

import shortarm as S
from shortarm import dance


def parse_pose(items):
    pose = {}
    for it in items:
        k, _, v = it.partition("=")
        if k not in S.LIMITS:
            sys.exit(f"unknown joint {k!r}: use {', '.join(S.LIMITS)}")
        pose[k] = float(v)
    return pose


def sweep(step, arm_max):
    """Worst clearance per obstacle and the colliding poses (first 20) over yaw x pitch x arm."""
    yaws = range(-dance.YAW_MAX, dance.YAW_MAX + 1, 7)
    pitches = range(-dance.PITCH_MAX, dance.PITCH_MAX + 1, 6)
    arms = range(0, arm_max + 1, step)
    worst, hits, max_pitch_nm, n = {}, [], 0.0, 0
    for yaw, pitch, a in itertools.product(yaws, pitches, arms):
        pose = {"l": a, "r": a, "yaw": yaw, "pitch": pitch}
        col = S.collisions(pose)
        max_pitch_nm = max(max_pitch_nm, S.statics(pose)["pitch_Nm"])
        n += 1
        for side, res in col.items():
            for name, d in res.items():
                if d < worst.get(name, (1e9,))[0]:
                    worst[name] = (d, pose)
                if d < 0 and len(hits) < 20:
                    hits.append({"side": side, "obstacle": name, "mm": d, "pose": pose})
    return {"poses": n, "arm_range": [0, arm_max], "worst_clearance_mm": {k: {"mm": v[0], "pose": v[1]} for k, v in worst.items()},
            "collisions": hits, "max_pitch_holding_Nm": round(max_pitch_nm, 4), "pitch_stall_est_Nm": S.HEAD_STALL_NM}


def dance_moves(amp):
    """The arm and head moves cli/dance.py would send, with the speed it would pick."""
    out = []
    for e in dance.schedule(amp):
        if e[0] != "move" or e[5] is None:
            continue
        _, t, key, value, dur, frm, beat = e
        m = {"t": t, "key": key, "frm": frm, "to": value, "dur": dur, "beat": beat}
        if key in dance.ARMS:
            steps = abs(value - frm) * S.STEPS_PER_DEG
            m["speed"] = max(100, min(dance.ARM_SPEED_MAX, int(steps / dur * 1.3)))
            m["takes"] = S.arm_move_time(value - frm, m["speed"], dance.ARM_ACC)
        else:
            m["takes"] = max(dur, abs(value - frm) / S.HEAD_SPEED_DPS)   # the head is told the time to take
        out.append(m)
    return out


def trajectory(amp, hz=50):
    """[(t, commanded pose, simulated pose)] sampled at `hz` over the whole dance."""
    moves, start = dance_moves(amp), dance.poses(amp)[0][1]
    end_t = dance.beat_s(dance.BEATS) + 0.5
    rows, active, cur, cmd, i = [], {}, dict(start), dict(start), 0
    for k in range(int(end_t * hz)):
        t = k / hz
        while i < len(moves) and moves[i]["t"] <= t:          # a new goal replaces the running move (like the servo)
            m = moves[i]
            m["frm_actual"] = cur[m["key"]]
            active[m["key"]], cmd[m["key"]] = m, m["to"]
            i += 1
        for key, m in active.items():
            dt, f = t - m["t"], m["frm_actual"]
            if key in dance.ARMS:
                cur[key] = S.arm_position(f, m["to"], dt, m["speed"], dance.ARM_ACC)
            else:
                cur[key] = m["to"] if dt >= m["takes"] else f + (m["to"] - f) * dt / m["takes"]
        rows.append((t, dict(cmd), dict(cur)))
    return rows


def dance_report(amp):
    moves = dance_moves(amp)
    late = [m for m in moves if m["takes"] > m["dur"] + 0.02]
    rows = trajectory(amp)
    worst = {"table": 1e9, "head": 1e9, "neck": 1e9}
    max_lag, max_pitch, problems = 0.0, 0.0, set()
    for t, cmd, cur in rows:
        for side, res in S.collisions(cur).items():
            for name, d in res.items():
                worst[name] = min(worst.get(name, 1e9), d)
                if d < 0:
                    problems.add(f"{side} arm hits {name} around t={t:.1f} s")
        max_pitch = max(max_pitch, S.statics(cur)["pitch_Nm"])
    for m in moves:                                           # lag at the moment the joint should land
        land = next((cur for t, _, cur in rows if t >= m["t"] + m["dur"]), rows[-1][2])
        max_lag = max(max_lag, abs(land[m["key"]] - m["to"]) if m["key"] in dance.ARMS else 0.0)
    return {"amp": amp, "moves": len(moves), "dance_check": dance.check(amp) or "ok",
            "late_arm_moves": [{"beat": m["beat"], "key": m["key"], "deg": [round(m["frm"]), round(m["to"])],
                                "has_s": round(m["dur"], 3), "needs_s": round(m["takes"], 3)} for m in late if m["key"] in dance.ARMS][:20],
            "late_arm_moves_total": sum(m["key"] in dance.ARMS for m in late),
            "max_arm_miss_on_beat_deg": round(max_lag, 1), "min_clearance_mm": {k: round(v, 1) for k, v in worst.items()},
            "max_pitch_holding_Nm": round(max_pitch, 4), "problems": sorted(problems)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pose"); p.add_argument("joints", nargs="*")
    p = sub.add_parser("sweep"); p.add_argument("--step", type=int, default=5); p.add_argument("--arm-max", type=int, default=dance.ARM_MAX)
    p = sub.add_parser("dance"); p.add_argument("--amp", type=float, default=1.0)
    p = sub.add_parser("svg"); p.add_argument("joints", nargs="*"); p.add_argument("--dance", action="store_true")
    p.add_argument("--amp", type=float, default=1.0); p.add_argument("-o", "--out", default="pose.svg")
    a = ap.parse_args()
    if a.cmd == "pose":
        print(json.dumps(S.check_pose(parse_pose(a.joints)), indent=1))
    elif a.cmd == "sweep":
        print(json.dumps(sweep(a.step, a.arm_max), indent=1))
    elif a.cmd == "dance":
        print(json.dumps(dance_report(a.amp), indent=1))
    else:
        import preview
        svg = preview.curves(trajectory(a.amp)) if a.dance else preview.pose_svg(parse_pose(a.joints))
        with open(a.out, "w") as f:
            f.write(svg)
        print(json.dumps({"wrote": a.out}))


if __name__ == "__main__":
    main()
