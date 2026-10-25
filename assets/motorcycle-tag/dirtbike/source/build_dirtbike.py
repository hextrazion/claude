#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" dirt bike with a skinnable UV layout.

Outputs (written to the dirtbike/ folder):
  MotorcycleTag_DirtBike.glb   main file, with the Blaze skin embedded
  MotorcycleTag_DirtBike.obj   same parts as OBJ objects (+ .mtl -> skins/blaze.png)
  skin_template.png            1024x1024 guide: every paintable area, labelled
  uv_overlay.png               transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png             example skins; a skin is just a different texture

Same conventions as the street bike: studs, +Y up, front faces -Z, each wheel its own
mesh centred on its axle, and the steering axis passes through the front wheel centre.

The texture has two zones:
  panels (top)  plastics projected flat, as seen from outside the bike, so numbers and
                stripes painted upright read correctly on the model
  blocks (bottom two rows)  64x64 solid swatches; every mechanical part samples the
                centre of its block, so filling a block recolours that part

Run:  python3 build_dirtbike.py          build everything
      python3 build_dirtbike.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import json
import math
import os
import struct
import sys
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
import build_motorcycle as kit  # noqa: E402  (shared primitives from the street bike)
from build_motorcycle import X, Y, beam, catmull, cbox, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_DirtBike"
TEX = 1024

