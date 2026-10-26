#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" superbike: a full-fairing race bike with a skinnable UV layout.

Outputs (written to the superbike/ folder):
  MotorcycleTag_SuperBike.glb   main file, with the Apex skin embedded
  MotorcycleTag_SuperBike.obj   same parts as OBJ objects (+ .mtl -> skins/apex.png)
  skin_template.png             1024x1024 guide: every paintable area, labelled
  uv_overlay.png                transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png              example skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre. Like a
real superbike the fairing, headlights and windshield are fixed to the frame; only the fork,
clip-on bars and front fender turn, inside a gap left around the fork's swept space.

Run:  python3 build_superbike.py          build everything
      python3 build_superbike.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, Z, beam, catmull, cbox, check, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402
from skinkit import Atlas, Chart, SkinPart, build, front_chart, side_chart, side_panel, top_chart  # noqa: E402

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_SuperBike"

# ---------------------------------------------------------------- layout
RAKE = math.radians(23.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.30, 0.42
REAR_R, REAR_HW = 1.36, 0.62
FRONT_AXLE = np.array([0.0, FRONT_R, -2.75])
REAR_AXLE = np.array([0.0, REAR_R, 2.65])
PIVOT = np.array([0.0, 1.55, 0.95])
STEER_LOCK = math.radians(30.0)
FENDER_R = FRONT_R + 0.10


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Apex colour
    ("TIRE", (34, 34, 37)), ("RIM", (232, 255, 42)), ("HUB", (40, 42, 48)), ("SPOKES", (232, 255, 42)),
    ("BRAKE", (170, 176, 184)), ("CALIPERS", (232, 255, 42)), ("FORK_UPPER", (238, 176, 52)),
    ("FORK_LOWER", (205, 212, 220)), ("CLAMPS", (52, 56, 62)), ("BARS", (40, 42, 46)), ("GRIPS", (20, 20, 22)),
    ("HEADLIGHTS", (235, 246, 255)), ("TAILLIGHT", (255, 40, 52)), ("WINDSHIELD", (40, 52, 70)),
    ("FRAME", (52, 56, 62)), ("ENGINE", (52, 56, 62)), ("RADIATOR", (30, 32, 36)), ("EXHAUST", (190, 196, 204)),
    ("EXHAUST_TIPS", (40, 42, 46)), ("SWINGARM", (180, 186, 194)), ("PEGS", (40, 42, 46)), ("SEAT_SIDE", (26, 26, 30)),
    ("PLASTIC", (28, 92, 255)), ("BELLY", (24, 24, 28)),
]
ATLAS = Atlas(BLOCKS)


def fender_proj(p):
    th = math.atan2(p[2] - FRONT_AXLE[2], p[1] - FRONT_AXLE[1])
    return p[0], -th * FENDER_R


def fender_pred(n, c):
    radial = unit(np.array([0.0, c[1] - FRONT_AXLE[1], c[2] - FRONT_AXLE[2]]))
    return n @ radial > 0.6


ATLAS.add(
    side_chart("BODY_R", "Bodywork right side", 1, 0.35),
    side_chart("BODY_L", "Bodywork left side", -1, 0.35),
    top_chart("BODY_TOP", "Nose, tank and tail (top)", 0.55),
    front_chart("NOSE_FRONT", "Nose (front)", 0.6),
    top_chart("SEAT", "Seat (top)", 0.5),
    Chart("FRONT_FENDER", "Front fender (unrolled)", fender_pred, fender_proj, "up"),
    side_chart("SWINGARM_R", "Swingarm right", 1, 0.6),
    side_chart("SWINGARM_L", "Swingarm left", -1, 0.6),
)
CHARTS = ATLAS.charts


