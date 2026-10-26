#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" street bike with a skinnable UV layout.

Outputs (written next to this folder):
  MotorcycleTag_Bike.glb   main file for the Roblox 3D Importer / Blender, Classic skin embedded
  MotorcycleTag_Bike.obj   same parts as OBJ objects (+ .mtl -> skins/classic.png)
  skin_template.png        1024x1024 guide: every paintable area, labelled
  uv_overlay.png           transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png         example skins; a skin is just a different texture

Units are Roblox studs. Y is up, the bike faces -Z (Roblox LookVector), X is right.
Every wheel is its own mesh, centred on its axle, so its bounding-box centre
(what Roblox uses as the MeshPart position) is exactly the rotation point.

Run:  python3 build_motorcycle.py          build everything
      python3 build_motorcycle.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

from shapes import X, Y, Z, beam, catmull, cbox, check, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit
from skinkit import Atlas, SkinPart, build, fender_chart, front_chart, side_chart, side_panel, top_chart

OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NAME = "MotorcycleTag_Bike"

# ---------------------------------------------------------------- layout
RAKE = math.radians(24.0)                          # steering axis tilt from vertical
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])   # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])          # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.30, 0.45                     # wheel radius, tire half-width
REAR_R, REAR_HW = 1.40, 0.58
FRONT_AXLE = np.array([0.0, FRONT_R, -2.70])
REAR_AXLE = np.array([0.0, REAR_R, 2.70])
SWINGARM_PIVOT = np.array([0.0, 1.55, 0.95])
STEER_LOCK = math.radians(30.0)                    # clearance is checked up to this
FENDER_R = FRONT_R + 0.12


def steer_pt(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Classic colour
    ("TIRE", (32, 33, 36)), ("RIM", (240, 180, 60)), ("HUB", (42, 46, 53)), ("SPOKES", (240, 180, 60)),
    ("FORK_LOWERS", (240, 180, 60)), ("FORK_TUBES", (196, 202, 210)), ("CLAMPS", (240, 180, 60)), ("AXLES", (196, 202, 210)),
    ("BARS", (42, 46, 53)), ("GRIPS", (16, 16, 18)), ("HEADLIGHT", (234, 246, 255)), ("TAILLIGHT", (255, 42, 58)),
    ("WINDSCREEN", (52, 62, 76)), ("FRAME", (42, 46, 53)), ("PEGS", (42, 46, 53)), ("ENGINE", (64, 69, 78)),
    ("ENGINE_ACCENT", (196, 202, 210)), ("EXHAUST", (196, 202, 210)), ("EXHAUST_TIP", (42, 46, 53)),
    ("SWINGARM", (96, 102, 112)), ("SEAT_SIDE", (26, 27, 31)), ("PAINT", (242, 73, 46)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    side_chart("BODY_R", "Bodywork right side", 1, 0.35),
    side_chart("BODY_L", "Bodywork left side", -1, 0.35),
    top_chart("BODY_TOP", "Cowl, tank and tail (top)", 0.55),
    front_chart("COWL_FRONT", "Headlight cowl (front)", 0.5),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FENDER_R),
    top_chart("SEAT", "Seat (top)", 0.5),
    side_chart("SWINGARM_R", "Swingarm right", 1, 0.6),
    side_chart("SWINGARM_L", "Swingarm left", -1, 0.6),
)
CHARTS = ATLAS.charts


