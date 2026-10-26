"""Shared shape primitives and the clearance check for the Motorcycle Tag bikes.

Units are Roblox studs. Y is up, bikes face -Z (Roblox LookVector), X is right.
Every primitive returns (vertices, faces[, per-face colours]) as a closed surface.
"""
import math

import numpy as np

X = np.array([1.0, 0.0, 0.0])
Y = np.array([0.0, 1.0, 0.0])
Z = np.array([0.0, 0.0, 1.0])


# ---------------------------------------------------------------- primitives
def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def rotation(axis, angle):
    a = unit(axis)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(angle) * k + (1 - math.cos(angle)) * (k @ k)


def loft(sections, cap_start=True, cap_end=True):
    """Skin equal-length rings; caps are fans around the ring centroid (rings must be convex)."""
    sections = [np.asarray(s, float) for s in sections]
    n = len(sections[0])
    verts = list(np.concatenate(sections))
    faces = []
    for s in range(len(sections) - 1):
        for i in range(n):
            j = (i + 1) % n
            a, b, c, d = s * n + i, s * n + j, (s + 1) * n + j, (s + 1) * n + i
            faces += [(a, b, c), (a, c, d)]
    if cap_start:
        ci = len(verts)
        verts.append(sections[0].mean(0))
        faces += [(ci, (i + 1) % n, i) for i in range(n)]
    if cap_end:
        ci = len(verts)
        base = (len(sections) - 1) * n
        verts.append(sections[-1].mean(0))
        faces += [(ci, base + i, base + (i + 1) % n) for i in range(n)]
    return np.array(verts), faces


def ring(center, u, v, pts2d):
    return [center + p[0] * u + p[1] * v for p in pts2d]


def octagon(hw, hh, c):
    c = min(c, hw * 0.9, hh * 0.9)
    return [(hw, hh - c), (hw - c, hh), (-hw + c, hh), (-hw, hh - c),
            (-hw, -hh + c), (-hw + c, -hh), (hw - c, -hh), (hw, -hh + c)]


def superellipse(a, b, e=2.6, n=20):
    pts = []
    for i in range(n):
        p = 2 * math.pi * i / n
        cx, sy = math.cos(p), math.sin(p)
        pts.append((a * math.copysign(abs(cx) ** (2 / e), cx), b * math.copysign(abs(sy) ** (2 / e), sy)))
    return pts


def beam(p0, p1, w0, h0, w1=None, h1=None, c=0.04, up=Y):
    """Chamfered box swept from p0 to p1 (w across `up`, h along it), optionally tapered."""
    w1 = w0 if w1 is None else w1
    h1 = h0 if h1 is None else h1
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    ax = unit(p1 - p0)
    u = np.cross(up, ax)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(X, ax)
    u = unit(u)
    v = np.cross(ax, u)
    e = min(c, np.linalg.norm(p1 - p0) / 4)
    secs = [
        ring(p0, u, v, octagon(w0 / 2 - e, h0 / 2 - e, c * 0.5)),
        ring(p0 + e * ax, u, v, octagon(w0 / 2, h0 / 2, c)),
        ring(p1 - e * ax, u, v, octagon(w1 / 2, h1 / 2, c)),
        ring(p1, u, v, octagon(w1 / 2 - e, h1 / 2 - e, c * 0.5)),
    ]
    return loft(secs)


def cbox(center, half, c=0.06, rot=np.eye(3)):
    center = np.asarray(center, float)
    hz = rot @ np.array([0, 0, half[2]])
    return beam(center - hz, center + hz, 2 * half[0], 2 * half[1], c=c, up=rot @ Y)


def tube(path, radius, sides=10, bevel=0.0):
    """Tube along a polyline with parallel-transport frames. radius: float or per-point list."""
    path = np.asarray(path, float)
    radii = np.full(len(path), radius) if np.isscalar(radius) else np.asarray(radius, float)
    if bevel > 0:  # soften the two ends
        a0, a1 = unit(path[1] - path[0]), unit(path[-1] - path[-2])
        path = np.vstack([path[0], path[0] + bevel * a0, path[1:-1], path[-1] - bevel * a1, path[-1]]) \
            if len(path) > 2 else np.vstack([path[0], path[0] + bevel * a0, path[-1] - bevel * a1, path[-1]])
        radii = np.concatenate([[radii[0] * 0.78], radii, [radii[-1] * 0.78]])
    tangents = []
    for i in range(len(path)):
        a = path[max(i - 1, 0)]
        b = path[min(i + 1, len(path) - 1)]
        tangents.append(unit(b - a))
    t0 = tangents[0]
    nrm = np.cross(t0, X if abs(t0[0]) < 0.9 else Y)
    nrm = unit(nrm)
    secs = []
    for i, p in enumerate(path):
        t = tangents[i]
        nrm = unit(nrm - np.dot(nrm, t) * t)
        bin_ = np.cross(t, nrm)
        secs.append([p + radii[i] * (math.cos(2 * math.pi * k / sides) * nrm + math.sin(2 * math.pi * k / sides) * bin_)
                     for k in range(sides)])
    return loft(secs)