# ---------------------------------------------------------------- layout
RAKE = math.radians(27.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.38, 0.34    # radius includes the knobs
REAR_R, REAR_HW = 1.36, 0.50
FRONT_AXLE = np.array([0.0, FRONT_R, -2.85])
REAR_AXLE = np.array([0.0, REAR_R, 2.65])
PIVOT = np.array([0.0, 1.62, 0.80])
STEER_LOCK = math.radians(30.0)


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


def steer_coords(p):
    q = np.asarray(p) - FRONT_AXLE
    return q @ X, q @ D, q @ FWD


# ---------------------------------------------------------------- texture blocks (solid colours)
BLOCKS = [  # name, Blaze colour
    ("TIRE", (34, 34, 37)), ("RIM", (30, 30, 34)), ("HUB", (190, 196, 204)), ("SPOKES", (200, 205, 212)),
    ("BRAKE", (150, 156, 164)), ("FORK_UPPER", (238, 176, 52)), ("FORK_LOWER", (205, 212, 220)),
    ("CLAMPS", (238, 120, 34)), ("FORK_GUARDS", (245, 245, 245)), ("BARS", (40, 42, 46)), ("GRIPS", (20, 20, 22)),
    ("BAR_PAD", (255, 92, 20)), ("HEADLIGHT", (235, 246, 255)), ("TAILLIGHT", (255, 40, 52)),
    ("FRAME", (60, 64, 72)), ("ENGINE", (70, 74, 82)), ("ENGINE_ACCENT", (238, 120, 34)), ("EXHAUST", (198, 204, 212)),
    ("MUFFLER", (52, 55, 60)), ("SWINGARM", (186, 192, 200)), ("SHOCK", (55, 58, 64)), ("SPRING", (255, 92, 20)),
    ("SEAT_SIDE", (28, 28, 31)), ("PLASTIC", (245, 245, 245)), ("TANK", (245, 245, 245)), ("SKID", (52, 55, 60)),
    ("PEGS", (150, 156, 164)),
]
BLOCK = {name: i for i, (name, _) in enumerate(BLOCKS)}
BLOCK_PX = 64
BLOCK_ROWS = 2
PANEL_H = TEX - BLOCK_ROWS * BLOCK_PX


def block_rect(i):
    per_row = TEX // BLOCK_PX
    return (i % per_row) * BLOCK_PX, PANEL_H + (i // per_row) * BLOCK_PX, BLOCK_PX, BLOCK_PX


def block_uv(i):
    x, y, w, h = block_rect(i)
    return (x + w / 2) / TEX, (y + h / 2) / TEX


# ---------------------------------------------------------------- texture panels (projected charts)
class Chart:
    """A paintable panel. proj maps a 3D point to (right, up) as seen by someone looking at that surface."""

    def __init__(self, name, label, pred, proj, front):
        self.name, self.label, self.pred, self.proj, self.front = name, label, pred, proj, front
        self.points = []
        self.tris = []      # (3, 2) projected triangles, for the template wireframe
        self.rect = None

    def bounds(self):
        p = np.array(self.points)
        return p.min(0), p.max(0)

    def to_px(self, sx, sy):
        (mn, mx), (x, y, w, h), s = self.bounds(), self.rect, self.scale
        return x + (sx - mn[0]) * s, y + (mx[1] - sy) * s

    def frac_to_px(self, ff, fy):
        """ff: 0 = rear/bottom edge .. 1 = edge nearest the bike's front (or top for top-down panels)."""
        mn, mx = self.bounds()
        fx = ff if self.front in ("right", "up") else 1 - ff
        return self.to_px(mn[0] + fx * (mx[0] - mn[0]), mn[1] + fy * (mx[1] - mn[1]))


def side_chart(name, label, sign, min_dot=0.4):
    # Viewed from the right (+X) the bike's front (-Z) is on the viewer's right; from the left, on the left.
    return Chart(name, label, lambda n: n[0] * sign > min_dot, lambda p: (-sign * p[2], p[1]),
                 "right" if sign > 0 else "left")


def top_chart(name, label, min_dot=0.4):
    # Viewed from above with the front at the top of the image.
    return Chart(name, label, lambda n: n[1] > min_dot, lambda p: (p[0], -p[2]), "up")


CHARTS = {
    "SHROUD_R": side_chart("SHROUD_R", "Shroud right", 1),
    "SHROUD_L": side_chart("SHROUD_L", "Shroud left", -1),
    "SIDEPLATE_R": side_chart("SIDEPLATE_R", "Number plate right", 1),
    "SIDEPLATE_L": side_chart("SIDEPLATE_L", "Number plate left", -1),
    "FRONT_PLATE": Chart("FRONT_PLATE", "Front number plate", lambda n: n @ FWD > 0.4,
                         lambda p: (-steer_coords(p)[0], steer_coords(p)[1]), "up"),
    "FRONT_FENDER": Chart("FRONT_FENDER", "Front fender (top)", lambda n: n @ D > 0.35,
                          lambda p: (steer_coords(p)[0], steer_coords(p)[2]), "up"),
    "REAR_FENDER": top_chart("REAR_FENDER", "Rear fender (top)"),
    "SEAT": top_chart("SEAT", "Seat (top)", 0.5),
    "SWINGARM_R": side_chart("SWINGARM_R", "Swingarm right", 1, 0.6),
    "SWINGARM_L": side_chart("SWINGARM_L", "Swingarm left", -1, 0.6),
}


# ---------------------------------------------------------------- parts
class SkinPart:
    def __init__(self, name, pivot=(0, 0, 0), group="Body"):
        self.name, self.group = name, group
        self.pivot = np.asarray(pivot, float)
        self.verts, self.faces, self.kinds, self.raw = [], [], [], []
        self.count = 0

    def add(self, prim, block, charts=()):
        """block: block name, or a list of names indexed by a lathe's per-face colours."""
        verts, faces = np.asarray(prim[0], float), np.asarray(prim[1], int)
        if isinstance(block, str):
            fblocks = np.full(len(faces), BLOCK[block])
        else:
            fblocks = np.array([BLOCK[block[k]] for k in prim[2]])
        c = verts.mean(0)
        a, b, d = verts[faces[:, 0]] - c, verts[faces[:, 1]] - c, verts[faces[:, 2]] - c
        if np.einsum("ij,ij->i", a, np.cross(b, d)).sum() < 0:
            faces = faces[:, [0, 2, 1]]
        P = verts[faces]
        fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        area = np.linalg.norm(fn, axis=1)
        keep = area > 1e-9
        faces, P, fn, fblocks = faces[keep], P[keep], fn[keep] / area[keep, None], fblocks[keep]
        for f in range(len(faces)):
            for ch in charts:
                if ch.pred(fn[f]):
                    tri = np.array([ch.proj(p) for p in P[f]])
                    ch.points.extend(tri)
                    ch.tris.append(tri)
                    self.kinds.append(ch)
                    self.raw.append(tri)
                    break
            else:
                self.kinds.append(int(fblocks[f]))
                self.raw.append(None)
        self.verts.append(verts)
        self.faces.append(faces + self.count)
        self.count += len(verts)
        return self

    def world(self):
        return np.concatenate(self.verts), np.concatenate(self.faces)

    def corner_uvs(self):
        out = np.zeros((len(self.kinds), 3, 2))
        for f, (kind, raw) in enumerate(zip(self.kinds, self.raw)):
            if isinstance(kind, Chart):
                out[f] = [np.array(kind.to_px(*p)) / TEX for p in raw]
            else:
                out[f] = block_uv(kind)
        return out


def knobby_wheel(part, center, R, hw, spokes=12, disc=False):
    base = R - 0.08
    prof = [  # closed (x, r) loop: tire carcass outside, rim inside
        (-0.82 * hw, 0.70 * base), (-0.96 * hw, 0.78 * base), (-1.0 * hw, 0.87 * base), (-0.90 * hw, 0.95 * base),
        (-0.55 * hw, base), (0.55 * hw, base), (0.90 * hw, 0.95 * base), (1.0 * hw, 0.87 * base),
        (0.96 * hw, 0.78 * base), (0.82 * hw, 0.70 * base),
        (0.78 * hw, 0.68 * base), (0.70 * hw, 0.62 * base), (-0.70 * hw, 0.62 * base), (-0.78 * hw, 0.68 * base),
    ]
    part.add(lathe(center, prof, 32, [0] * 10 + [1] * (len(prof) - 10)), ["TIRE", "RIM"])
    # Two staggered rows of chunky knobs, an even count so the bounding box stays centred on the axle.
    count = 20
    for row, xoff in ((0, -0.42 * hw), (1, 0.42 * hw)):
        for k in range(count):
            th = 2 * math.pi * (k + 0.5 * row) / count
            radial = math.cos(th) * Y + math.sin(th) * np.array([0, 0, 1.0])
            tang = np.cross(X, radial)
            c0 = center + xoff * X + (base - 0.03) * radial
            c1 = center + xoff * X + R * radial
            sec = [(0.50 * hw, 0.13), (-0.50 * hw, 0.13), (-0.50 * hw, -0.13), (0.50 * hw, -0.13)]
            part.add(loft([ring(c0, X, tang, sec), ring(c1, X, tang, [(a * 0.9, b * 0.85) for a, b in sec])]), "TIRE")
    hub_hw = 0.86 * hw
    part.add(lathe(center, [(-hub_hw, 0.0), (-hub_hw, 0.13), (-0.7 * hub_hw, 0.20), (0.7 * hub_hw, 0.20), (hub_hw, 0.13),
                            (hub_hw, 0.0)], 16), "HUB")
    for s in range(spokes):
        th = 2 * math.pi * s / spokes
        radial = math.cos(th) * Y + math.sin(th) * np.array([0, 0, 1.0])
        side = (0.55 if s % 2 else -0.55) * hub_hw
        part.add(beam(center + side * X + 0.16 * radial, center + 0.64 * base * radial, 0.07, 0.07, c=0.015, up=X), "SPOKES")
    if disc:
        part.add(lathe(center, [(-0.97 * hw - 0.0, 0.16), (-0.97 * hw, 0.44), (-0.88 * hw, 0.44), (-0.88 * hw, 0.16)], 20),
                 "BRAKE")
        part.add(lathe(center, [(0.88 * hw, 0.16), (0.88 * hw, 0.44), (0.97 * hw, 0.44), (0.97 * hw, 0.16)], 20), "BRAKE")


def side_panel(part, profile, xs, block, chart_r, chart_l):
    """Prism from a convex side-view profile [(z, y)], with sections [(x, scale)] going outward."""
    c = np.mean(profile, axis=0)
    for sx, chart in ((1, chart_r), (-1, chart_l)):
        part.add(loft([[np.array([sx * x, c[1] + (y - c[1]) * s, c[0] + (z - c[0]) * s]) for z, y in profile]
                       for x, s in xs]), block, [chart])


def build_parts():
    parts = []

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels
    knobby_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW, disc=True)
    knobby_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW)

    # ---------------- steering assembly
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.52
        fork.add(cylinder(sp(x, -0.05, 0), sp(x, 1.60, 0), 0.095, 12, 0.02), "FORK_LOWER")
        fork.add(cbox(sp(x, 0.0, 0.02), (0.11, 0.17, 0.14), 0.04, STEER_ROT), "FORK_LOWER")
        fork.add(cylinder(sp(x, 1.50, 0), sp(x, 3.26, 0), 0.135, 12, 0.03), "FORK_UPPER")
        fork.add(cbox(sp(sx * 0.55, 0.88, 0.12), (0.10, 0.52, 0.06), 0.04, STEER_ROT), "FORK_GUARDS")
        fork.add(cylinder(FRONT_AXLE + sx * 0.37 * X, FRONT_AXLE + sx * 0.66 * X, 0.07, 10, 0.02), "FORK_LOWER")
    fork.add(cbox(sp(0, 2.55, 0), (0.70, 0.09, 0.20), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 3.15, 0), (0.68, 0.07, 0.20), 0.05, STEER_ROT), "CLAMPS")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.25, 3.18, 0), sp(sx * 0.25, 3.44, -0.04), 0.07, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.88, 3.585, -0.22), sp(sx * 1.16, 3.63, -0.33), 0.10, 12, 0.03), "GRIPS")
    bars.add(tube(catmull([sp(-0.92, 3.59, -0.23), sp(-0.62, 3.53, -0.13), sp(-0.25, 3.46, -0.05), sp(0.25, 3.46, -0.05),
                           sp(0.62, 3.53, -0.13), sp(0.92, 3.59, -0.23)], 4), 0.065, 10, bevel=0.02), "BARS")
    bars.add(cbox(sp(0, 3.50, -0.05), (0.30, 0.08, 0.09), 0.05, STEER_ROT), "BAR_PAD")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    spine = [(-0.35, 2.36, 0.32), (-0.05, 2.42, 0.40), (0.35, 2.42, 0.43), (0.80, 2.34, 0.40), (1.15, 2.22, 0.32),
             (1.38, 2.12, 0.22)]  # (n, t, half width)
    fender.add(loft([[sp(x * hw, t + dt, n) for x, dt in ((-1, 0), (-0.8, 0.07), (0.8, 0.07), (1, 0), (0.8, -0.03), (-0.8, -0.03))]
                     for n, t, hw in spine]), "PLASTIC", [CHARTS["FRONT_FENDER"]])

    plate = part("FrontPlate", FRONT_AXLE, "Steer")
    shield = [(-0.48, 3.30), (-0.30, 3.42), (0.30, 3.42), (0.48, 3.30), (0.44, 2.70), (0.20, 2.52), (-0.20, 2.52), (-0.44, 2.70)]
    tc = 2.97
    plate.add(loft([[sp(x * s, tc + (t - tc) * s, n) for x, t in shield]
                    for n, s in ((0.30, 0.94), (0.33, 1.0), (0.42, 1.0), (0.45, 0.94))]), "PLASTIC", [CHARTS["FRONT_PLATE"]])

    lamp = part("Headlight", FRONT_AXLE, "Steer")
    lens = [(-0.24, 2.80), (-0.12, 2.86), (0.12, 2.86), (0.24, 2.80), (0.18, 2.64), (-0.18, 2.64)]
    lamp.add(loft([[sp(x, t, 0.43) for x, t in lens], [sp(x, t, 0.50) for x, t in lens],
                   [sp(x * 0.85, 2.76 + (t - 2.76) * 0.8, 0.53) for x, t in lens]]), "HEADLIGHT")

    # ---------------- body
    frame = part("Frame")
    frame.add(cylinder(sp(0, 2.69, 0), sp(0, 3.03, 0), 0.19, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        frame.add(beam(sp(sx * 0.14, 2.86, -0.12), (sx * 0.44, 2.55, 0.62), 0.13, 0.24, 0.13, 0.30, c=0.04), "FRAME")
        frame.add(cbox((sx * 0.46, 1.72, 0.80), (0.07, 0.42, 0.20), 0.04), "FRAME")
        frame.add(beam((sx * 0.42, 2.50, 0.75), (sx * 0.30, 3.30, 2.30), 0.09, 0.12, c=0.03), "FRAME")
        frame.add(beam((sx * 0.44, 1.95, 0.92), (sx * 0.30, 3.22, 2.05), 0.08, 0.10, c=0.03), "FRAME")
        frame.add(cylinder((sx * 0.48, 1.22, 0.58), (sx * 0.92, 1.22, 0.58), 0.085, 10, 0.03), "PEGS")
    # The down tube heads back before it drops, clearing the lower clamp and fender at full lock.
    frame.add(beam(sp(0, 2.86, -0.12), sp(0, 2.72, -0.66), 0.15, 0.18, c=0.04), "FRAME")
    frame.add(beam(sp(0, 2.72, -0.58), (0, 1.15, -1.02), 0.15, 0.18, c=0.04), "FRAME")
    frame.add(cbox((0, 0.80, -0.40), (0.36, 0.05, 0.62), 0.03), "SKID")

    engine = part("Engine")
    engine.add(cbox((0, 1.30, -0.32), (0.36, 0.44, 0.62), 0.12), "ENGINE")
    tilt = rotation(X, math.radians(-12))
    cyl_c = np.array([0, 2.06, -0.52])
    engine.add(cbox(cyl_c, (0.30, 0.36, 0.30), 0.07, tilt), "ENGINE")
    for k in (-0.12, 0.12):
        engine.add(cbox(cyl_c + tilt @ np.array([0, k, 0]), (0.35, 0.045, 0.35), 0.03, tilt), "ENGINE_ACCENT")
    engine.add(cbox(cyl_c + tilt @ np.array([0, 0.44, 0]), (0.33, 0.11, 0.33), 0.06, tilt), "ENGINE")
    engine.add(cylinder((0.30, 1.28, 0.0), (0.46, 1.28, 0.0), 0.34, 16, 0.05), "ENGINE_ACCENT")
    engine.add(cylinder((-0.30, 1.30, -0.45), (-0.46, 1.30, -0.45), 0.28, 16, 0.05), "ENGINE_ACCENT")

    exhaust = part("Exhaust")
    m0, m1 = np.array([0.78, 2.12, 0.95]), np.array([0.74, 3.06, 2.78])
    exhaust.add(tube(catmull([(0.18, 2.15, -0.92), (0.38, 1.75, -1.12), (0.60, 1.52, -0.80), (0.68, 1.70, -0.10),
                              (0.74, 1.96, 0.55), m0 + 0.05 * unit(m1 - m0)], 4), 0.10, 10, bevel=0.02), "EXHAUST")
    ax = unit(m1 - m0)
    u = unit(np.cross(Y, ax))
    v = np.cross(ax, u)
    exhaust.add(loft([ring(m0, u, v, superellipse(0.15, 0.14, 3, 12)), ring(m0 + 0.22 * ax, u, v, superellipse(0.21, 0.20, 3, 12)),
                      ring(m1 - 0.12 * ax, u, v, superellipse(0.22, 0.21, 3, 12)), ring(m1, u, v, superellipse(0.17, 0.16, 3, 12))]),
                "MUFFLER")
    exhaust.add(cylinder(m1 - 0.05 * ax, m1 + 0.07 * ax, 0.09, 10, 0.01), "EXHAUST")

    swing = part("Swingarm")
    swing.add(cylinder(PIVOT - 0.82 * X, PIVOT + 0.82 * X, 0.11, 12, 0.03), "SWINGARM")
    for sx in (-1, 1):
        swing.add(beam((sx * 0.72, 1.62, 0.70), (sx * 0.72, 1.36, 2.88), 0.15, 0.30, 0.15, 0.22, c=0.04), "SWINGARM",
                  [CHARTS["SWINGARM_R" if sx > 0 else "SWINGARM_L"]])
        swing.add(cylinder(REAR_AXLE + sx * 0.50 * X, REAR_AXLE + sx * 0.86 * X, 0.08, 10, 0.02), "SWINGARM")
    shock0, shock1 = np.array([0, 2.80, 0.50]), np.array([0, 1.62, 1.02])
    swing.add(cylinder(shock0, shock1, 0.08, 10, 0.02), "SHOCK")
    swing.add(cylinder(shock0 + 0.2 * (shock1 - shock0), shock0 + 0.8 * (shock1 - shock0), 0.15, 12, 0.02), "SPRING")

    body = part("Bodywork")
    tank = [(-1.20, 0.20, 0.14, 3.38), (-1.05, 0.34, 0.24, 3.38), (-0.70, 0.40, 0.30, 3.35), (-0.20, 0.38, 0.28, 3.30),
            (0.10, 0.28, 0.18, 3.28)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 16)) for z, a, b, cy in tank]), "TANK")
    side_panel(body, [(-1.02, 3.58), (-0.50, 3.72), (0.15, 3.60), (-0.05, 2.85), (-0.70, 2.38), (-1.40, 2.62)],
               ((0.36, 1.0), (0.58, 1.0), (0.64, 0.92)), "PLASTIC", CHARTS["SHROUD_R"], CHARTS["SHROUD_L"])
    side_panel(body, [(0.45, 3.52), (1.80, 3.60), (2.12, 3.38), (1.75, 2.62), (0.80, 2.48), (0.40, 2.95)],
               ((0.36, 1.0), (0.48, 1.0), (0.53, 0.93)), "PLASTIC", CHARTS["SIDEPLATE_R"], CHARTS["SIDEPLATE_L"])
    rear = [(1.55, 0.44, 3.50), (2.10, 0.48, 3.56), (2.80, 0.42, 3.68), (3.40, 0.32, 3.82), (3.70, 0.24, 3.90)]
    body.add(loft([[np.array([x * hw, y - 0.06 + dy, z]) for x, dy in ((-1, 0), (-0.8, 0.06), (0.8, 0.06), (1, 0), (0.85, -0.06),
                                                                         (-0.85, -0.06))] for z, hw, y in rear]),
             "PLASTIC", [CHARTS["REAR_FENDER"]])

    seat = part("Seat")
    cushion = [(-0.60, 0.22, 0.06, 3.62), (-0.45, 0.32, 0.09, 3.66), (0.0, 0.38, 0.11, 3.68), (1.0, 0.42, 0.12, 3.68),
               (1.9, 0.40, 0.11, 3.66), (2.25, 0.30, 0.08, 3.64), (2.40, 0.16, 0.05, 3.62)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.2, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.85, z]), X, Y, superellipse(a, b, 2.4, 12))
                 for z, a, b in ((3.66, 0.15, 0.05), (3.74, 0.14, 0.045), (3.77, 0.11, 0.035))]), "TAILLIGHT")
    return parts


