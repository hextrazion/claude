#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" adventure bike: tall, rugged, with a skinnable UV layout.

Outputs (written to the adventure/ folder):
  MotorcycleTag_Adventure.glb   main file, with the Summit skin embedded
  MotorcycleTag_Adventure.obj   same parts as OBJ objects (+ .mtl -> skins/summit.png)
  skin_template.png             1024x1024 guide: every paintable area, labelled
  uv_overlay.png                transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png              skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre. Like a
real adventure bike the nose fairing, beak, headlights and windshield are fixed to the frame;
the fork, bars (with hand guards) and the low front fender turn behind them. The panniers
are their own part so a game can hide them for a stripped-down trim.

Run:  python3 build_adventure.py          build everything
      python3 build_adventure.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, beam, catmull, cbox, check, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402
from skinkit import (Atlas, SkinPart, build, fender_chart, front_chart, side_chart, side_panel,  # noqa: E402
                     spoked_wheel, top_chart)

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_Adventure"

# ---------------------------------------------------------------- layout
RAKE = math.radians(26.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.40, 0.36
REAR_R, REAR_HW = 1.36, 0.52
FRONT_AXLE = np.array([0.0, FRONT_R, -2.85])
REAR_AXLE = np.array([0.0, REAR_R, 2.70])
PIVOT = np.array([0.0, 1.75, 0.95])
STEER_LOCK = math.radians(30.0)
FENDER_R = FRONT_R + 0.10


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Summit colour
    ("TIRE", (34, 34, 37)), ("WHITEWALL", (34, 34, 37)), ("RIM", (40, 42, 48)), ("HUB", (40, 42, 48)),
    ("SPOKES", (200, 205, 212)), ("BRAKE", (150, 156, 164)), ("FORK_UPPER", (238, 176, 52)), ("FORK_LOWER", (205, 212, 220)),
    ("CLAMPS", (40, 42, 48)), ("BARS", (40, 42, 48)), ("GRIPS", (20, 20, 22)), ("HANDGUARDS", (245, 245, 245)),
    ("HEADLIGHTS", (235, 246, 255)), ("TAILLIGHT", (255, 40, 52)), ("WINDSHIELD", (60, 70, 84)), ("FRAME", (40, 42, 48)),
    ("CRASHBARS", (40, 42, 48)), ("SKID", (190, 196, 204)), ("ENGINE", (60, 64, 72)), ("ENGINE_ACCENT", (190, 196, 204)),
    ("EXHAUST", (190, 196, 204)), ("SWINGARM", (190, 196, 204)), ("PANNIERS", (190, 196, 204)), ("RACK", (40, 42, 48)),
    ("PEGS", (40, 42, 48)), ("SEAT_SIDE", (28, 28, 31)), ("PLASTIC", (245, 245, 245)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    side_chart("BODY_R", "Bodywork right side", 1, 0.35),
    side_chart("BODY_L", "Bodywork left side", -1, 0.35),
    top_chart("BODY_TOP", "Beak, nose, tank and tail (top)", 0.55),
    front_chart("NOSE_FRONT", "Nose (front)", 0.6),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FENDER_R),
    top_chart("SEAT", "Seat (top)", 0.5),
    side_chart("PANNIER_R", "Pannier right", 1, 0.6),
    side_chart("PANNIER_L", "Pannier left", -1, 0.6),
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

    # ---------------- wheels: wire-spoked, tall front
    spoked_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW, 12, 0.07, ((-0.33, -0.30),))
    spoked_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW, 12, 0.07)

    # ---------------- steering assembly: fork, bars with hand guards, low fender
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.56
        fork.add(cylinder(sp(x, -0.08, 0), sp(x, 1.30, 0), 0.10, 12, 0.02), "FORK_LOWER")
        fork.add(cbox(sp(x, 0.0, 0.02), (0.10, 0.16, 0.13), 0.04, STEER_ROT), "FORK_LOWER")
        fork.add(cylinder(sp(x, 1.20, 0), sp(x, 3.00, 0), 0.135, 12, 0.03), "FORK_UPPER")
        fork.add(cylinder(FRONT_AXLE + sx * 0.36 * X, FRONT_AXLE + sx * 0.64 * X, 0.07, 10, 0.02), "FORK_LOWER")
    fork.add(cbox(sp(0, 2.40, 0), (0.68, 0.08, 0.18), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 2.95, 0), (0.66, 0.07, 0.18), 0.05, STEER_ROT), "CLAMPS")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.25, 3.02, 0), sp(sx * 0.25, 3.20, -0.04), 0.07, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.86, 3.29, -0.25), sp(sx * 1.10, 3.32, -0.36), 0.10, 12, 0.03), "GRIPS")
        bars.add(cbox(sp(sx * 0.98, 3.31, -0.12), (0.17, 0.12, 0.05), 0.03, STEER_ROT), "HANDGUARDS")
    bars.add(tube(catmull([sp(-0.98, 3.30, -0.30), sp(-0.60, 3.25, -0.16), sp(-0.25, 3.20, -0.05), sp(0.25, 3.20, -0.05),
                           sp(0.60, 3.25, -0.16), sp(0.98, 3.30, -0.30)], 4), 0.07, 10, bevel=0.02), "BARS")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.32, FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.06), (fhw - 0.07, r0 + 0.12), (-fhw + 0.07, r0 + 0.12),
                                  (-fhw, r0 + 0.06)], 14, [0] * 6, arc=(RAKE - math.radians(50), RAKE + math.radians(25))),
               ["PLASTIC"], [CHARTS["FRONT_FENDER"]])

    # ---------------- bodywork (fixed to the frame)
    body = part("Bodywork")
    # Nose lofted forward from a back face clear of everything the fork sweeps; the beak juts out below it.
    cowl = [(-0.78, 2.95), (-0.45, 3.15), (0.45, 3.15), (0.78, 2.95), (0.72, 2.25), (0.40, 2.00), (-0.40, 2.00), (-0.72, 2.25)]
    tc = 2.55
    body.add(loft([[sp(x * k, tc + (t - tc) * k, n) for x, t in cowl] for n, k in ((0.80, 1.0), (1.05, 0.95), (1.25, 0.82),
                                                                                (1.32, 0.66))]),
             "PLASTIC", [CHARTS["NOSE_FRONT"], CHARTS["BODY_TOP"]] + sides)
    beak = []
    for n, t, hw in ((0.85, 2.02, 0.44), (1.30, 1.90, 0.40), (1.72, 1.74, 0.28)):
        beak.append([sp(x * hw, t + dt, n) for x, dt in ((-1, 0), (-0.8, 0.08), (0.8, 0.08), (1, 0), (0.85, -0.05),
                                                          (-0.85, -0.05))])
    body.add(loft(beak), "PLASTIC", [CHARTS["BODY_TOP"]] + sides)
    side_panel(body, [(-2.60, 3.80), (-0.85, 3.70), (-0.55, 3.05), (-0.75, 2.40), (-1.55, 2.30), (-2.50, 2.62), (-2.95, 3.00)],
               ((0.80, 1.0), (0.94, 1.0), (0.99, 0.94)), "PLASTIC", *sides)
    side_panel(body, [(0.35, 3.55), (1.70, 3.60), (2.00, 3.30), (1.65, 2.75), (0.65, 2.70), (0.30, 3.05)],
               ((0.40, 1.0), (0.58, 1.0), (0.63, 0.92)), "PLASTIC", *sides)
    tank = [(-1.15, 0.30, 0.20, 3.62), (-0.95, 0.58, 0.36, 3.62), (-0.55, 0.80, 0.45, 3.55), (0.0, 0.74, 0.40, 3.45),
            (0.35, 0.52, 0.28, 3.35), (0.46, 0.30, 0.12, 3.33)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 20)) for z, a, b, cy in tank]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)
    tail = [(1.80, 0.46, 0.20, 3.62), (2.60, 0.42, 0.18, 3.68), (3.20, 0.30, 0.14, 3.70), (3.30, 0.24, 0.10, 3.70)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 16)) for z, a, b, cy in tail]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)

    lights = part("Headlights")
    for sx in (-1, 1):
        lens = [(0.10, 2.60), (0.26, 2.66), (0.42, 2.58), (0.38, 2.42), (0.14, 2.42)]
        lights.add(loft([[sp(sx * x, t, n) for x, t in lens] for n in (1.28, 1.40)]), "HEADLIGHTS")

    shield = part("Windshield")
    plate = [sp(-0.50, 3.08, 1.06), sp(0.50, 3.08, 1.06), sp(0.46, 3.40, 0.88), sp(0.30, 3.62, 0.72), sp(-0.30, 3.62, 0.72),
             sp(-0.46, 3.40, 0.88)]
    pn = unit(np.cross(plate[1] - plate[0], plate[3] - plate[0]))
    shield.add(loft([[p - 0.025 * pn for p in plate], [p + 0.025 * pn for p in plate]]), "WINDSHIELD")

    seat = part("Seat")
    cushion = [(-0.05, 0.36, 0.10, 3.82), (0.40, 0.50, 0.14, 3.80), (1.10, 0.52, 0.14, 3.80), (1.60, 0.46, 0.12, 3.95),
               (2.20, 0.44, 0.12, 3.98), (2.45, 0.30, 0.08, 3.95)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.0, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.66, z]), X, Y, superellipse(a, b, 2.4, 12))
                 for z, a, b in ((3.28, 0.18, 0.07), (3.35, 0.17, 0.06), (3.38, 0.13, 0.045))]), "TAILLIGHT")

    panniers = part("Panniers")
    for sx in (-1, 1):
        panniers.add(cbox((sx * 0.92, 2.55, 2.20), (0.20, 0.42, 0.62), 0.06), "PANNIERS",
                     [CHARTS["PANNIER_R" if sx > 0 else "PANNIER_L"]])
        panniers.add(beam((sx * 0.45, 3.55, 1.65), (sx * 0.72, 2.95, 1.75), 0.06, 0.06, c=0.015), "RACK")
        panniers.add(beam((sx * 0.45, 3.55, 2.80), (sx * 0.72, 2.95, 2.70), 0.06, 0.06, c=0.015), "RACK")

    frame = part("Frame")
    frame.add(cylinder(sp(0, 2.53, 0), sp(0, 2.83, 0), 0.18, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        frame.add(beam(sp(sx * 0.15, 2.66, -0.14), (sx * 0.50, 2.95, 0.60), 0.13, 0.22, 0.13, 0.32, c=0.04), "FRAME")
        frame.add(cbox((sx * 0.56, 1.80, 0.95), (0.07, 0.42, 0.22), 0.04), "FRAME")
        frame.add(beam((sx * 0.50, 2.95, 0.80), (sx * 0.32, 3.55, 2.30), 0.08, 0.11, c=0.03), "FRAME")
        frame.add(beam(sp(sx * 0.10, 2.62, -0.40), (sx * 0.26, 1.00, -1.00), 0.10, 0.12, c=0.03), "FRAME")
        frame.add(cylinder((sx * 0.50, 1.55, 0.55), (sx * 0.95, 1.55, 0.55), 0.085, 10, 0.03), "PEGS")
        frame.add(tube(catmull([(sx * 0.40, 3.02, -1.02), (sx * 0.70, 2.25, -1.10), (sx * 0.80, 1.70, -1.02),
                                (sx * 0.60, 1.10, -0.78)], 4), 0.06, 8, bevel=0.01), "CRASHBARS")
        frame.add(beam((sx * 0.32, 3.55, 2.45), (sx * 0.32, 3.92, 2.48), 0.05, 0.05, c=0.01), "RACK")
    frame.add(cbox((0, 3.94, 2.88), (0.32, 0.03, 0.45), 0.01), "RACK")                                  # luggage rack
    frame.add(cbox((0, 0.90, -0.25), (0.50, 0.06, 0.90), 0.03), "SKID")

    engine = part("Engine")
    engine.add(cbox((0, 1.45, -0.15), (0.48, 0.48, 0.80), 0.13), "ENGINE")
    tilt = rotation(X, math.radians(-25))
    cyl_c = np.array([0, 2.30, -0.55])
    engine.add(cbox(cyl_c, (0.42, 0.40, 0.32), 0.07, tilt), "ENGINE")
    engine.add(cbox(cyl_c + tilt @ np.array([0, 0.48, 0]), (0.45, 0.12, 0.35), 0.06, tilt), "ENGINE_ACCENT")
    engine.add(cylinder((0.44, 1.40, 0.05), (0.58, 1.40, 0.05), 0.34, 16, 0.05), "ENGINE_ACCENT")

    exhaust = part("Exhaust")
    exhaust.add(tube(catmull([(0.25, 2.45, -0.95), (0.40, 1.80, -1.20), (0.55, 1.15, -0.95), (0.66, 1.10, -0.20),
                              (0.78, 1.55, 0.55), (0.84, 2.10, 0.95)], 4), 0.10, 10, bevel=0.02), "EXHAUST")
    m0, m1 = np.array([0.84, 2.15, 0.92]), np.array([0.88, 2.40, 1.45])
    ax = unit(m1 - m0)
    u = unit(np.cross(Y, ax))
    v = np.cross(ax, u)
    exhaust.add(loft([ring(m0, u, v, superellipse(0.15, 0.14, 3, 12)), ring(m0 + 0.12 * ax, u, v, superellipse(0.19, 0.18, 3, 12)),
                      ring(m1, u, v, superellipse(0.17, 0.16, 3, 12))]), "EXHAUST")

    swing = part("Swingarm")
    swing.add(cylinder(PIVOT - 0.80 * X, PIVOT + 0.80 * X, 0.11, 12, 0.03), "SWINGARM")
    for sx in (-1, 1):
        swing.add(beam((sx * 0.70, 1.78, 0.82), (sx * 0.70, 1.36, 2.90), 0.15, 0.32, 0.15, 0.22, c=0.04), "SWINGARM")
        swing.add(cylinder(REAR_AXLE + sx * 0.50 * X, REAR_AXLE + sx * 0.86 * X, 0.08, 10, 0.02), "SWINGARM")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "summit": dict(primary=(245, 245, 245), secondary=(220, 30, 40), accent=(30, 70, 200), number="33",
                   seat=(28, 28, 31), blocks=dict(RIM=(30, 70, 200), HANDGUARDS=(245, 245, 245))),
    "dune": dict(primary=(222, 190, 130), secondary=(240, 120, 30), accent=(60, 45, 30), number="7",
                 seat=(60, 45, 30), blocks=dict(PLASTIC=(222, 190, 130), RIM=(240, 120, 30), HANDGUARDS=(240, 120, 30),
                                                FRAME=(60, 45, 30), CRASHBARS=(240, 120, 30), PANNIERS=(60, 45, 30))),
    "arctic": dict(primary=(236, 242, 246), secondary=(130, 140, 152), accent=(0, 190, 200), number="1",
                   seat=(40, 46, 56), blocks=dict(RIM=(0, 190, 200), HANDGUARDS=(0, 190, 200), CRASHBARS=(130, 140, 152))),
    "jungle": dict(primary=(80, 96, 50), secondary=(30, 32, 26), accent=(230, 200, 60), number="21",
                   seat=(30, 32, 26), blocks=dict(PLASTIC=(80, 96, 50), RIM=(30, 32, 26), HANDGUARDS=(30, 32, 26),
                                                  PANNIERS=(60, 70, 40), CRASHBARS=(30, 32, 26), SKID=(60, 64, 56))),
    "volcano": dict(primary=(26, 26, 30), secondary=(255, 110, 20), accent=(255, 200, 60), number="66",
                    seat=(20, 20, 22), blocks=dict(PLASTIC=(26, 26, 30), RIM=(255, 110, 20), HANDGUARDS=(255, 110, 20),
                                                   CRASHBARS=(255, 110, 20), PANNIERS=(40, 42, 48))),
    "rally": dict(primary=(255, 210, 0), secondary=(24, 24, 28), accent=(255, 255, 255), number="99",
                  seat=(24, 24, 28), blocks=dict(PLASTIC=(255, 210, 0), RIM=(24, 24, 28), HANDGUARDS=(24, 24, 28),
                                                 FORK_UPPER=(24, 24, 28))),
    "ocean": dict(primary=(20, 40, 90), secondary=(0, 200, 230), accent=(250, 250, 250), number="5",
                  seat=(16, 20, 36), blocks=dict(PLASTIC=(20, 40, 90), RIM=(0, 200, 230), HANDGUARDS=(0, 200, 230),
                                                 CRASHBARS=(20, 40, 90))),
    "stealth": dict(primary=(70, 74, 80), secondary=(30, 32, 36), accent=(120, 255, 60), number="0",
                    seat=(22, 22, 26), blocks=dict(PLASTIC=(70, 74, 80), RIM=(30, 32, 36), SPOKES=(30, 32, 36),
                                                   HANDGUARDS=(30, 32, 36), FORK_UPPER=(30, 32, 36), PANNIERS=(30, 32, 36),
                                                   SKID=(30, 32, 36), EXHAUST=(50, 52, 58))),
}


def paint_skin(pt, skin):
    pri, sec, acc = skin["primary"], skin["secondary"], skin["accent"]
    for side in ("BODY_R", "BODY_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        # Rally livery in side-view (z, y) studs: a swept band from the beak back to the tail.
        line = [(-3.8, 2.70), (-2.0, 2.85), (-0.6, 3.10), (1.0, 3.05), (3.5, 3.55)]
        pt.world_poly(c, [(0, y - 0.30, z) for z, y in line] + [(0, y, z) for z, y in reversed(line)], sec)
        pt.world_poly(c, [(0, y + 0.04, z) for z, y in line] + [(0, y + 0.14, z) for z, y in reversed(line)], acc)
        pt.text_at(c, (0, 3.18, 1.15), skin["number"], sec if sum(pri) > 300 else acc, 0.40)
    c = CHARTS["BODY_TOP"]
    pt.fill(c, pri)
    pt.bands(c, [(0.44, 0.48, sec), (0.52, 0.56, acc)])
    c = CHARTS["NOSE_FRONT"]
    pt.fill(c, pri)
    pt.poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.25), (0.0, 0.25)], sec)
    c = CHARTS["FRONT_FENDER"]
    pt.fill(c, pri)
    pt.bands(c, [(0.42, 0.58, sec)])
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    pt.ribs(c, tuple(min(255, v + 20) for v in skin["seat"]), 10, 3)
    for side in ("PANNIER_R", "PANNIER_L"):
        c = CHARTS[side]
        pt.fill(c, skin["blocks"].get("PANNIERS", ATLAS.blocks[ATLAS.index["PANNIERS"]][1]))
        pt.poly(c, [(0.0, 0.62), (1.0, 0.62), (1.0, 0.80), (0.0, 0.80)], sec)
        pt.number(c, "HALDOR", acc if sum(sec) < 300 else (24, 24, 28), 0.15, 0.71)
    pt.blocks(dict(skin["blocks"], PLASTIC=skin["blocks"].get("PLASTIC", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_adventure.py",
          "AdventureSkin", up_labels=("NOSE_FRONT",))
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=30)


if __name__ == "__main__":
    main()
