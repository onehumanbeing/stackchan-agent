# Hardware

The robot is a stock StackChan with two bus-servo shoulders and LEGO Technic arms.
The only custom part is one 3D-printed adapter between the servo horn and LEGO.

## Bill of materials

| Qty | Part | Notes |
|---|---|---|
| 1 | Official StackChan kit (M5Stack CoreS3) | Head, face, camera, mic, speaker. Its two SCS0009 head servos (1 = yaw, 2 = pitch) are on their own bus (Serial2, GPIO7 RX / GPIO6 TX), already handled by the firmware. |
| 2 | Feetech STS3215 bus servo | Shoulders: id 1 = left, id 5 = right. |
| 1 | Waveshare Bus Servo Adapter (A) | Jumper on **A** (UART / ESP32 side). |
| 1 | Grove cable | CoreS3 Grove Port A to the adapter's UART pins. |
| 1 | Servo power supply | Into the adapter's DC input. The arm servos read ≈ 12 V in this build (`./stackchan read 1`). |
| 2+ | 3D-printed adapter, [`sts3215-lego-adapter.stl`](sts3215-lego-adapter.stl) | One per servo horn. |
| - | Assorted LEGO Technic parts | Beams, axles and pins for the arms; no fixed list. |

## Wiring

```
CoreS3 Grove Port A ──Grove cable──▶ Waveshare Bus Servo Adapter (A) ──servo bus──▶ STS3215 id 1 ──▶ STS3215 id 5
 (GPIO1 / GPIO2)                      jumper on A (UART), own supply     1 Mbps          left shoulder    right shoulder
```

- Adapter TX / RX / GND to the Grove port (the firmware turns the Grove 5 V on, in case the adapter takes its logic
  power from there). The firmware tries Grove ports C, A and B in both TX/RX orders at boot and uses the one where a servo
  answers, so a swapped pair still works.
- The bus runs at 1 Mbps (the STS3215 default).
- Never feed the servo supply into the Grove 5 V pin.
- New STS3215 servos all ship as id 1. Connect the right shoulder alone first and run `./stackchan set-id 1 5`,
  then chain both.

## Mounting

- Screw the printed adapter onto the 4 outer M3 holes of the servo's stock aluminium horn (the horn stays on the
  servo). Its two male cross axles then take any LEGO Technic part with cross holes.
- Build each arm from LEGO Technic parts on the adapter.
- Mount each shoulder on the body through the three holes on each side of the StackChan body.

## The printed part

[`sts3215-lego-adapter.stl`](sts3215-lego-adapter.stl), units mm.

- Flange Ø24 × 4 mm with 4 × Ø3.2 holes (counterbored Ø6 × 2 mm) on a Ø14 circle, and a Ø7 × 3.2 mm pocket
  underneath for the horn's centre screw head.
- Two LEGO cross axles (4.8 / 1.8 mm, minus 0.1 mm for fit), 16 mm apart (LEGO holes 1 and 3), 8 mm long,
  with a 0.6 mm root chamfer. Two axles share the torque: a single cross axle is too weak for the servo.
- The 14 mm bolt circle was confirmed by a test fit, not measured. No load or torque test has been done.

Source: [`adapter.py`](adapter.py) (manifold3d + trimesh), all dimensions as parameters at the top. Measure your
horn, edit the `HORN_*` values and regenerate:

```sh
pip install manifold3d trimesh numpy networkx lxml
python hardware/adapter.py      # -> hardware/sts3215-lego-adapter.stl
```

Print notes (as printed here): PLA, flange down, no supports, 100 % infill, 4 walls, 6 top / 6 bottom layers.
An earlier version with 16 mm axles nearly snapped when bent by hand, which is why the axles are short and chamfered.

## Calibration

Home (0) is both arms hanging straight down:

```sh
./stackchan torque 1 off; ./stackchan torque 5 off   # limp: pose both arms hanging straight down
./stackchan calibrate --arms                         # save that pose as home
```

`calibrate` reads each arm servo listed in [`cli/calibration.json`](../cli/calibration.json) and stores its current
angle as that joint's `zero`; a servo that does not answer keeps its old zero. `--arms` leaves the head zeros alone
(without it, the head's current pose is saved as straight ahead too). The agent, the dance and the 3D twin all move
relative to these zeros; `up` in the same file is the direction (+1 / -1) that raises each arm forward.