def cylinder(p0, p1, r, sides=12, bevel=0.03):
    return tube([p0, p1], r, sides, bevel=bevel)


def catmull(points, steps=4):
    pts = [np.asarray(p, float) for p in points]
    pts = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(steps):
            t = s / steps
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(pts[-2])
    return out


def lathe(center, profile, segments=32, colors=None, arc=None):
    """Revolve a closed (x, r) profile around the X axis through `center`.
    colors: per profile edge. arc: (theta0, theta1) for a capped partial revolve,
    with theta measured from +Y towards +Z."""
    center = np.asarray(center, float)
    k = len(profile)
    full = arc is None
    rings = segments if full else segments + 1
    verts = []
    for s in range(rings):
        th = 2 * math.pi * s / segments if full else arc[0] + (arc[1] - arc[0]) * s / segments
        cy, sz = math.cos(th), math.sin(th)
        for (x, r) in profile:
            verts.append(center + np.array([x, r * cy, r * sz]))
    faces, fcol = [], []
    for s in range(segments):
        s1 = (s + 1) % rings
        for i in range(k):
            j = (i + 1) % k
            a, b, c, d = s * k + i, s * k + j, s1 * k + j, s1 * k + i
            faces += [(a, c, b), (a, d, c)]
            col = colors[i] if colors is not None else 0
            fcol += [col, col]
    verts = list(verts)
    if not full:
        for s, flip in ((0, False), (segments, True)):
            ci = len(verts)
            verts.append(np.mean([verts[s * k + i] for i in range(k)], axis=0))
            for i in range(k):
                j = (i + 1) % k
                faces.append((ci, s * k + j, s * k + i) if flip else (ci, s * k + i, s * k + j))
                fcol.append(colors[0] if colors is not None else 0)
    return np.array(verts), faces, fcol


# ---------------------------------------------------------------- clearance check
def surface_samples(V, F, spacing=0.05, seed=1):
    rng = np.random.default_rng(seed)
    P = V[F]
    area = 0.5 * np.linalg.norm(np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0]), axis=1)
    n = np.maximum(1, np.ceil(area / spacing ** 2)).astype(int)
    tri = np.repeat(np.arange(len(F)), n)
    r1, r2 = rng.random(len(tri)), rng.random(len(tri))
    s = np.sqrt(r1)
    w = np.stack([1 - s, s * (1 - r2), s * r2], 1)
    return np.concatenate([np.einsum("ij,ijk->ik", w, P[tri]), V])


def nearest(a, b):
    """Distance from each point of a to the closest point of b (scipy if present, else numpy)."""
    try:
        from scipy.spatial import cKDTree
        return cKDTree(b).query(a)[0]
    except ImportError:
        bb = (b * b).sum(1)
        out = []
        for i in range(0, len(a), 1000):
            ch = a[i:i + 1000]
            d2 = (ch * ch).sum(1)[:, None] + bb[None, :] - 2 * ch @ b.T
            out.append(np.sqrt(np.maximum(d2.min(1), 0)))
        return np.concatenate(out)


def check(parts, axis, front, rear, lock_rad, spin_period=72):
    """Sweep the steering through the lock and spin the wheels; print the tightest gaps.
    spin_period: rotational symmetry of the wheels in degrees."""
    S = {p.name: surface_samples(*p.world()[:2]) for p in parts}
    group = {p.name: p.group for p in parts}
    steer = [n for n in S if group[n] == "Steer"] + ["FrontWheel"]
    body = [n for n in S if group[n] == "Body"] + ["RearWheel"]
    lock = round(math.degrees(lock_rad))
    gaps = {}
    for s_name in steer:
        for ang in range(-lock, lock + 1, 3):
            R = rotation(axis, math.radians(ang))
            pts = (S[s_name] - front) @ R.T + front
            for b_name in body:
                d = nearest(pts, S[b_name]).min()
                if d < gaps.get((s_name, b_name), (np.inf,))[0]:
                    gaps[(s_name, b_name)] = (d, ang)
    print(f"Steering sweep +/-{lock} deg, tightest steering-part/body gaps:")
    for (a, b), (d, ang) in sorted(gaps.items(), key=lambda kv: kv[1][0])[:6]:
        print(f"  {a:14s} vs {b:12s} {d:.3f} studs (at {ang:+d} deg)")
    print("Spinning wheels vs the parts around them (tightest 4 each):")
    for wname, center, others in (("FrontWheel", front, steer[:-1]), ("RearWheel", rear, body[:-1])):
        spin = {o: min(nearest((S[wname] - center) @ rotation(X, math.radians(a)).T + center, S[o]).min()
                       for a in range(0, spin_period, 6)) for o in others}
        for o, lo in sorted(spin.items(), key=lambda kv: kv[1])[:4]:
            print(f"  {wname:14s} vs {o:12s} {lo:.3f} studs")