# ---------------------------------------------------------------- atlas packing
def pack(charts, pad=14, label=22):
    """Skyline-pack the panels into the top zone at the largest uniform texel density that fits.
    Each panel keeps `label` pixels above it for its name on the template."""
    items = sorted(charts, key=lambda c: -(c.bounds()[1][1] - c.bounds()[0][1]))

    def place(scale):
        sky = np.full(TEX, pad + label, float)   # lowest free y per pixel column
        rects = {}
        for c in items:
            mn, mx = c.bounds()
            w, h = (mx - mn) * scale
            span = int(math.ceil(w)) + pad
            best = None
            for x in range(pad, TEX - span + 1, 4):
                y = sky[x:x + span].max()
                if best is None or y < best[1]:
                    best = (x, y)
            if best is None or best[1] + h + pad > PANEL_H:
                return None
            x, y = best
            rects[c.name] = (x, y, w, h)
            sky[x:x + span] = y + h + pad + label
        return rects

    lo, hi = 10.0, 1000.0
    for _ in range(30):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if place(mid) else (lo, mid)
    rects = place(lo)
    for c in charts:
        c.rect, c.scale = rects[c.name], lo
    return lo


# ---------------------------------------------------------------- images
def font(size, bold=True):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def text_color(rgb):
    return (20, 20, 22) if sum(rgb) > 380 else (245, 245, 245)


