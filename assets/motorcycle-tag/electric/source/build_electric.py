#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" electric bike: angular, hubless wheels, with a skinnable UV layout.

Outputs (written to the electric/ folder):
  MotorcycleTag_Electric.glb   main file, with the Volt skin embedded
  MotorcycleTag_Electric.obj   same parts as OBJ objects (+ .mtl -> skins/volt.png)
  skin_template.png            1024x1024 guide: every paintable area, labelled
  uv_overlay.png               transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png             skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre.

The wheels are hubless: each wheel is a tire, rim and glow ring with an open centre. A fixed
stator ring sits inside that opening, held by the single-sided fork (left) or single-sided
swingarm (right), so the wheel spins around it. The nose cowl, light bar and visor are fixed
to the frame like a superbike's; the fork, bars and front fender turn behind them.
`LightStrips` is its own part so a game can make it Neon in any colour.

Run:  python3 build_electric.py          build everything
      python3 build_electric.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, beam, cbox, check, cylinder, lathe, loft, ring, superellipse, unit  # noqa: E402
from skinkit import (Atlas, SkinPart, build, fender_chart, front_chart, side_chart, side_panel,  # noqa: E402
                     top_chart)

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_Electric"

# ---------------------------------------------------------------- layout
RAKE = math.radians(24.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.30, 0.42
REAR_R, REAR_HW = 1.36, 0.58
FRONT_AXLE = np.array([0.0, FRONT_R, -2.75])
REAR_AXLE = np.array([0.0, REAR_R, 2.65])
PIVOT = np.array([0.0, 1.55, 0.80])
STEER_LOCK = math.radians(30.0)
FENDER_R = FRONT_R + 0.10


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Volt colour
    ("TIRE", (30, 30, 33)), ("RIM", (36, 38, 44)), ("RIM_GLOW", (0, 230, 255)), ("STATOR", (60, 64, 72)),
    ("FORK", (36, 38, 44)), ("CLAMPS", (36, 38, 44)), ("BARS", (36, 38, 44)), ("GRIPS", (18, 18, 20)),
    ("DISPLAY", (0, 230, 255)), ("HEADLIGHTS", (220, 250, 255)), ("TAILLIGHT", (255, 30, 60)),
    ("LIGHT_STRIPS", (0, 230, 255)), ("WINDSHIELD", (30, 40, 50)), ("FRAME", (36, 38, 44)), ("BATTERY", (44, 46, 52)),
    ("MOTOR", (70, 74, 82)), ("SWINGARM", (36, 38, 44)), ("PEGS", (36, 38, 44)), ("SEAT_SIDE", (22, 22, 26)),
    ("PLASTIC", (240, 244, 248)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    side_chart("BODY_R", "Bodywork right side", 1, 0.35),
    side_chart("BODY_L", "Bodywork left side", -1, 0.35),
    top_chart("BODY_TOP", "Nose and body (top)", 0.55),
    front_chart("NOSE_FRONT", "Nose (front)", 0.6),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FENDER_R),
    top_chart("SEAT", "Seat (top)", 0.5),
    side_chart("SWINGARM_R", "Swingarm (right)", 1, 0.6),
)
CHARTS = ATLAS.charts


def hexagon(hw, top, bottom):
    """Angular body section: wide at the shoulders, narrower at top and bottom."""
    mid, h = (top + bottom) / 2, (top - bottom) / 2
    return [(hw, mid + 0.15 * h), (0.55 * hw, top), (-0.55 * hw, top), (-hw, mid + 0.15 * h), (-0.7 * hw, bottom),
            (0.7 * hw, bottom)]


# ---------------------------------------------------------------- parts
def hubless_wheel(part, center, R, hw):
    prof = [  # closed (x, r) loop: low-profile tire outside, rim inside
        (-0.85 * hw, 0.80 * R), (-0.98 * hw, 0.86 * R), (-1.0 * hw, 0.92 * R), (-0.88 * hw, 0.975 * R), (-0.50 * hw, R),
        (0.50 * hw, R), (0.88 * hw, 0.975 * R), (1.0 * hw, 0.92 * R), (0.98 * hw, 0.86 * R), (0.85 * hw, 0.80 * R),
        (0.80 * hw, 0.78 * R), (0.70 * hw, 0.64 * R), (-0.70 * hw, 0.64 * R), (-0.80 * hw, 0.78 * R),
    ]
    part.add(lathe(center, prof, 40, [0] * 10 + [1] * 4), ["TIRE", "RIM"])
    part.add(lathe(center, [(-0.62 * hw, 0.56 * R), (0.62 * hw, 0.56 * R), (0.62 * hw, 0.645 * R), (-0.62 * hw, 0.645 * R)],
                   40), "RIM_GLOW")


