#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" police bike: a big touring patrol bike with a skinnable UV layout.

Outputs (written to the police/ folder):
  MotorcycleTag_Police.glb   main file, with the Highway skin embedded
  MotorcycleTag_Police.obj   same parts as OBJ objects (+ .mtl -> skins/highway.png)
  skin_template.png          1024x1024 guide: every paintable area, labelled
  uv_overlay.png             transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png           skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre. The big
fairing, headlights and windshield are fixed to the frame; the fork, bars and fender turn
behind them. The red and blue emergency lights are two parts, `LightsRed` and `LightsBlue`,
so the game can flash them (see MotorcycleRig.SetSirens). Markings are generic: no real
agency names, crests or numbers.

Run:  python3 build_police.py          build everything
      python3 build_police.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, catmull, cbox, check, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402
from skinkit import (Atlas, SkinPart, back_chart, build, fender_chart, front_chart, side_chart, side_panel,  # noqa: E402
                     spoked_wheel, top_chart)

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_Police"

# ---------------------------------------------------------------- layout
RAKE = math.radians(26.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.30, 0.44
REAR_R, REAR_HW = 1.32, 0.60
FRONT_AXLE = np.array([0.0, FRONT_R, -2.85])
REAR_AXLE = np.array([0.0, REAR_R, 2.75])
PIVOT = np.array([0.0, 1.60, 0.95])
STEER_LOCK = math.radians(30.0)
FENDER_R = FRONT_R + 0.10


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Highway colour
    ("TIRE", (32, 32, 35)), ("WHITEWALL", (32, 32, 35)), ("RIM", (40, 42, 48)), ("HUB", (40, 42, 48)),
    ("SPOKES", (40, 42, 48)), ("BRAKE", (170, 176, 184)), ("FORK", (205, 210, 218)), ("FORK_LOWER", (40, 42, 48)),
    ("CLAMPS", (40, 42, 48)), ("BARS", (40, 42, 48)), ("GRIPS", (20, 20, 22)), ("HEADLIGHTS", (235, 246, 255)),
    ("TAILLIGHT", (255, 40, 52)), ("WINDSHIELD", (70, 80, 92)), ("LIGHTS_RED", (255, 30, 40)),
    ("LIGHTS_BLUE", (30, 80, 255)), ("FRAME", (40, 42, 48)), ("ENGINE", (60, 64, 72)), ("EXHAUST", (190, 196, 204)),
    ("SWINGARM", (40, 42, 48)), ("CASES", (245, 245, 245)), ("RACK", (40, 42, 48)), ("PEGS", (40, 42, 48)),
    ("SEAT_SIDE", (24, 24, 28)), ("PLASTIC", (245, 245, 245)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    side_chart("BODY_R", "Bodywork right side", 1, 0.35),
    side_chart("BODY_L", "Bodywork left side", -1, 0.35),
    top_chart("BODY_TOP", "Fairing, tank and tail (top)", 0.55),
    front_chart("NOSE_FRONT", "Fairing (front)", 0.6),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FENDER_R),
    top_chart("SEAT", "Seat (top)", 0.5),
    side_chart("CASE_R", "Side case right", 1, 0.6),
    side_chart("CASE_L", "Side case left", -1, 0.6),
    back_chart("TOPCASE_BACK", "Top box (back)", 0.6),
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

    # ---------------- wheels: chunky five-spoke cast wheels
    spoked_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW, 5, 0.20,
                 ((-0.37, -0.34), (0.34, 0.37)))
    spoked_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW, 5, 0.20, ((-0.50, -0.47),))

    # ---------------- steering assembly: fork, bars, fender
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.62
        fork.add(cylinder(sp(x, -0.08, 0), sp(x, 1.20, 0), 0.12, 12, 0.03), "FORK_LOWER")
        fork.add(cylinder(sp(x, 1.10, 0), sp(x, 2.95, 0), 0.10, 12, 0.02), "FORK")
        fork.add(cylinder(FRONT_AXLE + sx * 0.43 * X, FRONT_AXLE + sx * 0.72 * X, 0.07, 10, 0.02), "FORK_LOWER")
    fork.add(cbox(sp(0, 2.30, 0), (0.74, 0.08, 0.18), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 2.85, 0), (0.72, 0.07, 0.18), 0.05, STEER_ROT), "CLAMPS")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.24, 2.92, 0), sp(sx * 0.24, 3.36, -0.04), 0.07, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.76, 3.43, -0.28), sp(sx * 0.96, 3.46, -0.40), 0.095, 12, 0.03), "GRIPS")
    bars.add(tube(catmull([sp(-0.80, 3.43, -0.30), sp(-0.55, 3.40, -0.16), sp(-0.24, 3.36, -0.05), sp(0.24, 3.36, -0.05),
                           sp(0.55, 3.40, -0.16), sp(0.80, 3.43, -0.30)], 4), 0.07, 10, bevel=0.02), "BARS")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.40, FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.07), (fhw - 0.08, r0 + 0.13), (-fhw + 0.08, r0 + 0.13),
                                  (-fhw, r0 + 0.07)], 14, [0] * 6, arc=(RAKE - math.radians(55), RAKE + math.radians(25))),
               ["PLASTIC"], [CHARTS["FRONT_FENDER"]])

    # ---------------- bodywork (fixed to the frame)
    body = part("Bodywork")
    cowl = [(-0.95, 2.70), (-0.55, 2.92), (0.55, 2.92), (0.95, 2.70), (0.92, 1.95), (0.50, 1.65), (-0.50, 1.65), (-0.92, 1.95)]
    tc = 2.30
    body.add(loft([[sp(x * k, tc + (t - tc) * k, n) for x, t in cowl] for n, k in ((0.86, 1.0), (1.10, 0.96), (1.30, 0.84),
                                                                                (1.40, 0.66))]),
             "PLASTIC", [CHARTS["NOSE_FRONT"], CHARTS["BODY_TOP"]] + sides)
    side_panel(body, [(-2.95, 4.05), (-1.55, 3.75), (-0.95, 3.30), (-0.85, 2.30), (-1.50, 1.95), (-2.40, 2.40), (-2.95, 3.10)],
               ((0.92, 1.0), (1.04, 1.0), (1.09, 0.95)), "PLASTIC", *sides)
    side_panel(body, [(-1.50, 1.95), (-0.85, 2.30), (-0.10, 2.00), (0.10, 1.25), (-0.30, 0.82), (-1.35, 0.98)],
               ((0.62, 1.0), (0.80, 1.0), (0.86, 0.95)), "PLASTIC", *sides)
    side_panel(body, [(0.40, 3.40), (1.70, 3.45), (2.00, 3.15), (1.70, 2.80), (0.55, 2.75), (0.30, 3.05)],
               ((0.36, 1.0), (0.52, 1.0), (0.57, 0.92)), "PLASTIC", *sides)                       # side covers
    tank = [(-1.05, 0.30, 0.18, 3.62), (-0.85, 0.56, 0.32, 3.62), (-0.40, 0.74, 0.40, 3.55), (0.10, 0.70, 0.36, 3.45),
            (0.40, 0.50, 0.24, 3.36), (0.50, 0.28, 0.10, 3.34)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 20)) for z, a, b, cy in tank]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)
    tail = [(1.70, 0.50, 0.22, 3.42), (2.50, 0.46, 0.20, 3.48), (3.05, 0.36, 0.16, 3.50), (3.15, 0.28, 0.10, 3.50)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 16)) for z, a, b, cy in tail]), "PLASTIC",
             [CHARTS["BODY_TOP"]] + sides)

    lights = part("Headlights")
    for sx in (-1, 1):
        lens = [(0.12, 2.48), (0.28, 2.52), (0.42, 2.46), (0.38, 2.32), (0.14, 2.32)]
        lights.add(loft([[sp(sx * x, t, n) for x, t in lens] for n in (1.34, 1.46)]), "HEADLIGHTS")

    shield = part("Windshield")
    plate = [sp(-0.58, 2.88, 1.00), sp(0.58, 2.88, 1.00), sp(0.52, 3.30, 0.80), sp(0.36, 3.62, 0.62), sp(-0.36, 3.62, 0.62),
             sp(-0.52, 3.30, 0.80)]
    pn = unit(np.cross(plate[1] - plate[0], plate[3] - plate[0]))
    shield.add(loft([[p - 0.025 * pn for p in plate], [p + 0.025 * pn for p in plate]]), "WINDSHIELD")

    seat = part("Seat")
    cushion = [(-0.10, 0.40, 0.12, 3.62), (0.40, 0.56, 0.16, 3.60), (1.10, 0.58, 0.16, 3.60), (1.60, 0.50, 0.14, 3.74),
               (2.15, 0.48, 0.13, 3.78), (2.40, 0.34, 0.08, 3.76)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.0, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.48, z]), X, Y, superellipse(a, b, 2.4, 12))
                 for z, a, b in ((3.13, 0.20, 0.07), (3.20, 0.19, 0.06), (3.23, 0.15, 0.045))]), "TAILLIGHT")

    cases = part("Panniers")
    for sx in (-1, 1):
        cases.add(cbox((sx * 0.95, 2.40, 2.35), (0.24, 0.48, 0.62), 0.10), "CASES",
                  [CHARTS["CASE_R" if sx > 0 else "CASE_L"]])
    cases.add(cbox((0, 4.02, 2.85), (0.42, 0.30, 0.36), 0.08), "CASES", [CHARTS["TOPCASE_BACK"]])
    cases.add(cylinder((0, 4.30, 3.05), (0, 4.86, 3.08), 0.04, 8, 0.01), "RACK")                   # light bar pole
    cases.add(cbox((0, 4.90, 3.08), (0.32, 0.03, 0.05), 0.01), "RACK")
    cases.add(cylinder((0.30, 3.70, 3.05), (0.30, 5.10, 3.10), 0.015, 6, 0.0), "RACK")              # radio antenna

    red = part("LightsRed")
    blue = part("LightsBlue")
    for lamp, sx, block in ((red, -1, "LIGHTS_RED"), (blue, 1, "LIGHTS_BLUE")):
        lamp.add(cbox((sx * 0.17, 5.00, 3.08), (0.14, 0.08, 0.07), 0.03), block)                    # rear light bar
        lamp.add(loft([[sp(sx * x, t, n) for x, t in ((0.36, 2.06), (0.56, 2.06), (0.54, 1.96), (0.38, 1.96))]
                       for n in (1.33, 1.46)]), block)                                               # front strobes
        lamp.add(cbox((sx * 0.95, 2.70, 2.99), (0.10, 0.05, 0.03), 0.01), block)                    # rear case strobes

    frame = part("Frame")
    frame.add(cylinder(sp(0, 2.43, 0), sp(0, 2.73, 0), 0.18, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        frame.add(cbox((sx * 0.56, 1.85, 0.95), (0.07, 0.45, 0.22), 0.04), "FRAME")
        frame.add(cylinder((sx * 0.50, 1.40, 0.45), (sx * 0.92, 1.40, 0.45), 0.09, 10, 0.03), "PEGS")
        frame.add(cbox((sx * 0.62, 2.95, 2.30), (0.07, 0.06, 0.70), 0.02), "RACK")                  # case rails
    frame.add(cbox((0, 3.10, 1.60), (0.36, 0.20, 1.20), 0.05), "FRAME")                              # hidden subframe

    engine = part("Engine")
    engine.add(cbox((0, 1.40, -0.30), (0.55, 0.45, 0.70), 0.12), "ENGINE")
    tilt = rotation(X, math.radians(-30))
    engine.add(cbox(np.array([0, 2.10, -0.62]), (0.50, 0.38, 0.30), 0.07, tilt), "ENGINE")

    exhaust = part("Exhaust")
    exhaust.add(tube(catmull([(0.30, 2.00, -1.00), (0.50, 1.10, -0.90), (0.70, 0.95, 0.00), (0.98, 1.25, 0.95),
                              (1.06, 1.50, 1.32)], 4), 0.09, 10, bevel=0.02), "EXHAUST")
    m0, m1 = np.array([1.06, 1.52, 1.30]), np.array([1.06, 1.58, 2.60])
    ax = unit(m1 - m0)
    u = unit(np.cross(Y, ax))
    v = np.cross(ax, u)
    exhaust.add(loft([ring(m0, u, v, superellipse(0.12, 0.12, 2.4, 12)), ring(m0 + 0.2 * ax, u, v,
                                                                              superellipse(0.17, 0.16, 2.4, 12)),
                      ring(m1, u, v, superellipse(0.15, 0.14, 2.4, 12))]), "EXHAUST")

    swing = part("Swingarm")
    swing.add(cylinder(PIVOT - 0.86 * X, PIVOT + 0.86 * X, 0.11, 12, 0.03), "SWINGARM")
    for sx in (-1, 1):
        swing.add(cylinder((sx * 0.76, 1.60, 0.88), (sx * 0.76, 1.32, 2.90), 0.10, 10, 0.03), "SWINGARM")
        swing.add(cylinder(REAR_AXLE + sx * 0.57 * X, REAR_AXLE + sx * 0.88 * X, 0.08, 10, 0.02), "SWINGARM")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "highway": dict(primary=(245, 245, 245), band=((20, 40, 120), (245, 245, 245)), word="POLICE", word_color=(20, 40, 120),
                    seat=(24, 24, 28), blocks=dict(CASES=(245, 245, 245))),
    "metro": dict(primary=(22, 22, 26), lower=(245, 245, 245), word="POLICE", word_color=(22, 22, 26),
                  seat=(22, 22, 26), blocks=dict(CASES=(22, 22, 26), PLASTIC=(22, 22, 26))),
    "battenburg": dict(primary=(250, 250, 250), band=((40, 70, 200), (215, 255, 30)), word="POLICE",
                       word_color=(40, 70, 200), seat=(24, 24, 28), blocks=dict(CASES=(250, 250, 250))),
    "sheriff": dict(primary=(250, 248, 240), lower=(40, 70, 50), word="SHERIFF", word_color=(40, 70, 50),
                    star=(210, 170, 60), seat=(30, 26, 22), blocks=dict(CASES=(250, 248, 240))),
    "interceptor": dict(primary=(16, 22, 40), stripe=(200, 210, 225), word="PATROL", word_color=(200, 210, 225),
                        seat=(16, 18, 24), blocks=dict(CASES=(16, 22, 40), PLASTIC=(16, 22, 40))),
    "ranger": dict(primary=(70, 90, 60), lower=(200, 180, 130), word="RANGER", word_color=(245, 235, 200),
                   seat=(40, 32, 24), blocks=dict(CASES=(70, 90, 60), PLASTIC=(70, 90, 60))),
    "tactical": dict(primary=(70, 72, 76), stripe=(30, 30, 34), word="TACTICAL", word_color=(30, 30, 34),
                     seat=(26, 26, 30), blocks=dict(CASES=(50, 52, 56), PLASTIC=(70, 72, 76), FORK=(50, 52, 56))),
    "unmarked": dict(primary=(28, 28, 32), word=None, seat=(22, 22, 26),
                     blocks=dict(CASES=(28, 28, 32), PLASTIC=(28, 28, 32), LIGHTS_RED=(60, 30, 34),
                                 LIGHTS_BLUE=(30, 34, 60))),
}


def world_checker(pt, c, z0, z1, y0, y1, colours, rows=2):
    """Checkered band in side-view (z, y) studs."""
    size = (y1 - y0) / rows
    k = 0
    z = z0
    while z < z1:
        for r in range(rows):
            col = colours[(k + r) % 2]
            ya = y0 + r * size
            pt.world_poly(c, [(0, ya, z), (0, ya, z + size), (0, ya + size, z + size), (0, ya + size, z)], col)
        z += size
        k += 1


def star(pt, cx, cy, R, color):
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        r = R if k % 2 == 0 else R * 0.42
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pt.d.polygon(pts, fill=color)


def paint_skin(pt, skin):
    pri = skin["primary"]
    word = skin.get("word")
    for side in ("BODY_R", "BODY_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        if "lower" in skin:   # two-tone: lower half in a second colour
            pt.world_poly(c, [(0, 0.0, -4.5), (0, 2.75, -4.5), (0, 2.75, 3.5), (0, 0.0, 3.5)], skin["lower"])
        if "band" in skin:    # checkered band running nose to tail
            world_checker(pt, c, -4.5, 3.5, 2.50, 2.90, skin["band"])
        if "stripe" in skin:
            pt.world_poly(c, [(0, 2.70, -4.5), (0, 2.70, 3.5), (0, 2.82, 3.5), (0, 2.82, -4.5)], skin["stripe"])
        if word:
            pt.text_at(c, (0, 3.30, -1.95), word, skin["word_color"], 0.30)
        if "star" in skin:
            x, y = c.world_to_px((0, 3.30, -0.40))
            star(pt, x, y, 0.28 * c.scale, skin["star"])
    c = CHARTS["BODY_TOP"]
    pt.fill(c, pri)
    c = CHARTS["NOSE_FRONT"]
    pt.fill(c, pri)
    if word:
        pt.number(c, word, skin["word_color"], 0.12, 0.82)
    c = CHARTS["FRONT_FENDER"]
    pt.fill(c, pri)
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    case_colour = skin["blocks"].get("CASES", pri)
    for side in ("CASE_R", "CASE_L"):
        c = CHARTS[side]
        pt.fill(c, case_colour)
        if "band" in skin:
            x, y, w, h = c.rect
            size = h * 0.16
            for k in range(int(w / size) + 2):
                for r in range(2):
                    xx, yy = x - 10 + k * size, y + h * 0.42 + r * size
                    pt.d.rectangle([xx, yy, xx + size, yy + size], fill=skin["band"][(k + r) % 2])
        elif "lower" in skin:
            pt.poly(c, [(0.0, 0.0), (1.0, 0.0), (1.0, 0.45), (0.0, 0.45)], skin["lower"])
        if word:
            pt.number(c, word, skin["word_color"] if "band" not in skin else skin["band"][0], 0.14, 0.80)
    c = CHARTS["TOPCASE_BACK"]
    pt.fill(c, case_colour)
    if word:
        pt.number(c, word, skin["word_color"], 0.24, 0.55)
    pt.blocks(dict(skin["blocks"], PLASTIC=skin["blocks"].get("PLASTIC", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_police.py",
          "PoliceSkin", up_labels=("NOSE_FRONT", "TOPCASE_BACK"))
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=72)


if __name__ == "__main__":
    main()