def draw_wire(draw, chart, color, width=1):
    for tri in chart.tris:
        pts = [chart.to_px(*p) for p in tri]
        draw.line(pts + [pts[0]], fill=color, width=width)


def write_template(charts, path_template, path_overlay):
    img = Image.new("RGB", (TEX, TEX), (43, 45, 49))
    ov = Image.new("RGBA", (TEX, TEX), (0, 0, 0, 0))
    d, do = ImageDraw.Draw(img), ImageDraw.Draw(ov)
    for c in charts.values():
        x, y, w, h = c.rect
        d.rectangle([x - 6, y - 6, x + w + 6, y + h + 6], fill=(70, 74, 80))
        for tri in c.tris:
            d.polygon([c.to_px(*p) for p in tri], fill=(232, 234, 238))
        draw_wire(d, c, (175, 180, 188))
        draw_wire(do, c, (255, 255, 255, 140))
        do.rectangle([x - 6, y - 6, x + w + 6, y + h + 6], outline=(255, 210, 0, 200), width=2)
        arrow = {"right": "FRONT \u2192", "left": "\u2190 FRONT", "up": "\u2191 FRONT"}[c.front]
        if c.name == "FRONT_PLATE":
            arrow = "\u2191 UP"
        d.text((x, y - 4), c.label, fill=(255, 210, 0), font=font(15), anchor="lb")
        d.text((x + w / 2, y + h / 2), arrow, fill=(110, 116, 126), font=font(14), anchor="mm")
    for i, (name, rgb) in enumerate(BLOCKS):
        x, y, w, h = block_rect(i)
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=rgb, outline=(20, 20, 22))
        do.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 210, 0, 160))
        label = name.replace("_", "\n", 1)
        d.multiline_text((x + w / 2, y + h / 2), label, fill=text_color(rgb), font=font(9), anchor="mm", align="center")
    img.save(path_template)
    ov.save(path_overlay)