def build_parts():
    parts = []
    sides = [CHARTS["BODY_R"], CHARTS["BODY_L"]]

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels
    hubless_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW)
    hubless_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW)

    # ---------------- steering assembly: single-sided fork on the left, bars, blade fender
    fork = part("Fork", FRONT_AXLE, "Steer")
    fork.add(lathe(FRONT_AXLE, [(-0.5 * FRONT_HW, 0.38 * FRONT_R), (0.5 * FRONT_HW, 0.38 * FRONT_R),
                                (0.5 * FRONT_HW, 0.50 * FRONT_R), (-0.5 * FRONT_HW, 0.50 * FRONT_R)], 32), "STATOR")
    tb = 0.44 * FRONT_R  # bracket height along the steering axis, inside the wheel's open centre
    fork.add(cbox(sp(-0.42, tb, 0), (0.21, 0.09, 0.12), 0.03, STEER_ROT), "STATOR")
    fork.add(cbox(sp(-0.66, 1.40, 0), (0.08, 0.86, 0.14), 0.04, STEER_ROT), "FORK")            # the single arm
    fork.add(cbox(sp(-0.33, 2.20, 0), (0.41, 0.08, 0.15), 0.04, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(-0.33, 2.85, 0), (0.41, 0.07, 0.15), 0.04, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(-0.66, 2.52, 0), (0.08, 0.32, 0.12), 0.03, STEER_ROT), "FORK")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.10, 2.92, -0.02), sp(sx * 0.80, 2.98, -0.20), 0.065, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.78, 2.975, -0.19), sp(sx * 1.02, 3.00, -0.26), 0.09, 12, 0.03), "GRIPS")
    bars.add(cbox(sp(0, 3.00, 0.06), (0.22, 0.04, 0.13), 0.02, STEER_ROT), "DISPLAY")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.36, FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.05), (fhw - 0.10, r0 + 0.12), (-fhw + 0.10, r0 + 0.12),
                                  (-fhw, r0 + 0.05)], 12, [0] * 6, arc=(RAKE - math.radians(45), RAKE + math.radians(20))),
               ["PLASTIC"], [CHARTS["FRONT_FENDER"]])

    # ---------------- body (fixed to the frame)
    body = part("Bodywork")
    cowl = [(-0.62, 2.70), (-0.30, 2.85), (0.30, 2.85), (0.62, 2.70), (0.56, 2.10), (0.25, 1.92), (-0.25, 1.92), (-0.56, 2.10)]
    tc = 2.40
    body.add(loft([[sp(x * k, tc + (t - tc) * k, n) for x, t in cowl] for n, k in ((0.86, 1.0), (1.10, 0.92), (1.30, 0.70),
                                                                                (1.38, 0.50))]),
             "PLASTIC", [CHARTS["NOSE_FRONT"], CHARTS["BODY_TOP"]] + sides)
    side_panel(body, [(-2.55, 3.52), (-0.70, 3.46), (-0.60, 2.90), (-1.30, 2.40), (-2.30, 2.80)],
               ((0.84, 1.0), (0.94, 1.0), (0.98, 0.94)), "PLASTIC", *sides)
    shell = [(-0.75, 0.30, 3.70, 3.10), (-0.40, 0.62, 3.80, 2.70), (0.40, 0.60, 3.72, 2.55), (1.20, 0.52, 3.58, 2.65),
             (2.10, 0.42, 3.62, 3.00), (3.00, 0.26, 3.72, 3.40), (3.35, 0.10, 3.76, 3.62)]
    body.add(loft([[np.array([x, y, z]) for x, y in hexagon(hw, top, bot)] for z, hw, top, bot in shell]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)

    strips = part("LightStrips")
    for sx in (-1, 1):
        strips.add(beam((sx * 0.64, 3.28, -0.40), (sx * 0.60, 3.22, 0.70), 0.04, 0.06, c=0.01), "LIGHT_STRIPS")
        strips.add(beam((sx * 0.55, 3.18, 0.70), (sx * 0.30, 3.60, 2.90), 0.04, 0.05, c=0.01), "LIGHT_STRIPS")
        strips.add(beam((sx * 0.96, 3.10, -2.35), (sx * 0.96, 2.92, -0.90), 0.04, 0.05, c=0.01), "LIGHT_STRIPS")

    lights = part("Headlights")
    bar = [(-0.26, 2.46), (0.26, 2.46), (0.30, 2.41), (0.26, 2.36), (-0.26, 2.36), (-0.30, 2.41)]
    lights.add(loft([[sp(x, t, n) for x, t in bar] for n in (1.34, 1.43)]), "HEADLIGHTS")

    shield = part("Windshield")
    plate = [sp(-0.42, 2.80, 1.05), sp(0.42, 2.80, 1.05), sp(0.30, 3.05, 0.84), sp(-0.30, 3.05, 0.84)]
    pn = unit(np.cross(plate[1] - plate[0], plate[2] - plate[0]))
    shield.add(loft([[p - 0.025 * pn for p in plate], [p + 0.025 * pn for p in plate]]), "WINDSHIELD")

    seat = part("Seat")
    cushion = [(0.10, 0.40, 0.07, 3.72), (0.60, 0.48, 0.09, 3.66), (1.30, 0.44, 0.09, 3.62), (1.70, 0.30, 0.07, 3.66)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.4, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([[np.array([x, y, z]) for x, y in hexagon(hw, 3.74, 3.60)] for z, hw in ((3.33, 0.13), (3.42, 0.10))]),
           "TAILLIGHT")

    frame = part("Frame")
    frame.add(cylinder(sp(0, 2.33, 0), sp(0, 2.73, 0), 0.17, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        frame.add(beam(sp(sx * 0.12, 2.50, -0.14), (sx * 0.30, 3.05, -0.55), 0.12, 0.22, c=0.03), "FRAME")
        frame.add(cylinder((sx * 0.42, 1.50, 0.38), (sx * 0.86, 1.50, 0.38), 0.08, 10, 0.03), "PEGS")
    frame.add(cbox((0, 1.75, -0.15), (0.40, 0.55, 0.75), 0.10), "BATTERY")
    frame.add(cbox((0, 2.55, 0.40), (0.30, 0.35, 0.40), 0.08), "BATTERY")

    motor = part("Motor")
    motor.add(cylinder(PIVOT - 0.32 * X, PIVOT + 0.32 * X, 0.38, 20, 0.06), "MOTOR")

    swing = part("Swingarm")
    swing.add(lathe(REAR_AXLE, [(-0.5 * REAR_HW, 0.38 * REAR_R), (0.5 * REAR_HW, 0.38 * REAR_R),
                                (0.5 * REAR_HW, 0.50 * REAR_R), (-0.5 * REAR_HW, 0.50 * REAR_R)], 32), "STATOR")
    bracket = REAR_AXLE + 0.40 * REAR_R * unit(np.array([0, 1.0, -0.6]))
    swing.add(cbox(bracket + np.array([0.52, 0, 0]), (0.23, 0.09, 0.12), 0.03), "STATOR")
    swing.add(beam((0.40, 1.60, 0.80), (0.78, 1.60, 1.08), 0.16, 0.36, c=0.05), "SWINGARM", [CHARTS["SWINGARM_R"]])
    swing.add(beam((0.78, 1.60, 1.02), (0.78, bracket[1], bracket[2]), 0.16, 0.36, 0.16, 0.26, c=0.05), "SWINGARM",
              [CHARTS["SWINGARM_R"]])
    swing.add(cylinder(PIVOT + 0.30 * X, PIVOT + 0.50 * X, 0.14, 12, 0.02), "SWINGARM")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "volt": dict(primary=(240, 244, 248), secondary=(30, 32, 38), accent=(0, 230, 255), number="E1",
                 blocks=dict(RIM_GLOW=(0, 230, 255), LIGHT_STRIPS=(0, 230, 255), DISPLAY=(0, 230, 255))),
    "nebula": dict(primary=(40, 20, 70), secondary=(120, 40, 200), accent=(255, 60, 220), number="77",
                   blocks=dict(PLASTIC=(40, 20, 70), RIM_GLOW=(255, 60, 220), LIGHT_STRIPS=(255, 60, 220),
                               DISPLAY=(255, 60, 220), RIM=(40, 20, 70))),
    "carbon": dict(primary=(34, 35, 40), secondary=(70, 72, 80), accent=(255, 40, 50), number="03",
                   blocks=dict(PLASTIC=(34, 35, 40), RIM_GLOW=(255, 40, 50), LIGHT_STRIPS=(255, 40, 50),
                               DISPLAY=(255, 40, 50))),
    "solar": dict(primary=(255, 130, 20), secondary=(250, 250, 250), accent=(255, 230, 80), number="88",
                  blocks=dict(PLASTIC=(255, 130, 20), RIM_GLOW=(255, 230, 80), LIGHT_STRIPS=(255, 230, 80),
                              DISPLAY=(255, 230, 80))),
    "aurora": dict(primary=(10, 60, 70), secondary=(20, 200, 150), accent=(120, 255, 200), number="42",
                   blocks=dict(PLASTIC=(10, 60, 70), RIM_GLOW=(120, 255, 200), LIGHT_STRIPS=(120, 255, 200),
                               DISPLAY=(120, 255, 200))),
    "synthwave": dict(primary=(255, 90, 180), secondary=(60, 30, 140), accent=(60, 220, 255), number="84",
                      blocks=dict(PLASTIC=(255, 90, 180), RIM_GLOW=(60, 220, 255), LIGHT_STRIPS=(60, 220, 255),
                                  DISPLAY=(60, 220, 255), RIM=(60, 30, 140))),
    "chrome": dict(primary=(196, 202, 212), secondary=(40, 42, 48), accent=(40, 120, 255), number="00",
                   blocks=dict(PLASTIC=(196, 202, 212), RIM_GLOW=(40, 120, 255), LIGHT_STRIPS=(40, 120, 255),
                               DISPLAY=(40, 120, 255), RIM=(196, 202, 212))),
    "venom": dict(primary=(20, 22, 20), secondary=(60, 64, 60), accent=(150, 255, 30), number="13",
                  blocks=dict(PLASTIC=(20, 22, 20), RIM_GLOW=(150, 255, 30), LIGHT_STRIPS=(150, 255, 30),
                              DISPLAY=(150, 255, 30))),
}


def paint_skin(pt, skin):
    pri, sec, acc = skin["primary"], skin["secondary"], skin["accent"]
    for side in ("BODY_R", "BODY_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        # Angular shards in side-view (z, y) studs, with a glow line along their edge.
        pt.world_poly(c, [(0, 0.0, -3.6), (0, 2.75, -3.6), (0, 2.95, -1.4), (0, 2.75, 0.4), (0, 3.20, 3.6), (0, 0.0, 3.6)], sec)
        pt.world_poly(c, [(0, 2.75, -3.6), (0, 2.95, -1.4), (0, 2.75, 0.4), (0, 3.20, 3.6), (0, 3.27, 3.6), (0, 2.82, 0.4),
                          (0, 3.02, -1.4), (0, 2.82, -3.6)], acc)
        pt.text_at(c, (0, 3.40, 1.30), skin["number"], acc, 0.30)
    c = CHARTS["BODY_TOP"]
    pt.fill(c, pri)
    pt.bands(c, [(0.47, 0.53, acc)])
    c = CHARTS["NOSE_FRONT"]
    pt.fill(c, pri)
    pt.poly(c, [(0.0, 0.35), (1.0, 0.35), (1.0, 0.75), (0.0, 0.75)], sec)   # dark visor band behind the light bar
    c = CHARTS["FRONT_FENDER"]
    pt.fill(c, pri)
    pt.bands(c, [(0.47, 0.53, acc)])
    c = CHARTS["SEAT"]
    pt.fill(c, (22, 22, 26))
    pt.bands(c, [(0.10, 0.14, acc), (0.86, 0.90, acc)])
    c = CHARTS["SWINGARM_R"]
    pt.fill(c, sec)
    pt.poly(c, [(0.0, 0.42), (1.0, 0.42), (1.0, 0.58), (0.0, 0.58)], acc)
    pt.blocks(dict(skin["blocks"], PLASTIC=skin["blocks"].get("PLASTIC", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_electric.py",
          "ElectricSkin", up_labels=("NOSE_FRONT",))
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=6)  # wheels are lathes


if __name__ == "__main__":
    main()