# ---------------------------------------------------------------- parts
def build_parts():
    parts = []
    sides = [CHARTS["BODY_R"], CHARTS["BODY_L"]]

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
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
        w.add(lathe(center, prof, 32, [0] * 11 + [1] * 5), ["TIRE", "RIM"])
        hub_hw = 0.86 * hw
        w.add(lathe(center, [(-hub_hw, 0.0), (-hub_hw, 0.16 * f), (-0.75 * hub_hw, 0.25 * f), (0.75 * hub_hw, 0.25 * f),
                             (hub_hw, 0.16 * f), (hub_hw, 0.0)], 20), "HUB")
        for s in range(spokes):
            th = 2 * math.pi * s / spokes
            dirv = math.cos(th) * Y + math.sin(th) * Z
            w.add(beam(center + 0.18 * f * dirv, center + 0.70 * R * dirv, 0.22 * f, 0.30 * hw,
                       0.15 * f, 0.26 * hw, c=0.03, up=X), "SPOKES")
        return w

    wheel("FrontWheel", FRONT_AXLE, FRONT_R, FRONT_HW)
    wheel("RearWheel", REAR_AXLE, REAR_R, REAR_HW)

    # ---------------- steering assembly (pivots at the front axle, which sits on the steering axis)
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.70
        fork.add(cylinder(steer_pt(x, -0.16, 0), steer_pt(x, 1.08, 0), 0.13, 12, 0.05), "FORK_LOWERS")
        fork.add(cylinder(steer_pt(x, 1.0, 0), steer_pt(x, 2.60, 0), 0.10, 12, 0.03), "FORK_TUBES")
        fork.add(cylinder(FRONT_AXLE + sx * 0.45 * X, FRONT_AXLE + sx * 0.86 * X, 0.08, 10, 0.02), "AXLES")
    fork.add(cbox(steer_pt(0, 1.79, 0), (0.86, 0.08, 0.18), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(steer_pt(0, 2.46, 0), (0.84, 0.07, 0.18), 0.05, STEER_ROT), "CLAMPS")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(steer_pt(sx * 0.28, 2.50, 0), steer_pt(sx * 0.28, 2.88, -0.02), 0.075, 10, 0.02), "BARS")
    bar_path = catmull([steer_pt(-0.86, 2.97, -0.20), steer_pt(-0.55, 2.92, -0.08), steer_pt(0, 2.88, 0),
                        steer_pt(0.55, 2.92, -0.08), steer_pt(0.86, 2.97, -0.20)], 4)
    bars.add(tube(bar_path, 0.07, 10, bevel=0.02), "BARS")
    for sx in (-1, 1):
        bars.add(cylinder(steer_pt(sx * 0.80, 2.965, -0.18), steer_pt(sx * 1.10, 3.00, -0.29), 0.105, 12, 0.03), "GRIPS")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.54, FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.08), (fhw - 0.10, r0 + 0.16),
                                  (-fhw + 0.10, r0 + 0.16), (-fhw, r0 + 0.08)], 16,
                     [0] * 6, arc=(RAKE - math.radians(80), RAKE + math.radians(18))), ["PAINT"], [CHARTS["FRONT_FENDER"]])

    # cowl: shield shape in the (x, t) plane lofted forward along n
    shield = [(-0.68, 2.72), (-0.42, 2.92), (0.42, 2.92), (0.68, 2.72), (0.60, 1.98), (0.28, 1.78), (-0.28, 1.78), (-0.60, 1.98)]

    def shield_ring(n, scale, tc=2.32):
        return [steer_pt(x * scale, tc + (t - tc) * scale, n) for (x, t) in shield]

    cowl = part("HeadlightCowl", FRONT_AXLE, "Steer")
    cowl.add(loft([shield_ring(0.30, 0.94), shield_ring(0.36, 1.0), shield_ring(0.58, 0.94), shield_ring(0.72, 0.80),
                   shield_ring(0.76, 0.74)]), "PAINT", [CHARTS["COWL_FRONT"], CHARTS["BODY_TOP"]] + sides)

    lamp = part("Headlight", FRONT_AXLE, "Steer")
    lens = [(-0.44, 2.42), (-0.22, 2.55), (0.22, 2.55), (0.44, 2.42), (0.32, 2.16), (-0.32, 2.16)]
    lamp.add(loft([[steer_pt(x, t, 0.68) for x, t in lens],
                   [steer_pt(x, t, 0.82) for x, t in lens],
                   [steer_pt(x * 0.88, 2.36 + (t - 2.36) * 0.82, 0.86) for x, t in lens]]), "HEADLIGHT")

    screen = part("Windscreen", FRONT_AXLE, "Steer")
    plate = [steer_pt(-0.46, 2.84, 0.58), steer_pt(0.46, 2.84, 0.58), steer_pt(0.42, 3.12, 0.44),
             steer_pt(0.22, 3.34, 0.32), steer_pt(-0.22, 3.34, 0.32), steer_pt(-0.42, 3.12, 0.44)]
    pn = unit(np.cross(plate[1] - plate[0], plate[3] - plate[0]))
    screen.add(loft([[p - 0.025 * pn for p in plate], [p + 0.025 * pn for p in plate]]), "WINDSCREEN")

    # ---------------- body (all welded to Frame in Roblox)
    frame = part("Frame")
    frame.add(cylinder(steer_pt(0, 1.93, 0), steer_pt(0, 2.34, 0), 0.20, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        frame.add(beam(steer_pt(sx * 0.16, 2.16, -0.12), (sx * 0.52, 2.40, 0.62), 0.16, 0.28, 0.14, 0.40, c=0.05), "FRAME")
        frame.add(cbox((sx * 0.56, 1.84, 0.92), (0.07, 0.50, 0.22), 0.05), "FRAME")
        frame.add(beam((sx * 0.50, 2.40, 1.00), (sx * 0.36, 2.94, 2.10), 0.10, 0.14, c=0.03), "FRAME")
        frame.add(cylinder((sx * 0.56, 1.32, 0.62), (sx * 1.08, 1.32, 0.62), 0.09, 10, 0.03), "PEGS")
    frame.add(beam(steer_pt(0, 2.06, -0.16), (0, 2.02, -0.98), 0.15, 0.20, c=0.04), "FRAME")

    engine = part("Engine")
    engine.add(cbox((0, 1.30, -0.12), (0.46, 0.50, 0.84), 0.14), "ENGINE")
    tilt = rotation(X, math.radians(-20))  # lean the cylinder forward
    cyl_c = np.array([0, 2.12, -0.52])
    engine.add(cbox(cyl_c, (0.38, 0.40, 0.34), 0.08, tilt), "ENGINE")
    for k in (-0.14, 0.12):
        engine.add(cbox(cyl_c + tilt @ np.array([0, k, 0]), (0.43, 0.05, 0.39), 0.03, tilt), "ENGINE_ACCENT")
    engine.add(cbox(cyl_c + tilt @ np.array([0, 0.48, -0.02]), (0.42, 0.13, 0.37), 0.07, tilt), "ENGINE")
    engine.add(cylinder((0.40, 1.26, 0.16), (0.58, 1.26, 0.16), 0.38, 16, 0.05), "ENGINE_ACCENT")
    engine.add(cylinder((-0.40, 1.32, -0.36), (-0.57, 1.32, -0.36), 0.32, 16, 0.05), "ENGINE_ACCENT")

    exhaust = part("Exhaust")
    header = catmull([(0.25, 2.30, -0.86), (0.36, 1.80, -1.06), (0.54, 1.10, -1.02), (0.60, 0.74, -0.62),
                      (0.64, 0.70, 0.10), (0.84, 0.86, 0.80), (1.12, 1.30, 1.36), (1.20, 1.62, 1.62)], 4)
    exhaust.add(tube(header, 0.12, 10, bevel=0.02), "EXHAUST")
    m0, m1 = np.array([1.20, 1.56, 1.56]), np.array([1.10, 2.46, 2.86])
    max_ = unit(m1 - m0)
    mu = unit(np.cross(Y, max_))
    mv = np.cross(max_, mu)
    exhaust.add(loft([ring(m0, mu, mv, superellipse(0.17, 0.15, 3, 12)),
                      ring(m0 + 0.20 * max_, mu, mv, superellipse(0.27, 0.25, 3, 12)),
                      ring(m1 - 0.10 * max_, mu, mv, superellipse(0.30, 0.28, 3, 12)),
                      ring(m1, mu, mv, superellipse(0.24, 0.22, 3, 12))]), "EXHAUST")
    exhaust.add(cylinder(m1 - 0.05 * max_, m1 + 0.06 * max_, 0.13, 12, 0.01), "EXHAUST_TIP")

    swing = part("Swingarm")
    swing.add(cylinder(SWINGARM_PIVOT - 0.94 * X, SWINGARM_PIVOT + 0.94 * X, 0.12, 12, 0.03), "SWINGARM")
    for sx in (-1, 1):
        swing.add(beam((sx * 0.84, 1.56, 0.84), (sx * 0.84, 1.40, 2.92), 0.16, 0.34, 0.16, 0.24, c=0.05), "SWINGARM",
                  [CHARTS["SWINGARM_R" if sx > 0 else "SWINGARM_L"]])
        swing.add(cylinder(REAR_AXLE + sx * 0.56 * X, REAR_AXLE + sx * 0.97 * X, 0.09, 10, 0.02), "AXLES")

    body = part("Bodywork")
    tank = [(-1.22, 0.18, 0.12, 3.36), (-1.10, 0.40, 0.26, 3.34), (-0.90, 0.64, 0.38, 3.30), (-0.42, 0.84, 0.44, 3.24),
            (0.04, 0.78, 0.38, 3.14), (0.34, 0.58, 0.27, 3.04), (0.44, 0.34, 0.12, 3.02)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 20)) for z, a, b, cy in tank]), "PAINT",
             [CHARTS["BODY_TOP"]] + sides)
    tail = [(0.90, 0.50, 0.24, 2.88), (1.60, 0.55, 0.28, 3.02), (2.30, 0.47, 0.26, 3.22), (2.85, 0.36, 0.22, 3.42),
            (3.16, 0.28, 0.17, 3.54), (3.22, 0.26, 0.16, 3.56)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.4, 16)) for z, a, b, cy in tail]), "PAINT",
             [CHARTS["BODY_TOP"]] + sides)
    # radiator shrouds flanking the tank, and side covers under the seat
    side_panel(body, [(-1.04, 3.22), (-0.56, 3.20), (-0.18, 2.76), (-0.40, 2.22), (-0.90, 2.12), (-1.20, 2.58)],
               ((0.44, 1.0), (0.86, 1.0), (0.94, 0.88)), "PAINT", *sides)
    side_panel(body, [(0.30, 3.04), (1.50, 3.06), (1.86, 2.84), (1.50, 2.46), (0.52, 2.40), (0.22, 2.70)],
               ((0.36, 1.0), (0.60, 1.0), (0.66, 0.9)), "PAINT", *sides)

    seat = part("Seat")
    cushion = [(0.30, 0.48, 0.16, 3.12), (0.80, 0.58, 0.21, 3.16), (1.45, 0.56, 0.21, 3.24), (1.95, 0.46, 0.17, 3.36),
               (2.22, 0.30, 0.10, 3.44)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.0, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.56, z]), X, Y, superellipse(a, b, 2.4, 16))
                 for z, a, b in ((3.21, 0.24, 0.14), (3.28, 0.22, 0.13), (3.31, 0.17, 0.10))]), "TAILLIGHT")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "classic": dict(primary=(242, 73, 46), secondary=(242, 73, 46), accent=(240, 180, 60), style="plain",
                    seat=(26, 27, 31), swingarm=(96, 102, 112), blocks={}),
    "nightrider": dict(primary=(24, 25, 29), secondary=(48, 50, 56), accent=(60, 255, 120), style="stripe", number="9",
                       seat=(18, 18, 22), swingarm=(30, 31, 36),
                       blocks=dict(RIM=(60, 255, 120), SPOKES=(24, 25, 29), FORK_LOWERS=(24, 25, 29), CLAMPS=(60, 255, 120),
                                   SWINGARM=(30, 31, 36))),
    "glacier": dict(primary=(244, 247, 252), secondary=(30, 110, 230), accent=(30, 110, 230), style="racing",
                    seat=(30, 40, 70), swingarm=(210, 216, 224),
                    blocks=dict(RIM=(30, 110, 230), SPOKES=(244, 247, 252), FORK_LOWERS=(30, 110, 230),
                                CLAMPS=(30, 110, 230), SWINGARM=(210, 216, 224))),
    "sunset": dict(primary=(255, 150, 40), secondary=(150, 40, 200), accent=(255, 230, 120), style="fade",
                   seat=(40, 20, 50), swingarm=(60, 40, 80),
                   blocks=dict(RIM=(150, 40, 200), SPOKES=(150, 40, 200), FORK_LOWERS=(255, 150, 40),
                               CLAMPS=(150, 40, 200), SWINGARM=(60, 40, 80))),
    "cobalt": dict(primary=(25, 70, 200), secondary=(240, 244, 250), accent=(240, 244, 250), style="stripe", number="3",
                   seat=(20, 24, 40), swingarm=(200, 205, 214),
                   blocks=dict(RIM=(240, 244, 250), SPOKES=(25, 70, 200), CLAMPS=(240, 244, 250), FORK_LOWERS=(25, 70, 200))),
    "lime": dict(primary=(150, 230, 30), secondary=(22, 22, 26), accent=(22, 22, 26), style="racing",
                 seat=(22, 22, 26), swingarm=(22, 22, 26),
                 blocks=dict(RIM=(22, 22, 26), SPOKES=(150, 230, 30), CLAMPS=(22, 22, 26), FORK_LOWERS=(22, 22, 26),
                             SWINGARM=(22, 22, 26))),
    "copper": dict(primary=(190, 105, 60), secondary=(40, 30, 26), accent=(40, 30, 26), style="stripe", number="7",
                   seat=(40, 30, 26), swingarm=(40, 30, 26),
                   blocks=dict(RIM=(40, 30, 26), SPOKES=(190, 105, 60), CLAMPS=(190, 105, 60), FORK_LOWERS=(40, 30, 26),
                               SWINGARM=(40, 30, 26))),
    "phantom": dict(primary=(130, 60, 220), secondary=(18, 18, 22), accent=(200, 160, 255), style="fade",
                    seat=(18, 18, 22), swingarm=(18, 18, 22),
                    blocks=dict(RIM=(18, 18, 22), SPOKES=(130, 60, 220), CLAMPS=(130, 60, 220), FORK_LOWERS=(18, 18, 22),
                                SWINGARM=(18, 18, 22))),
}