SKINS = {
    "blaze": dict(primary=(255, 92, 20), secondary=(250, 250, 250), accent=(24, 24, 28), plate=(250, 250, 250),
                  number="07", number_color=(24, 24, 28), seat=(26, 26, 30), seat_rib=(60, 60, 66), swingarm=(186, 192, 200),
                  blocks={}),
    "toxic": dict(primary=(150, 230, 30), secondary=(22, 22, 26), accent=(160, 60, 255), plate=(22, 22, 26),
                  number="13", number_color=(150, 230, 30), seat=(22, 22, 26), seat_rib=(150, 230, 30), swingarm=(40, 42, 48),
                  blocks=dict(RIM=(150, 230, 30), CLAMPS=(160, 60, 255), BAR_PAD=(160, 60, 255), SPRING=(150, 230, 30),
                              FORK_UPPER=(40, 42, 48), ENGINE_ACCENT=(150, 230, 30), PLASTIC=(22, 22, 26), TANK=(22, 22, 26),
                              FORK_GUARDS=(22, 22, 26))),
    "frost": dict(primary=(240, 246, 252), secondary=(40, 190, 255), accent=(20, 60, 140), plate=(20, 60, 140),
                  number="21", number_color=(240, 246, 252), seat=(20, 60, 140), seat_rib=(40, 190, 255), swingarm=(210, 216, 224),
                  blocks=dict(RIM=(40, 190, 255), CLAMPS=(40, 190, 255), BAR_PAD=(20, 60, 140), SPRING=(40, 190, 255),
                              FORK_UPPER=(210, 216, 224), ENGINE_ACCENT=(40, 190, 255), PLASTIC=(240, 246, 252),
                              TANK=(240, 246, 252), FORK_GUARDS=(240, 246, 252), FRAME=(40, 190, 255))),
    "midnight": dict(primary=(26, 24, 34), secondary=(255, 40, 140), accent=(120, 70, 255), plate=(255, 40, 140),
                     number="99", number_color=(26, 24, 34), seat=(18, 18, 22), seat_rib=(255, 40, 140), swingarm=(30, 30, 36),
                     blocks=dict(RIM=(255, 40, 140), CLAMPS=(120, 70, 255), BAR_PAD=(255, 40, 140), SPRING=(255, 40, 140),
                                 FORK_UPPER=(30, 30, 36), FORK_LOWER=(120, 70, 255), ENGINE_ACCENT=(120, 70, 255),
                                 PLASTIC=(26, 24, 34), TANK=(26, 24, 34), FORK_GUARDS=(26, 24, 34), FRAME=(30, 30, 36),
                                 SWINGARM=(30, 30, 36), HUB=(120, 70, 255), SPOKES=(60, 60, 70))),
}


