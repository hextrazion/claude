#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" bike as a Roblox-ready asset.

Outputs (written next to this folder):
  MotorcycleTag_Bike.glb   main file for the Roblox 3D Importer / Blender
  MotorcycleTag_Bike.obj   same parts as OBJ objects (+ .mtl, palette.png)
  palette.png              64x64 flat-colour palette every part samples from

Units are Roblox studs. Y is up, the bike faces -Z (Roblox LookVector), X is right.
Every wheel is its own mesh, centred on its axle, so its bounding-box centre
(what Roblox uses as the MeshPart position) is exactly the rotation point.

Run:  python3 build_motorcycle.py          build files
      python3 build_motorcycle.py --check  build, then sweep the steering and
                                           report wheel/part clearances
Only needs numpy.
"""
import json
import math
import os
import struct
import sys
import zlib
from collections import defaultdict

import numpy as np

OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NAME = "MotorcycleTag_Bike"

X = np.array([1.0, 0.0, 0.0])
Y = np.array([0.0, 1.0, 0.0])
Z = np.array([0.0, 0.0, 1.0])

# ---------------------------------------------------------------- layout
RAKE = math.radians(24.0)                          # steering axis tilt from vertical
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])   # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward

FRONT_R, FRONT_HW = 1.30, 0.45                     # wheel radius, tire half-width
REAR_R, REAR_HW = 1.40, 0.58
FRONT_AXLE = np.array([0.0, FRONT_R, -2.70])
REAR_AXLE = np.array([0.0, REAR_R, 2.70])
SWINGARM_PIVOT = np.array([0.0, 1.55, 0.95])
STEER_LOCK = math.radians(30.0)                    # clearance is checked up to this


def steer_pt(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- palette
PALETTE = [
    ("paint", (242, 73, 46)),      # main body colour (recolour per player in Roblox)
    ("frame", (42, 46, 53)),
    ("seat", (26, 27, 31)),
    ("engine", (64, 69, 78)),
    ("chrome", (196, 202, 210)),
    ("gold", (240, 180, 60)),
    ("swingarm", (96, 102, 112)),
    ("tire", (32, 33, 36)),
    ("headlight", (234, 246, 255)),
    ("taillight", (255, 42, 58)),
    ("glass", (52, 62, 76)),
    ("grip", (16, 16, 18)),
]
COL = {name: i for i, (name, _) in enumerate(PALETTE)}
GRID = 4          # swatches per row
SWATCH = 16       # pixels per swatch


def palette_uv(i):
    return ((i % GRID) + 0.5) / GRID, ((i // GRID) + 0.5) / GRID


def palette_png():
    size = GRID * SWATCH
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            i = (py // SWATCH) * GRID + px // SWATCH
            row += bytes(PALETTE[i][1] if i < len(PALETTE) else (255, 0, 255))
        rows.append(bytes(row))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


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


# ---------------------------------------------------------------- parts
class Part:
    def __init__(self, name, pivot=(0, 0, 0), group="Body"):
        self.name, self.group = name, group
        self.pivot = np.asarray(pivot, float)
        self.verts, self.faces, self.colors = [], [], []
        self.count = 0

    def add(self, prim, color):
        verts, faces = prim[0], np.asarray(prim[1], int)
        cols = np.asarray(prim[2] if len(prim) > 2 else [color] * len(faces), int)
        verts = np.asarray(verts, float)
        # Orient each closed primitive outward (positive signed volume).
        c = verts.mean(0)
        a, b, d = verts[faces[:, 0]] - c, verts[faces[:, 1]] - c, verts[faces[:, 2]] - c
        if np.einsum("ij,ij->i", a, np.cross(b, d)).sum() < 0:
            faces = faces[:, [0, 2, 1]]
        n = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
        keep = np.linalg.norm(n, axis=1) > 1e-9
        self.verts.append(verts)
        self.faces.append(faces[keep] + self.count)
        self.colors.append(cols[keep])
        self.count += len(verts)
        return self

    def mirror_x(self, prim):
        v = np.asarray(prim[0], float).copy()
        v[:, 0] *= -1
        return (v, prim[1]) + tuple(prim[2:])

    def world(self):
        return np.concatenate(self.verts), np.concatenate(self.faces), np.concatenate(self.colors)


def build_parts():
    parts = []

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = Part(name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels: one mesh each, symmetric about the axle
    def wheel(name, center, R, hw, spokes=5):
        w = part(name, center, group="Wheel")
        f = R / 1.30
        prof = [  # closed (x, r) loop: tire outside, rim inside
            (-0.85 * hw, 0.73 * R), (-0.975 * hw, 0.80 * R), (-1.0 * hw, 0.87 * R), (-0.92 * hw, 0.94 * R),
            (-0.72 * hw, 0.985 * R), (-0.30 * hw, R), (0.30 * hw, R), (0.72 * hw, 0.985 * R),
            (0.92 * hw, 0.94 * R), (1.0 * hw, 0.87 * R), (0.975 * hw, 0.80 * R), (0.85 * hw, 0.73 * R),
            (0.80 * hw, 0.71 * R), (0.70 * hw, 0.635 * R), (-0.70 * hw, 0.635 * R), (-0.80 * hw, 0.71 * R),
        ]
        cols = [COL["tire"]] * 11 + [COL["gold"]] * 5
        w.add(lathe(center, prof, 32, cols), 0)
        hub_hw = 0.86 * hw
        w.add(lathe(center, [(-hub_hw, 0.0), (-hub_hw, 0.16 * f), (-0.75 * hub_hw, 0.25 * f), (0.75 * hub_hw, 0.25 * f),
                             (hub_hw, 0.16 * f), (hub_hw, 0.0)], 20, [COL["frame"]] * 6), 0)
        for s in range(spokes):
            th = 2 * math.pi * s / spokes
            dirv = math.cos(th) * Y + math.sin(th) * Z
            w.add(beam(center + 0.18 * f * dirv, center + 0.70 * R * dirv, 0.22 * f, 0.30 * hw,
                       0.15 * f, 0.26 * hw, c=0.03, up=X), COL["gold"])
        return w

    wheel("FrontWheel", FRONT_AXLE, FRONT_R, FRONT_HW)
    wheel("RearWheel", REAR_AXLE, REAR_R, REAR_HW)

    # ---------------- steering assembly (pivots at the front axle, which sits on the steering axis)
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.70
        fork.add(cylinder(steer_pt(x, -0.16, 0), steer_pt(x, 1.08, 0), 0.13, 12, 0.05), COL["gold"])
        fork.add(cylinder(steer_pt(x, 1.0, 0), steer_pt(x, 2.60, 0), 0.10, 12, 0.03), COL["chrome"])
        fork.add(cylinder(FRONT_AXLE + sx * 0.45 * X, FRONT_AXLE + sx * 0.86 * X, 0.08, 10, 0.02), COL["chrome"])
    steer_rot = np.column_stack([X, D, -FWD])  # local x, y=steering axis, z=back
    fork.add(cbox(steer_pt(0, 1.79, 0), (0.86, 0.08, 0.18), 0.05, steer_rot), COL["gold"])
    fork.add(cbox(steer_pt(0, 2.46, 0), (0.84, 0.07, 0.18), 0.05, steer_rot), COL["gold"])

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(steer_pt(sx * 0.28, 2.50, 0), steer_pt(sx * 0.28, 2.88, -0.02), 0.075, 10, 0.02), COL["frame"])
    bar_path = catmull([steer_pt(-0.86, 2.97, -0.20), steer_pt(-0.55, 2.92, -0.08), steer_pt(0, 2.88, 0),
                        steer_pt(0.55, 2.92, -0.08), steer_pt(0.86, 2.97, -0.20)], 4)
    bars.add(tube(bar_path, 0.07, 10, bevel=0.02), COL["frame"])
    for sx in (-1, 1):
        bars.add(cylinder(steer_pt(sx * 0.80, 2.965, -0.18), steer_pt(sx * 1.10, 3.00, -0.29), 0.105, 12, 0.03), COL["grip"])

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw = 0.54
    r0 = FRONT_R + 0.12
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.08), (fhw - 0.10, r0 + 0.16),
                                  (-fhw + 0.10, r0 + 0.16), (-fhw, r0 + 0.08)], 16,
                     [COL["paint"]] * 6, arc=(RAKE - math.radians(80), RAKE + math.radians(18))), 0)

    # cowl: shield shape in the (x, t) plane lofted forward along n
    shield = [(-0.68, 2.72), (-0.42, 2.92), (0.42, 2.92), (0.68, 2.72), (0.60, 1.98), (0.28, 1.78), (-0.28, 1.78), (-0.60, 1.98)]

    def shield_ring(n, scale, tc=2.32, shrink_t=1.0):
        return [steer_pt(x * scale, tc + (t - tc) * scale * shrink_t, n) for (x, t) in shield]

    cowl = part("HeadlightCowl", FRONT_AXLE, "Steer")
    cowl.add(loft([shield_ring(0.30, 0.94), shield_ring(0.36, 1.0), shield_ring(0.58, 0.94), shield_ring(0.72, 0.80),
                   shield_ring(0.76, 0.74)]), COL["paint"])

    lamp = part("Headlight", FRONT_AXLE, "Steer")
    lens = [(-0.44, 2.42), (-0.22, 2.55), (0.22, 2.55), (0.44, 2.42), (0.32, 2.16), (-0.32, 2.16)]
    lamp.add(loft([[steer_pt(x, t, 0.68) for x, t in lens],
                   [steer_pt(x, t, 0.82) for x, t in lens],
                   [steer_pt(x * 0.88, 2.36 + (t - 2.36) * 0.82, 0.86) for x, t in lens]]), COL["headlight"])

    screen = part("Windscreen", FRONT_AXLE, "Steer")
    plate = [steer_pt(-0.46, 2.84, 0.58), steer_pt(0.46, 2.84, 0.58), steer_pt(0.42, 3.12, 0.44),
             steer_pt(0.22, 3.34, 0.32), steer_pt(-0.22, 3.34, 0.32), steer_pt(-0.42, 3.12, 0.44)]
    pn = unit(np.cross(plate[1] - plate[0], plate[3] - plate[0]))
    screen.add(loft([[p - 0.025 * pn for p in plate], [p + 0.025 * pn for p in plate]]), COL["glass"])

    # ---------------- body (all welded to Frame in Roblox)
    frame = part("Frame")
    frame.add(cylinder(steer_pt(0, 1.93, 0), steer_pt(0, 2.34, 0), 0.20, 14, 0.03), COL["frame"])
    for sx in (-1, 1):
        frame.add(beam(steer_pt(sx * 0.16, 2.16, -0.12), (sx * 0.52, 2.40, 0.62), 0.16, 0.28, 0.14, 0.40, c=0.05), COL["frame"])
        frame.add(cbox((sx * 0.56, 1.84, 0.92), (0.07, 0.50, 0.22), 0.05), COL["frame"])
        frame.add(beam((sx * 0.50, 2.40, 1.00), (sx * 0.36, 2.94, 2.10), 0.10, 0.14, c=0.03), COL["frame"])
        frame.add(cylinder((sx * 0.56, 1.32, 0.62), (sx * 1.08, 1.32, 0.62), 0.09, 10, 0.03), COL["frame"])
    frame.add(beam(steer_pt(0, 2.06, -0.16), (0, 2.02, -0.98), 0.15, 0.20, c=0.04), COL["frame"])

    engine = part("Engine")
    engine.add(cbox((0, 1.30, -0.12), (0.46, 0.50, 0.84), 0.14), COL["engine"])
    tilt = rotation(X, math.radians(-20))  # lean the cylinder forward
    cyl_c = np.array([0, 2.12, -0.52])
    engine.add(cbox(cyl_c, (0.38, 0.40, 0.34), 0.08, tilt), COL["engine"])
    for k in (-0.14, 0.12):
        engine.add(cbox(cyl_c + tilt @ np.array([0, k, 0]), (0.43, 0.05, 0.39), 0.03, tilt), COL["chrome"])
    engine.add(cbox(cyl_c + tilt @ np.array([0, 0.48, -0.02]), (0.42, 0.13, 0.37), 0.07, tilt), COL["engine"])
    engine.add(cylinder((0.40, 1.26, 0.16), (0.58, 1.26, 0.16), 0.38, 16, 0.05), COL["chrome"])
    engine.add(cylinder((-0.40, 1.32, -0.36), (-0.57, 1.32, -0.36), 0.32, 16, 0.05), COL["chrome"])

    exhaust = part("Exhaust")
    header = catmull([(0.25, 2.30, -0.86), (0.36, 1.80, -1.06), (0.54, 1.10, -1.02), (0.60, 0.74, -0.62),
                      (0.64, 0.70, 0.10), (0.84, 0.86, 0.80), (1.12, 1.30, 1.36), (1.20, 1.62, 1.62)], 4)
    exhaust.add(tube(header, 0.12, 10, bevel=0.02), COL["chrome"])
    m0, m1 = np.array([1.20, 1.56, 1.56]), np.array([1.10, 2.46, 2.86])
    max_ = unit(m1 - m0)
    mu = unit(np.cross(Y, max_))
    mv = np.cross(max_, mu)
    exhaust.add(loft([ring(m0, mu, mv, superellipse(0.17, 0.15, 3, 12)),
                      ring(m0 + 0.20 * max_, mu, mv, superellipse(0.27, 0.25, 3, 12)),
                      ring(m1 - 0.10 * max_, mu, mv, superellipse(0.30, 0.28, 3, 12)),
                      ring(m1, mu, mv, superellipse(0.24, 0.22, 3, 12))]), COL["chrome"])
    exhaust.add(cylinder(m1 - 0.05 * max_, m1 + 0.06 * max_, 0.13, 12, 0.01), COL["frame"])

    swing = part("Swingarm")
    swing.add(cylinder(SWINGARM_PIVOT - 0.94 * X, SWINGARM_PIVOT + 0.94 * X, 0.12, 12, 0.03), COL["swingarm"])
    for sx in (-1, 1):
        swing.add(beam((sx * 0.84, 1.56, 0.84), (sx * 0.84, 1.40, 2.92), 0.16, 0.34, 0.16, 0.24, c=0.05), COL["swingarm"])
        swing.add(cylinder(REAR_AXLE + sx * 0.56 * X, REAR_AXLE + sx * 0.97 * X, 0.09, 10, 0.02), COL["chrome"])

    body = part("Bodywork")
    tank = [(-1.22, 0.18, 0.12, 3.36), (-1.10, 0.40, 0.26, 3.34), (-0.90, 0.64, 0.38, 3.30), (-0.42, 0.84, 0.44, 3.24),
            (0.04, 0.78, 0.38, 3.14), (0.34, 0.58, 0.27, 3.04), (0.44, 0.34, 0.12, 3.02)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 20)) for z, a, b, cy in tank]), COL["paint"])
    tail = [(0.90, 0.50, 0.24, 2.88), (1.60, 0.55, 0.28, 3.02), (2.30, 0.47, 0.26, 3.22), (2.85, 0.36, 0.22, 3.42),
            (3.16, 0.28, 0.17, 3.54), (3.22, 0.26, 0.16, 3.56)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.4, 16)) for z, a, b, cy in tail]), COL["paint"])
    def side_panel(profile, xs):
        c = np.mean(profile, axis=0)
        for sx in (-1, 1):
            body.add(loft([[np.array([sx * x, c[1] + (q - c[1]) * s, c[0] + (p - c[0]) * s]) for p, q in profile]
                           for x, s in xs]), COL["paint"])

    # radiator shrouds flanking the tank, and side covers under the seat
    side_panel([(-1.04, 3.22), (-0.56, 3.20), (-0.18, 2.76), (-0.40, 2.22), (-0.90, 2.12), (-1.20, 2.58)],
               ((0.44, 1.0), (0.86, 1.0), (0.94, 0.88)))
    side_panel([(0.30, 3.04), (1.50, 3.06), (1.86, 2.84), (1.50, 2.46), (0.52, 2.40), (0.22, 2.70)],
               ((0.36, 1.0), (0.60, 1.0), (0.66, 0.9)))

    seat = part("Seat")
    cushion = [(0.30, 0.48, 0.16, 3.12), (0.80, 0.58, 0.21, 3.16), (1.45, 0.56, 0.21, 3.24), (1.95, 0.46, 0.17, 3.36),
               (2.22, 0.30, 0.10, 3.44)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.0, 16)) for z, a, b, cy in cushion]), COL["seat"])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.56, z]), X, Y, superellipse(a, b, 2.4, 16))
                 for z, a, b in ((3.21, 0.24, 0.14), (3.28, 0.22, 0.13), (3.31, 0.17, 0.10))]), COL["taillight"])
    return parts


# ---------------------------------------------------------------- normals + export
def bake(part, smooth_deg=40.0):
    """Angle-based smoothing (hard edges above smooth_deg), then dedupe vertices.
    Returns local positions, normals, uvs, indices."""
    V, F, C = part.world()
    P = V[F]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fu = fn / np.linalg.norm(fn, axis=1, keepdims=True)
    key = {}
    gid = np.array([key.setdefault(tuple(k), len(key)) for k in np.round(V * 1e4).astype(np.int64)])
    G = gid[F]
    by_group = defaultdict(list)
    for f in range(len(F)):
        for c in range(3):
            by_group[G[f, c]].append(f)
    by_group = {g: np.array(fs) for g, fs in by_group.items()}
    cos_t = math.cos(math.radians(smooth_deg))
    out, pos, nor, uv, idx = {}, [], [], [], []
    for f in range(len(F)):
        u, v = palette_uv(C[f])
        for c in range(3):
            fs = by_group[G[f, c]]
            near = fs[fu[fs] @ fu[f] > cos_t]
            n = unit(fn[near].sum(0))
            k = (G[f, c], *np.round(n * 1e3).astype(int), C[f])
            if k not in out:
                out[k] = len(pos)
                pos.append(V[F[f, c]] - part.pivot)
                nor.append(n)
                uv.append((u, v))
            idx.append(out[k])
    return (np.array(pos, np.float32), np.array(nor, np.float32), np.array(uv, np.float32),
            np.array(idx, np.uint32))


def write_glb(path, parts, baked, png):
    blob = bytearray()
    views, accessors = [], []

    def view(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def accessor(arr, kind, ctype, target, minmax=False):
        a = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": kind}
        if minmax:
            a["min"] = arr.min(0).astype(float).tolist()
            a["max"] = arr.max(0).astype(float).tolist()
        accessors.append(a)
        return len(accessors) - 1

    meshes, nodes = [], []
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        small = idx.max() < 65535
        prim = {
            "attributes": {
                "POSITION": accessor(pos, "VEC3", 5126, 34962, True),
                "NORMAL": accessor(nor, "VEC3", 5126, 34962),
                "TEXCOORD_0": accessor(uv, "VEC2", 5126, 34962),
            },
            "indices": accessor(idx.astype(np.uint16 if small else np.uint32), "SCALAR", 5123 if small else 5125, 34963),
            "material": 0,
        }
        meshes.append({"name": p.name, "primitives": [prim]})
        nodes.append({"name": p.name, "mesh": len(meshes) - 1, "translation": p.pivot.tolist(),
                      "extras": {"group": p.group}})
    image_view = view(png)
    nodes.append({"name": NAME, "children": list(range(len(parts))),
                  "extras": {"units": "studs", "forward": "-Z", "up": "+Y",
                             "steeringRakeDeg": math.degrees(RAKE),
                             "steeringAxis": "through FrontWheel centre, tilted back by steeringRakeDeg"}})
    gltf = {
        "asset": {"version": "2.0", "generator": "Motorcycle Tag build_motorcycle.py"},
        "scene": 0,
        "scenes": [{"name": NAME, "nodes": [len(nodes) - 1]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [{"name": "MotorcyclePalette",
                       "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0,
                                                "roughnessFactor": 0.55}}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9728, "minFilter": 9728, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"name": "palette", "bufferView": image_view, "mimeType": "image/png"}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    while len(blob) % 4:
        blob.append(0)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        fh.write(struct.pack("<I4s", len(js), b"JSON") + js)
        fh.write(struct.pack("<I4s", len(blob), b"BIN\x00") + bytes(blob))


def write_obj(path, parts, baked):
    mtl = os.path.splitext(os.path.basename(path))[0] + ".mtl"
    lines = [f"# {NAME} - units: studs, +Y up, front faces -Z", f"mtllib {mtl}"]
    base = 1
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        lines.append(f"o {p.name}")
        w = pos + p.pivot
        lines += [f"v {a:.5f} {b:.5f} {c:.5f}" for a, b, c in w]
        lines += [f"vt {a:.5f} {1 - b:.5f}" for a, b in uv]
        lines += [f"vn {a:.4f} {b:.4f} {c:.4f}" for a, b, c in nor]
        lines.append("usemtl MotorcyclePalette")
        lines.append("s off")
        for t in idx.reshape(-1, 3) + base:
            lines.append("f " + " ".join(f"{i}/{i}/{i}" for i in t))
        base += len(pos)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(os.path.dirname(path), mtl), "w") as fh:
        fh.write("newmtl MotorcyclePalette\nKa 0 0 0\nKd 1 1 1\nKs 0.1 0.1 0.1\nNs 40\nd 1\nillum 2\nmap_Kd palette.png\n")


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


def check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=72):
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


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    baked = [bake(p) for p in parts]
    png = palette_png()
    with open(os.path.join(OUT_DIR, "palette.png"), "wb") as fh:
        fh.write(png)
    write_glb(os.path.join(OUT_DIR, NAME + ".glb"), parts, baked, png)
    write_obj(os.path.join(OUT_DIR, NAME + ".obj"), parts, baked)
    total_t = total_v = 0
    print(f"{'part':14s} {'group':6s} {'tris':>5s} {'verts':>5s}  size (studs)        pivot")
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        size = pos.max(0) - pos.min(0)
        ctr = (pos.max(0) + pos.min(0)) / 2
        total_t += len(idx) // 3
        total_v += len(pos)
        note = f"  bbox centre offset {np.abs(ctr).max():.4f}" if p.group == "Wheel" else ""
        print(f"{p.name:14s} {p.group:6s} {len(idx) // 3:5d} {len(pos):5d}  "
              f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}  {np.round(p.pivot, 3).tolist()}{note}")
    allv = np.concatenate([b[0] + p.pivot for p, b in zip(parts, baked)])
    ext = allv.max(0) - allv.min(0)
    print(f"total: {total_t} triangles, {total_v} vertices; bike {ext[0]:.2f} W x {ext[1]:.2f} H x {ext[2]:.2f} L studs")
    if "--check" in sys.argv:
        check(parts)


if __name__ == "__main__":
    main()
