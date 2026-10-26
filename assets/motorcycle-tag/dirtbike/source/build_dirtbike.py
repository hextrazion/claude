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
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
import build_motorcycle as kit  # noqa: E402  (shared primitives from the street bike)
from build_motorcycle import X, Y, beam, catmull, cbox, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402
from skinkit import Atlas, Chart, SkinPart, build, side_chart, side_panel, top_chart  # noqa: E402

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_DirtBike"

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


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
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
ATLAS = Atlas(BLOCKS)

ATLAS.add(
    side_chart("SHROUD_R", "Shroud right", 1),
    side_chart("SHROUD_L", "Shroud left", -1),
    side_chart("SIDEPLATE_R", "Number plate right", 1),
    side_chart("SIDEPLATE_L", "Number plate left", -1),
    Chart("FRONT_PLATE", "Front number plate", lambda n, c: n @ FWD > 0.4,
          lambda p: (-steer_coords(p)[0], steer_coords(p)[1]), "up"),
    Chart("FRONT_FENDER", "Front fender (top)", lambda n, c: n @ D > 0.35,
          lambda p: (steer_coords(p)[0], steer_coords(p)[2]), "up"),
    top_chart("REAR_FENDER", "Rear fender (top)"),
    top_chart("SEAT", "Seat (top)", 0.5),
    side_chart("SWINGARM_R", "Swingarm right", 1, 0.6),
    side_chart("SWINGARM_L", "Swingarm left", -1, 0.6),
)
CHARTS = ATLAS.charts


# ---------------------------------------------------------------- parts
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


def build_parts():
    parts = []

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
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


# ---------------------------------------------------------------- skins
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


def paint_skin(pt, skin):
    for side in ("SHROUD_R", "SHROUD_L"):  # base colour with a swoosh rising toward the front
        c = CHARTS[side]
        pt.fill(c, skin["primary"])
        pt.poly(c, [(0.0, 0.05), (0.55, 0.30), (1.0, 0.85), (1.0, 1.05), (0.45, 0.55), (0.0, 0.32)], skin["secondary"])
        pt.poly(c, [(0.0, 0.36), (0.45, 0.59), (1.0, 1.08), (1.0, 1.2), (0.42, 0.68), (0.0, 0.46)], skin["accent"])
    for side in ("SIDEPLATE_R", "SIDEPLATE_L"):
        c = CHARTS[side]
        pt.fill(c, skin["plate"])
        pt.poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.12), (0.0, 0.12)], skin["primary"])
        pt.number(c, skin["number"], skin["number_color"], 0.58, 0.56)
    c = CHARTS["FRONT_PLATE"]
    pt.fill(c, skin["plate"])
    pt.poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.36), (0.0, 0.36)], skin["primary"])  # headlight sits here
    pt.number(c, skin["number"], skin["number_color"], 0.40, 0.70)
    for name in ("FRONT_FENDER", "REAR_FENDER"):
        c = CHARTS[name]
        pt.fill(c, skin["primary"])
        pt.bands(c, [(0.38, 0.62, skin["secondary"]), (0.45, 0.55, skin["accent"])])
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    pt.ribs(c, skin["seat_rib"])  # gripper ribs
    for side in ("SWINGARM_R", "SWINGARM_L"):
        c = CHARTS[side]
        pt.fill(c, skin["swingarm"])
        pt.poly(c, [(0.55, 0.25), (0.9, 0.25), (0.9, 0.75), (0.55, 0.75)], skin["accent"])
    pt.blocks(skin["blocks"])


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_dirtbike.py",
          "DirtBikeSkin", up_labels=("FRONT_PLATE",))
    if "--check" in sys.argv:
        kit.check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=90)


if __name__ == "__main__":
    main()