def paint_skin(charts, skin, path):
    img = Image.new("RGB", (TEX, TEX), skin["primary"])
    d = ImageDraw.Draw(img)

    def fill(c, color, grow=10):
        x, y, w, h = c.rect
        d.rectangle([x - grow, y - grow, x + w + grow, y + h + grow], fill=color)

    def poly(c, pts, color):
        d.polygon([c.frac_to_px(ff, fy) for ff, fy in pts], fill=color)

    def number(c, size_frac=0.62, cy=0.5):
        x, y, w, h = c.rect
        f = font(max(8, int(h * size_frac)))
        cx, py = c.frac_to_px(0.5, cy)
        d.text((cx, py), skin["number"], fill=skin["number_color"], font=f, anchor="mm")

    for side in ("SHROUD_R", "SHROUD_L"):  # base colour with a swoosh rising toward the front
        c = charts[side]
        fill(c, skin["primary"])
        poly(c, [(0.0, 0.05), (0.55, 0.30), (1.0, 0.85), (1.0, 1.05), (0.45, 0.55), (0.0, 0.32)], skin["secondary"])
        poly(c, [(0.0, 0.36), (0.45, 0.59), (1.0, 1.08), (1.0, 1.2), (0.42, 0.68), (0.0, 0.46)], skin["accent"])
    for side in ("SIDEPLATE_R", "SIDEPLATE_L"):
        c = charts[side]
        fill(c, skin["plate"])
        poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.12), (0.0, 0.12)], skin["primary"])
        number(c, 0.58, 0.56)
    c = charts["FRONT_PLATE"]
    fill(c, skin["plate"])
    poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.36), (0.0, 0.36)], skin["primary"])  # headlight sits here
    number(c, 0.40, 0.70)
    for name in ("FRONT_FENDER", "REAR_FENDER"):
        c = charts[name]
        fill(c, skin["primary"])
        for lo, hi, col in ((0.38, 0.62, skin["secondary"]), (0.45, 0.55, skin["accent"])):
            x0, _ = c.frac_to_px(lo, 0)
            x1, _ = c.frac_to_px(hi, 0)
            x, y, w, h = c.rect
            d.rectangle([min(x0, x1), y - 10, max(x0, x1), y + h + 10], fill=col)
    c = charts["SEAT"]
    fill(c, skin["seat"])
    x, y, w, h = c.rect
    for k in range(1, 12):  # gripper ribs
        yy = y + h * k / 12
        d.line([(x + w * 0.12, yy), (x + w * 0.88, yy)], fill=skin["seat_rib"], width=3)
    for side in ("SWINGARM_R", "SWINGARM_L"):
        c = charts[side]
        fill(c, skin["swingarm"])
        poly(c, [(0.55, 0.25), (0.9, 0.25), (0.9, 0.75), (0.55, 0.75)], skin["accent"])
    for i, (name, rgb) in enumerate(BLOCKS):
        x, y, w, h = block_rect(i)
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=skin["blocks"].get(name, rgb))
    img.save(path)