# ---------------------------------------------------------------- parts
def sport_wheel(part, center, R, hw, disc_x=()):
    prof = [  # closed (x, r) loop: rounded race tire outside, rim inside
        (-0.85 * hw, 0.73 * R), (-0.975 * hw, 0.80 * R), (-1.0 * hw, 0.87 * R), (-0.90 * hw, 0.94 * R),
        (-0.62 * hw, 0.985 * R), (-0.22 * hw, R), (0.22 * hw, R), (0.62 * hw, 0.985 * R),
        (0.90 * hw, 0.94 * R), (1.0 * hw, 0.87 * R), (0.975 * hw, 0.80 * R), (0.85 * hw, 0.73 * R),
        (0.80 * hw, 0.71 * R), (0.70 * hw, 0.635 * R), (-0.70 * hw, 0.635 * R), (-0.80 * hw, 0.71 * R),
    ]
    part.add(lathe(center, prof, 32, [0] * 11 + [1] * 5), ["TIRE", "RIM"])
    hub_hw = 0.86 * hw
    part.add(lathe(center, [(-hub_hw, 0.0), (-hub_hw, 0.15), (-0.75 * hub_hw, 0.24), (0.75 * hub_hw, 0.24),
                            (hub_hw, 0.15), (hub_hw, 0.0)], 18), "HUB")
    for k in range(3):  # three split "Y" spokes
        th = 2 * math.pi * k / 3
        root = math.cos(th) * Y + math.sin(th) * Z
        for split in (-0.24, 0.24):
            tip = math.cos(th + split) * Y + math.sin(th + split) * Z
            part.add(beam(center + 0.18 * root, center + 0.66 * R * tip, 0.13, 0.30 * hw, 0.10, 0.26 * hw, c=0.03, up=X),
                     "SPOKES")
    for x0, x1 in disc_x:
        part.add(lathe(center, [(x0, 0.44), (x0, 0.66), (x1, 0.66), (x1, 0.44)], 24), "BRAKE")


