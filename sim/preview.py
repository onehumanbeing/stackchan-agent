"""SVG previews (no dependencies): a pose in front and side view, and the dance's joint curves."""

import itertools

import shortarm as S
from shortarm import dance

COLORS = {"head": "#e8e8e4", "neck": "#8a8e94", "l": "#2a6fd6", "r": "#d6542a", "chassis": "#555"}


def _box_corners(m, centre, half):
    return [S.apply(m, tuple(centre[i] + sx * half[i] for i, sx in enumerate(s))) for s in itertools.product((-1, 1), repeat=3)]


def _hull(pts):
    """2D convex hull (monotone chain)."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def _boxes(pose):
    f = S.frames(pose)
    out = [("neck", _box_corners(f["yaw"], S.NECK_C, S.NECK_HALF)), ("head", _box_corners(f["pitch"], S.HEAD_C, S.HEAD_HALF))]
    out += [("chassis", _box_corners(S.translate(0, 0, 0), c, h)) for c, h in S.CHASSIS]
    for side, s in (("l", 1), ("r", -1)):
        x0, x1 = s * S.ARM_X[0], s * S.ARM_X[1]
        c = ((x0 + x1) / 2, 0.0, sum(S.ARM_Z) / 2)
        h = (abs(x1 - x0) / 2, S.ARM_HALF_Y, (S.ARM_Z[1] - S.ARM_Z[0]) / 2)
        out.append((side, _box_corners(f[side], c, h)))
    return out


def pose_svg(pose, scale=2.0):
    """Front view (looking at the face: the robot's left is on the right) and side view from its right."""
    pose = {k: float(pose.get(k, 0)) for k in S.LIMITS}
    W, H, pad = 220, 180, 20
    views = [("front", lambda p: (p[0], p[1]), lambda p: p[2]), ("side, from its right (forward = right)", lambda p: (p[2], p[1]), lambda p: -p[0])]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * W * scale + 3 * pad}" height="{H * scale + 2 * pad + 30}" '
             f'font-family="sans-serif" font-size="12"><rect width="100%" height="100%" fill="#fff"/>']
    for i, (name, proj, depth) in enumerate(views):
        ox, oy = pad + i * (W * scale + pad), pad + H * scale
        tx = lambda p: (ox + (p[0] + W / 2) * scale, oy - p[1] * scale)
        parts.append(f'<line x1="{ox}" y1="{oy}" x2="{ox + W * scale}" y2="{oy}" stroke="#000"/>')
        parts.append(f'<text x="{ox}" y="{oy + 18}">{name}</text>')
        for kind, corners in sorted(_boxes(pose), key=lambda b: sum(depth(c) for c in b[1])):
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (tx(c) for c in _hull([tuple(round(v, 3) for v in proj(c)) for c in corners])))
            parts.append(f'<polygon points="{pts}" fill="{COLORS[kind]}" fill-opacity="0.75" stroke="#222"/>')
    label = "  ".join(f"{k}={v:g}" for k, v in pose.items())
    parts.append(f'<text x="{pad}" y="{H * scale + 2 * pad + 22}">{label}  (approximate geometry)</text></svg>')
    return "\n".join(parts)


def curves(rows, scale_x=40, h=90):
    """One strip per joint: commanded (thin grey) vs simulated (colour), beats as ticks."""
    keys = list(S.LIMITS)
    t_end = rows[-1][0]
    W = t_end * scale_x + 80
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{len(keys) * (h + 20) + 20}" '
             f'font-family="sans-serif" font-size="12"><rect width="100%" height="100%" fill="#fff"/>']
    for n, k in enumerate(keys):
        lo, hi = S.LIMITS[k]
        y0 = 10 + n * (h + 20)
        y = lambda v: y0 + h - (v - lo) / (hi - lo) * h
        parts.append(f'<text x="4" y="{y0 + 12}">{k}</text><text x="4" y="{y0 + 28}" fill="#888">{lo}..{hi}</text><rect x="60" y="{y0}" width="{t_end * scale_x:.0f}" height="{h}" fill="none" stroke="#ccc"/>')
        for b in range(dance.BEATS + 1):
            x = 60 + dance.beat_s(b) * scale_x
            parts.append(f'<line x1="{x:.1f}" y1="{y0 + h}" x2="{x:.1f}" y2="{y0 + h - 4}" stroke="#999"/>')
        for idx, color, width in ((1, "#aaa", 1), (2, COLORS.get(k, "#2a2"), 1.5)):
            pts = " ".join(f"{60 + row[0] * scale_x:.1f},{y(row[idx][k]):.1f}" for row in rows)
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"/>')
    parts.append(f'<text x="60" y="{len(keys) * (h + 20) + 14}">grey: commanded goal; colour: simulated servo; ticks: beats</text></svg>')
    return "\n".join(parts)