# ---------------------------------------------------------------- normals + export
def bake(part, smooth_deg=40.0):
    V, F = part.world()
    UV = part.corner_uvs()
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
        for c in range(3):
            fs = by_group[G[f, c]]
            n = unit(fn[fs[fu[fs] @ fu[f] > cos_t]].sum(0))
            k = (G[f, c], *np.round(n * 1e3).astype(int), *np.round(UV[f, c] * 1e5).astype(int))
            if k not in out:
                out[k] = len(pos)
                pos.append(V[F[f, c]] - part.pivot)
                nor.append(n)
                uv.append(UV[f, c])
            idx.append(out[k])
    return (np.array(pos, np.float32), np.array(nor, np.float32), np.array(uv, np.float32), np.array(idx, np.uint32))


def write_glb(path, parts, baked, png):
    blob, views, accessors = bytearray(), [], []

    def view(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def accessor(arr, kind, ctype, target, minmax=False):
        a = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": kind}
        if minmax:
            a["min"], a["max"] = arr.min(0).astype(float).tolist(), arr.max(0).astype(float).tolist()
        accessors.append(a)
        return len(accessors) - 1

    meshes, nodes = [], []
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        small = idx.max() < 65535
        prim = {"attributes": {"POSITION": accessor(pos, "VEC3", 5126, 34962, True),
                               "NORMAL": accessor(nor, "VEC3", 5126, 34962),
                               "TEXCOORD_0": accessor(uv, "VEC2", 5126, 34962)},
                "indices": accessor(idx.astype(np.uint16 if small else np.uint32), "SCALAR", 5123 if small else 5125, 34963),
                "material": 0}
        meshes.append({"name": p.name, "primitives": [prim]})
        nodes.append({"name": p.name, "mesh": len(meshes) - 1, "translation": p.pivot.tolist(), "extras": {"group": p.group}})
    image_view = view(png)
    nodes.append({"name": NAME, "children": list(range(len(parts))),
                  "extras": {"units": "studs", "forward": "-Z", "up": "+Y", "steeringRakeDeg": math.degrees(RAKE),
                             "steeringAxis": "through FrontWheel centre, tilted back by steeringRakeDeg"}})
    gltf = {
        "asset": {"version": "2.0", "generator": "Motorcycle Tag build_dirtbike.py"},
        "scene": 0, "scenes": [{"name": NAME, "nodes": [len(nodes) - 1]}], "nodes": nodes, "meshes": meshes,
        "materials": [{"name": "DirtBikeSkin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0,
                                                                         "roughnessFactor": 0.6}}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"name": "skin", "bufferView": image_view, "mimeType": "image/png"}],
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    while len(blob) % 4:
        blob.append(0)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        fh.write(struct.pack("<I4s", len(js), b"JSON") + js)
        fh.write(struct.pack("<I4s", len(blob), b"BIN\x00") + bytes(blob))