def blend(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def paint_skin(pt, skin):
    pri, sec, acc, style = skin["primary"], skin["secondary"], skin["accent"], skin["style"]
    for side in ("BODY_R", "BODY_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        # Side livery drawn in side-view (z, y) studs, so both sides line up across the panels.
        if style == "stripe":
            line = [(-3.2, 2.70), (-1.2, 2.95), (0.6, 2.75), (3.4, 3.35)]
            pt.world_poly(c, [(0, y - 0.10, z) for z, y in line] + [(0, y + 0.10, z) for z, y in reversed(line)], acc)
            pt.world_poly(c, [(0, y - 0.22, z) for z, y in line] + [(0, y - 0.14, z) for z, y in reversed(line)], sec)
        elif style == "racing":
            pt.world_poly(c, [(0, 0.0, -3.4), (0, 2.75, -3.4), (0, 2.55, 0.0), (0, 2.85, 3.6), (0, 0.0, 3.6)], sec)
        elif style == "fade":
            for k in range(40):
                y0 = 2.0 + k * 0.05
                pt.world_poly(c, [(0, y0, -3.4), (0, y0, 3.6), (0, y0 + 0.06, 3.6), (0, y0 + 0.06, -3.4)],
                              blend(sec, pri, k / 39))
        if skin.get("number"):
            pt.text_at(c, (0, 2.73, 1.05), skin["number"], acc, 0.42)
    c = CHARTS["BODY_TOP"]
    pt.fill(c, pri)
    if style == "racing":
        pt.bands(c, [(0.36, 0.46, sec), (0.54, 0.64, sec)])
    elif style in ("stripe", "plain"):
        pt.bands(c, [(0.48, 0.52, acc)] if style == "stripe" else [])
    elif style == "fade":
        pt.bands(c, [(0.46, 0.54, acc)])
    c = CHARTS["COWL_FRONT"]
    pt.fill(c, pri)
    if style == "racing":
        pt.bands(c, [(0.36, 0.46, sec), (0.54, 0.64, sec)])
    elif style == "fade":
        pt.fill(c, blend(sec, pri, 0.5))
    c = CHARTS["FRONT_FENDER"]
    pt.fill(c, pri)
    if style == "racing":
        pt.bands(c, [(0.36, 0.46, sec), (0.54, 0.64, sec)])
    elif style in ("stripe", "fade"):
        pt.bands(c, [(0.46, 0.54, acc)])
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    for side in ("SWINGARM_R", "SWINGARM_L"):
        c = CHARTS[side]
        pt.fill(c, skin["swingarm"])
        if style != "plain":
            pt.poly(c, [(0.10, 0.30), (0.40, 0.30), (0.40, 0.70), (0.10, 0.70)], acc)
    pt.blocks(dict(skin["blocks"], PAINT=skin["blocks"].get("PAINT", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_motorcycle.py",
          "StreetBikeSkin", up_labels=("COWL_FRONT",))
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=72)


if __name__ == "__main__":
    main()