def build_parts():
    parts = []

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels
    sport_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW, ((-0.31, -0.28), (0.28, 0.31)))
    sport_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW, ((-0.50, -0.47),))

    # ---------------- steering assembly: fork, clip-ons, fender
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.60
        fork.add(cylinder(sp(x, -0.08, 0), sp(x, 1.00, 0), 0.095, 12, 0.02), "FORK_LOWER")
        fork.add(cbox(sp(x, 0.0, 0.02), (0.10, 0.16, 0.13), 0.04, STEER_ROT), "FORK_LOWER")
        fork.add(cylinder(sp(x, 0.92, 0), sp(x, 2.45, 0), 0.13, 12, 0.03), "FORK_UPPER")
        fork.add(cylinder(FRONT_AXLE + sx * 0.42 * X, FRONT_AXLE + sx * 0.66 * X, 0.07, 10, 0.02), "FORK_LOWER")
        # radial caliper gripping the disc behind the leg
        fork.add(cbox(sp(sx * 0.44, 0.30, -0.50), (0.07, 0.22, 0.09), 0.03, STEER_ROT), "CALIPERS")
    fork.add(cbox(sp(0, 1.80, 0), (0.70, 0.08, 0.18), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 2.35, 0), (0.68, 0.07, 0.18), 0.05, STEER_ROT), "CLAMPS")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.60, 2.44, 0), sp(sx * 0.60, 2.60, 0), 0.15, 12, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.70, 2.56, -0.03), sp(sx * 0.84, 2.555, -0.10), 0.06, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.78, 2.555, -0.08), sp(sx * 0.93, 2.54, -0.16), 0.09, 12, 0.03), "GRIPS")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw = 0.40
    fender.add(lathe(FRONT_AXLE, [(-fhw, FENDER_R), (fhw, FENDER_R), (fhw, FENDER_R + 0.07), (fhw - 0.10, FENDER_R + 0.13),
                                  (-fhw + 0.10, FENDER_R + 0.13), (-fhw, FENDER_R + 0.07)], 16,
                     [0] * 6, arc=(RAKE - math.radians(62), RAKE + math.radians(28))), ["PLASTIC"], [CHARTS["FRONT_FENDER"]])

    # ---------------- bodywork (fixed to the frame)
    body = part("Bodywork")
    sides = [CHARTS["BODY_R"], CHARTS["BODY_L"]]
    # The nose is lofted forward from a back face that stays clear of everything the fork sweeps.
    cowl = [(-0.95, 2.45), (-0.55, 2.65), (0.55, 2.65), (0.95, 2.45), (0.90, 1.75), (0.45, 1.45), (-0.45, 1.45), (-0.90, 1.75)]
    tc = 2.05
    body.add(loft([[sp(x * k, tc + (t - tc) * k, n) for x, t in cowl] for n, k in ((0.86, 1.0), (1.10, 0.95), (1.30, 0.80),
                                                                                (1.38, 0.62))]),
             "PLASTIC", [CHARTS["NOSE_FRONT"], CHARTS["BODY_TOP"]] + sides)
    # upper fairing sides hugging the nose, a mid panel over the frame, and the lower fairing
    side_panel(body, [(-2.84, 3.40), (-1.40, 3.34), (-0.72, 3.14), (-0.80, 2.30), (-1.45, 2.00), (-2.35, 2.42), (-2.96, 2.98)],
               ((0.88, 1.0), (1.02, 1.0), (1.07, 0.95)), "PLASTIC", *sides)
    side_panel(body, [(-0.72, 3.30), (0.30, 3.20), (0.45, 2.75), (0.10, 2.20), (-0.80, 2.30)],
               ((0.56, 1.0), (0.72, 1.0), (0.77, 0.94)), "PLASTIC", *sides)
    side_panel(body, [(-1.45, 2.00), (-0.80, 2.30), (-0.15, 1.95), (0.10, 1.20), (-0.30, 0.78), (-1.30, 0.95)],
               ((0.60, 1.0), (0.80, 1.0), (0.86, 0.95)), "PLASTIC", *sides)
    tank = [(-1.25, 0.28, 0.16, 3.62), (-1.05, 0.52, 0.30, 3.62), (-0.60, 0.74, 0.40, 3.56), (-0.10, 0.70, 0.36, 3.44),
            (0.25, 0.50, 0.24, 3.32), (0.36, 0.28, 0.10, 3.28)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 20)) for z, a, b, cy in tank]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)
    tail = [(0.80, 0.54, 0.30, 3.06), (1.45, 0.56, 0.33, 3.26), (2.20, 0.44, 0.28, 3.50), (2.95, 0.26, 0.19, 3.72),
            (3.30, 0.14, 0.10, 3.84), (3.36, 0.12, 0.09, 3.85)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.4, 16)) for z, a, b, cy in tail]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)
    body.add(loft([ring(np.array([0, 1.02, z]), X, Y, superellipse(a, 0.14, 3.0, 16)) for z, a in
                   ((-1.30, 0.40), (-1.15, 0.60), (-0.10, 0.62), (0.10, 0.48))]), "BELLY")

    lights = part("Headlights")
    for sx in (-1, 1):
        lens = [(0.10, 2.10), (0.28, 2.16), (0.48, 2.08), (0.44, 1.96), (0.14, 1.97)]
        lights.add(loft([[sp(sx * x, t, n) for x, t in lens] for n in (1.32, 1.43)]), "HEADLIGHTS")

    shield = part("Windshield")
    plate = [sp(-0.52, 2.58, 1.12), sp(0.52, 2.58, 1.12), sp(0.46, 2.80, 0.92), sp(0.26, 2.98, 0.72), sp(-0.26, 2.98, 0.72),
             sp(-0.46, 2.80, 0.92)]
    pn = unit(np.cross(plate[1] - plate[0], plate[3] - plate[0]))
    shield.add(loft([[p - 0.025 * pn for p in plate], [p + 0.025 * pn for p in plate]]), "WINDSHIELD")

    seat = part("Seat")
    cushion = [(0.20, 0.40, 0.08, 3.24), (0.60, 0.50, 0.11, 3.24), (1.15, 0.48, 0.11, 3.30), (1.40, 0.36, 0.07, 3.36)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.0, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.85, z]), X, Y, superellipse(a, b, 2.4, 12))
                 for z, a, b in ((3.35, 0.13, 0.085), (3.42, 0.12, 0.075), (3.45, 0.09, 0.055))]), "TAILLIGHT")

    frame = part("Frame")
    frame.add(cylinder(sp(0, 1.93, 0), sp(0, 2.23, 0), 0.19, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        frame.add(beam(sp(sx * 0.16, 2.05, -0.14), (sx * 0.62, 2.80, 0.30), 0.14, 0.24, 0.14, 0.42, c=0.05), "FRAME")
        frame.add(beam((sx * 0.62, 2.80, 0.30), (sx * 0.62, 2.10, 0.95), 0.14, 0.42, 0.14, 0.36, c=0.05), "FRAME")
        frame.add(cbox((sx * 0.62, 1.85, 0.95), (0.08, 0.50, 0.24), 0.05), "FRAME")
        frame.add(cylinder((sx * 0.66, 1.80, 0.60), (sx * 0.98, 1.80, 0.60), 0.08, 10, 0.03), "PEGS")

    engine = part("Engine")
    engine.add(cbox((0, 1.40, -0.30), (0.55, 0.45, 0.70), 0.12), "ENGINE")
    tilt = rotation(X, math.radians(-30))
    cyl_c = np.array([0, 2.12, -0.62])
    engine.add(cbox(cyl_c, (0.50, 0.38, 0.30), 0.07, tilt), "ENGINE")
    engine.add(cbox(cyl_c + tilt @ np.array([0, 0.45, 0]), (0.52, 0.12, 0.32), 0.06, tilt), "ENGINE")
    engine.add(cbox((0, 2.05, -1.22), (0.52, 0.42, 0.05), 0.02, rotation(X, math.radians(-15))), "RADIATOR")

    exhaust = part("Exhaust")
    for sx in (-0.18, 0.18):
        exhaust.add(tube(catmull([(sx, 2.05, -1.02), (sx * 1.2, 1.40, -1.20), (sx * 1.2, 0.85, -0.95), (sx, 0.74, -0.55)], 4),
                         0.08, 10, bevel=0.02), "EXHAUST")
    exhaust.add(cbox((0, 0.74, 0.10), (0.46, 0.13, 0.62), 0.07), "EXHAUST")
    for sx in (0.18, 0.40):
        exhaust.add(cylinder((sx, 0.74, 0.60), (sx, 0.76, 0.86), 0.075, 10, 0.01), "EXHAUST_TIPS")

    swing = part("Swingarm")
    swing.add(cylinder(PIVOT - 0.92 * X, PIVOT + 0.92 * X, 0.12, 12, 0.03), "SWINGARM")
    for sx in (-1, 1):
        swing.add(beam((sx * 0.80, 1.60, 0.82), (sx * 0.80, 1.36, 2.90), 0.16, 0.38, 0.16, 0.24, c=0.05), "SWINGARM",
                  [CHARTS["SWINGARM_R" if sx > 0 else "SWINGARM_L"]])
        swing.add(cylinder(REAR_AXLE + sx * 0.60 * X, REAR_AXLE + sx * 0.92 * X, 0.09, 10, 0.02), "SWINGARM")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "apex": dict(primary=(28, 92, 255), secondary=(250, 250, 250), accent=(232, 255, 42), number="01",
                 seat=(26, 26, 30), swingarm=(180, 186, 194), blocks={}),
    "inferno": dict(primary=(222, 22, 38), secondary=(24, 24, 28), accent=(255, 196, 40), number="17",
                    seat=(24, 24, 28), swingarm=(40, 42, 48),
                    blocks=dict(RIM=(255, 196, 40), SPOKES=(255, 196, 40), CALIPERS=(255, 196, 40), PLASTIC=(222, 22, 38),
                                FRAME=(222, 22, 38), SWINGARM=(40, 42, 48), WINDSHIELD=(24, 24, 28))),
    "phantom": dict(primary=(30, 31, 36), secondary=(70, 74, 82), accent=(0, 230, 200), number="00",
                    seat=(18, 18, 22), swingarm=(30, 31, 36),
                    blocks=dict(RIM=(30, 31, 36), SPOKES=(30, 31, 36), CALIPERS=(0, 230, 200), PLASTIC=(30, 31, 36),
                                FRAME=(50, 52, 58), SWINGARM=(30, 31, 36), FORK_UPPER=(50, 52, 58), CLAMPS=(0, 230, 200),
                                EXHAUST=(50, 52, 58))),
    "sakura": dict(primary=(255, 150, 200), secondary=(255, 255, 255), accent=(150, 60, 220), number="88",
                   seat=(255, 255, 255), swingarm=(255, 255, 255),
                   blocks=dict(RIM=(255, 255, 255), SPOKES=(255, 255, 255), CALIPERS=(150, 60, 220),
                               PLASTIC=(255, 150, 200), FRAME=(255, 255, 255), SWINGARM=(255, 255, 255),
                               FORK_UPPER=(150, 60, 220), BELLY=(255, 255, 255), SEAT_SIDE=(255, 255, 255))),
}


def paint_skin(pt, skin):
    pri, sec, acc = skin["primary"], skin["secondary"], skin["accent"]
    for side in ("BODY_R", "BODY_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        # Livery drawn in side-view (z, y) studs, so both sides line up with the bodywork.
        line = [(-3.4, 2.95), (-1.6, 2.62), (-0.2, 2.15), (1.0, 2.70), (3.6, 3.62)]
        below = [(z, y) for z, y in line] + [(3.6, 0.0), (-3.4, 0.0)]
        stripe = [(z, y + 0.06) for z, y in line] + [(z, y + 0.20) for z, y in reversed(line)]
        pt.world_poly(c, [(0, y, z) for z, y in below], sec)
        pt.world_poly(c, [(0, y, z) for z, y in stripe], acc)
        pt.text_at(c, (0, 3.50, 2.25), skin["number"], sec if sum(pri) < 400 else acc, 0.34)
        pt.text_at(c, (0, 2.95, -2.05), skin["number"], acc, 0.42)
    c = CHARTS["BODY_TOP"]
    pt.fill(c, pri)
    pt.bands(c, [(0.40, 0.46, sec), (0.54, 0.60, sec), (0.47, 0.53, acc)])
    c = CHARTS["NOSE_FRONT"]
    pt.fill(c, pri)
    pt.poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.30), (0.5, 0.55), (0.0, 0.30)], sec)
    pt.poly(c, [(0.36, 0.0), (0.64, 0.0), (0.60, 0.22), (0.40, 0.22)], (20, 20, 24))  # ram-air intake
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    pt.bands(c, [(0.47, 0.53, acc)])
    c = CHARTS["FRONT_FENDER"]
    pt.fill(c, pri)
    pt.bands(c, [(0.40, 0.60, sec), (0.46, 0.54, acc)])
    for side in ("SWINGARM_R", "SWINGARM_L"):
        c = CHARTS[side]
        pt.fill(c, skin["swingarm"])
        pt.poly(c, [(0.10, 0.30), (0.45, 0.30), (0.45, 0.70), (0.10, 0.70)], acc)
    pt.blocks(dict(skin["blocks"], PLASTIC=skin["blocks"].get("PLASTIC", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_superbike.py",
          "SuperBikeSkin", up_labels=("NOSE_FRONT",))
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=120)


if __name__ == "__main__":
    main()