def write_obj(path, parts, baked, texture):
    mtl = os.path.splitext(os.path.basename(path))[0] + ".mtl"
    lines = [f"# {NAME} - units: studs, +Y up, front faces -Z", f"mtllib {mtl}"]
    base = 1
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        lines.append(f"o {p.name}")
        lines += [f"v {a:.5f} {b:.5f} {c:.5f}" for a, b, c in pos + p.pivot]
        lines += [f"vt {a:.5f} {1 - b:.5f}" for a, b in uv]
        lines += [f"vn {a:.4f} {b:.4f} {c:.4f}" for a, b, c in nor]
        lines += ["usemtl DirtBikeSkin", "s off"]
        lines += ["f " + " ".join(f"{i}/{i}/{i}" for i in t) for t in idx.reshape(-1, 3) + base]
        base += len(pos)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(os.path.dirname(path), mtl), "w") as fh:
        fh.write(f"newmtl DirtBikeSkin\nKa 0 0 0\nKd 1 1 1\nKs 0.1 0.1 0.1\nNs 30\nd 1\nillum 2\nmap_Kd {texture}\n")


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    density = pack(list(CHARTS.values()))
    baked = [bake(p) for p in parts]
    os.makedirs(os.path.join(OUT_DIR, "skins"), exist_ok=True)
    for name, skin in SKINS.items():
        paint_skin(CHARTS, skin, os.path.join(OUT_DIR, "skins", f"{name}.png"))
    write_template(CHARTS, os.path.join(OUT_DIR, "skin_template.png"), os.path.join(OUT_DIR, "uv_overlay.png"))
    with open(os.path.join(OUT_DIR, "skins", "blaze.png"), "rb") as fh:
        write_glb(os.path.join(OUT_DIR, NAME + ".glb"), parts, baked, fh.read())
    write_obj(os.path.join(OUT_DIR, NAME + ".obj"), parts, baked, "skins/blaze.png")

    total = 0
    print(f"{'part':12s} {'group':6s} {'tris':>5s}  size (studs)        pivot")
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        size, ctr = pos.max(0) - pos.min(0), (pos.max(0) + pos.min(0)) / 2
        total += len(idx) // 3
        note = f"  bbox centre offset {np.abs(ctr).max():.4f}" if p.group == "Wheel" else ""
        print(f"{p.name:12s} {p.group:6s} {len(idx) // 3:5d}  {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}  "
              f"{np.round(p.pivot, 3).tolist()}{note}")
    allv = np.concatenate([b[0] + p.pivot for p, b in zip(parts, baked)])
    ext = allv.max(0) - allv.min(0)
    print(f"total: {total} triangles; bike {ext[0]:.2f} W x {ext[1]:.2f} H x {ext[2]:.2f} L studs; "
          f"panel texel density {density:.0f} px/stud")
    if "--check" in sys.argv:
        kit.check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=90)


if __name__ == "__main__":
    main()
