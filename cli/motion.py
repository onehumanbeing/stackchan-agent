"""Smooth joint curves for the dance: keyframes -> a curve through them, streamed to the servos many times a second.

Point-to-point moves stop at every keyframe (the servo brakes, then starts again), which looks mechanical.
A curve keeps the joint moving through its keyframes, like a person does; a keyframe that repeats the value
before it is still a hold.  Monotone cubic (Fritsch-Carlson): no overshoot past a keyframe, so limits hold.
"""


class Curve:
    def __init__(self, points):
        """points: [(t, value)] sorted by t, at least one."""
        self.t = [p[0] for p in points]
        self.v = [p[1] for p in points]
        n = len(points)
        d = [(self.v[i + 1] - self.v[i]) / (self.t[i + 1] - self.t[i]) for i in range(n - 1)]
        m = [0.0] * n                              # tangents
        for i in range(1, n - 1):
            if d[i - 1] * d[i] > 0:                # same direction on both sides: flow through
                m[i] = 2 / (1 / d[i - 1] + 1 / d[i])
        self.m = m

    def __call__(self, t):
        ts, vs = self.t, self.v
        if t <= ts[0]:
            return vs[0]
        if t >= ts[-1]:
            return vs[-1]
        i = max(k for k in range(len(ts) - 1) if ts[k] <= t)
        h = ts[i + 1] - ts[i]
        s = (t - ts[i]) / h
        h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
        return h00 * vs[i] + h10 * h * self.m[i] + h01 * vs[i + 1] + h11 * h * self.m[i + 1]

    def speed(self, t, dt=0.01):
        """|d value / dt| (units per second)."""
        return abs(self(t + dt) - self(t - dt)) / (2 * dt)
