"""Feetech STS3215 aluminium horn -> two male LEGO Technic cross axles (parametric).

The metal horn stays on the servo; this part bolts to the horn's 4 outer M3
holes and sticks out two LEGO cross axles that plug straight into LEGO parts.

Run:  pip install manifold3d trimesh numpy networkx lxml
      python adapter.py      -> sts3215-lego-adapter.stl next to this file
Measure your horn and edit the HORN_* values before printing.
"""

import math
from pathlib import Path

import numpy as np
import trimesh
from manifold3d import Manifold

# --- Horn side (measure with calipers) -------------------------------------
HORN_BOLT_CIRCLE = 14.0   # diameter of the circle through the 4 hole centres
BOLT_ANGLE = 45.0         # first hole angle; 45 keeps the holes clear of the axles
FLANGE_D = 24.0           # >= bolt circle + counterbore + ~2 mm wall
FLANGE_T = 4.0            # 2 mm of plastic left under each screw head
CENTER_CLEAR_D, CENTER_CLEAR_H = 7.0, 3.2   # pocket for the horn's centre screw head
M3_HOLE_D = 3.2
CBORE_D, CBORE_DEPTH = 6.0, 2.0   # screw heads sit on the axle side

# --- LEGO side ---------------------------------------------------------------
FIT = 0.1                 # printed male axle is made this much smaller than LEGO nominal
AXLE_W, AXLE_ARM = 4.8 - FIT, 1.8 - FIT
AXLE_LEN = 8.0            # 1 LEGO unit sticking out (2 units bent too easily)
ROOT_CHAMFER = 0.6        # 45° fillet at each axle root, where it breaks
PITCH = 8.0               # LEGO hole spacing; the axles sit in holes 1 and 3

SEG = 96
OUT = Path(__file__).parent / "sts3215-lego-adapter.stl"


def cyl(d, h, z=0.0, x=0.0, y=0.0):
    return Manifold.cylinder(h, d / 2, d / 2, SEG).translate((x, y, z))


def box(sx, sy, sz, z=0.0):
    return Manifold.cube((sx, sy, sz), True).translate((0, 0, z + sz / 2))


def male_axle(length, z, x=0.0, chamfer=0.0):
    """LEGO cross axle; the arm tips are rounded so it also turns in a round pin hole."""
    cross = box(AXLE_W, AXLE_ARM, length, z) + box(AXLE_ARM, AXLE_W, length, z)
    axle = cross ^ cyl(AXLE_W, length, z)
    if chamfer:
        c, thin = chamfer, 0.01
        root = None
        for w, a in ((AXLE_W, AXLE_ARM), (AXLE_ARM, AXLE_W)):
            arm = Manifold.batch_hull([box(w + 2 * c, a + 2 * c, thin, z), box(w, a, thin, z + c)])
            root = arm if root is None else root + arm
        axle += root ^ cyl(AXLE_W + 2 * c, c + thin, z)
    return axle.translate((x, 0, 0))


def bolt_points():
    r = HORN_BOLT_CIRCLE / 2
    return [(r * math.cos(math.radians(BOLT_ANGLE + 90 * i)), r * math.sin(math.radians(BOLT_ANGLE + 90 * i)))
            for i in range(4)]


def flange(thickness=FLANGE_T, counterbore=True):
    part = cyl(FLANGE_D, thickness)
    part -= cyl(CENTER_CLEAR_D, min(CENTER_CLEAR_H, thickness - 0.8) + 1, -1)
    for x, y in bolt_points():
        part -= cyl(M3_HOLE_D, thickness + 2, -1, x, y)
        if counterbore:
            part -= cyl(CBORE_D, CBORE_DEPTH + 1, thickness - CBORE_DEPTH, x, y)
    return part




def double_axle():
    return (flange() + male_axle(AXLE_LEN, FLANGE_T, -PITCH, ROOT_CHAMFER)
            + male_axle(AXLE_LEN, FLANGE_T, PITCH, ROOT_CHAMFER))






def to_trimesh(part):
    mesh = part.to_mesh()
    return trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=True)


def main():
    mesh = to_trimesh(double_axle())
    mesh.export(OUT)
    size = mesh.bounds[1] - mesh.bounds[0]
    print(f"{OUT.name}: watertight={mesh.is_watertight} volume={mesh.volume:.1f} mm3 "
          f"size={size[0]:.1f}x{size[1]:.1f}x{size[2]:.1f} mm")


if __name__ == "__main__":
    main()
