# Short-arm simulation (work in progress)

> **Work in progress, not finished.** Not validated against the real robot. Every dimension, mass
> and servo figure is approximate (see the `TODO` parameters at the top of `shortarm.py`). Use the
> numbers to compare poses and motions with each other, not as measurements.

A small kinematic + static model of the short-arm StackChan: CoreS3 head on its yaw / pitch base,
one STS3215 shoulder per side (id 1 left, id 5 right) in a LEGO Technic frame. Arm angle 0 = hanging
down, 90 = forward, limit 100; the arms ride on the head, so head pitch and yaw move them too.

Pure Python 3 standard library: no install, no robot, no network. It reads `cli/calibration.json`
(servo zeros, up direction) and `cli/dance.py` (joint limits, `ARM_SPEED_MAX`, `ARM_ACC`, the dance
timeline), so it follows whatever the CLI uses.

## Tools

```sh
python3 sim/run.py pose l=90 r=0 yaw=10 pitch=-10   # one pose
python3 sim/run.py sweep                            # all poses on a grid (--step 5, --arm-max 180 to look past the limit)
python3 sim/run.py dance [--amp 0.5]                # the default dance through the servo model
python3 sim/run.py svg l=100 r=30 -o pose.svg       # front + side view of a pose
python3 sim/run.py svg --dance -o dance.svg         # joint curves: commanded vs simulated
python3 -m unittest discover -s sim                 # smoke tests
```

| Command | Output (JSON unless noted) |
|---|---|
| `pose` | servo goal per joint (what the CLI would send), arm tip positions, clearance of each arm to the table / head / neck / `CHASSIS`, gravity torque on the shoulders and the head pitch servo, centre of mass vs the support, `problems` (empty = fine) |
| `sweep` | worst clearance per obstacle over yaw x pitch x arm, the first colliding poses, worst pitch holding torque |
| `dance` | replays `cli/dance.py` with the speed it picks and an STS trapezoidal profile (`ARM_ACC`): arm moves that cannot land on their beat, the largest miss (deg), clearances and pitch torque along the way |
| `svg` | SVG file: box drawing of a pose, or the dance's four joint curves with beat ticks |

Files: `shortarm.py` (parameters, kinematics, checks, servo profile), `run.py` (CLI), `preview.py`
(SVG), `test_shortarm.py`.

## Model

- Frame as in the dashboard twin (`cli/twin/model.js`): mm, y up, z forward, +x = the robot's left.
- Each arm is one box (servo body + LEGO frame) rotating about the head's left-right axis at the
  side pin. Collisions are sampled points of that box against boxes (head, neck, optional `CHASSIS`)
  and the table plane.
- Servo timing: STS3215 goal speed in steps/s and acceleration in 100 steps/s² (4096 steps = 360°);
  a new goal replaces the running move. Head servos: linear over the time they are given.
- Statics only: gravity torques and centre of mass, no dynamics.

## Limitations

- Geometry comes from the twin, which is drawn to look right, not measured. Arm length, the
  shoulder position, masses and the head servo specs are estimates.
- No drive base: `CHASSIS` is empty until you add your own boxes, so the arm-vs-body check only
  covers the head, the neck and the table.
- The servo profile is the datasheet model; load, supply voltage, backlash and cable drag are not
  simulated.
- This model found that `ARM_ACC = 60` made one-beat arm moves in the dance land late (about 0.5 s
  for 30° against 0.43 s per beat); the dance now uses `ARM_ACC = 200` and ramp-aware speeds. Not yet
  confirmed on the robot.
- The dance now streams smooth curves (`cli/motion.py`, `STREAM_HZ`); `run.py dance` still replays it as
  point-to-point keyframe moves, so it is pessimistic about speed and smoothness.
