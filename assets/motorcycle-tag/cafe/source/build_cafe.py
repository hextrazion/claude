#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" café racer: retro, low and lean, with a skinnable UV layout.

Outputs (written to the cafe/ folder):
  MotorcycleTag_Cafe.glb   main file, with the British Green skin embedded
  MotorcycleTag_Cafe.obj   same parts as OBJ objects (+ .mtl -> skins/british_green.png)
  skin_template.png        1024x1024 guide: every paintable area, labelled
  uv_overlay.png           transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png         skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre.

Run:  python3 build_cafe.py          build everything
      python3 build_cafe.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, beam, catmull, cbox, check, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402
from skinkit import (Atlas, SkinPart, build, fender_chart, side_chart, side_panel, spoked_wheel,  # noqa: E402
                     top_chart)

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_Cafe"

# ---------------------------------------------------------------- layout
RAKE = math.radians(25.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.32, 0.38
REAR_R, REAR_HW = 1.36, 0.50
FRONT_AXLE = np.array([0.0, FRONT_R, -2.70])
REAR_AXLE = np.array([0.0, REAR_R, 2.60])
PIVOT = np.array([0.0, 1.55, 0.90])
STEER_LOCK = math.radians(30.0)
FENDER_R = FRONT_R + 0.10


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, British Green colour
    ("TIRE", (32, 32, 35)), ("WHITEWALL", (32, 32, 35)), ("RIM", (205, 210, 218)), ("HUB", (205, 210, 218)),
    ("SPOKES", (205, 210, 218)), ("BRAKE", (150, 156, 164)), ("FORK", (205, 210, 218)), ("FORK_LOWER", (180, 186, 194)),
    ("CLAMPS", (40, 42, 46)), ("BARS", (40, 42, 46)), ("GRIPS", (60, 40, 28)), ("HEADLIGHT", (255, 246, 220)),
    ("LIGHT_BUCKET", (205, 210, 218)), ("TAILLIGHT", (255, 40, 52)), ("FRAME", (30, 30, 34)), ("ENGINE", (70, 74, 80)),
    ("CYLINDERS", (150, 156, 164)), ("ENGINE_ACCENT", (205, 210, 218)), ("EXHAUST", (205, 210, 218)),
    ("SWINGARM", (30, 30, 34)), ("SHOCKS", (40, 42, 46)), ("SPRINGS", (205, 210, 218)), ("PEGS", (40, 42, 46)),
    ("SEAT_SIDE", (60, 40, 28)), ("PAINT", (20, 80, 50)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    side_chart("BODY_R", "Tank and cowl right side", 1, 0.35),
    side_chart("BODY_L", "Tank and cowl left side", -1, 0.35),
    top_chart("BODY_TOP", "Tank and cowl (top)", 0.55),
    side_chart("SIDECOVER_R", "Number plate right", 1),
    side_chart("SIDECOVER_L", "Number plate left", -1),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FENDER_R),
    top_chart("SEAT", "Seat (top)", 0.5),
)
CHARTS = ATLAS.charts


def finned_cylinder(part, base, axis, length, r_in, r_out, fins=5):
    """A cylinder barrel with chunky cooling fins along `axis`."""
    pts, radii = [], []
    for k in range(fins * 2 + 1):
        a = length * k / (fins * 2)
        for da in (-0.03, 0.03):
            pts.append(base + (a + da) * axis)
            radii.append(r_out if k % 2 else r_in)
    part.add(tube(pts[1:-1], radii[1:-1], 12), "CYLINDERS")


# ---------------------------------------------------------------- parts
def build_parts():
    parts = []
    sides = [CHARTS["BODY_R"], CHARTS["BODY_L"]]

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels: classic wire spokes
    spoked_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW, 16, 0.05, ((-0.35, -0.32),))
    spoked_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW, 16, 0.05)

    # ---------------- steering assembly: fork with headlight bucket, clip-ons, short fender
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.55
        fork.add(cylinder(sp(x, -0.06, 0), sp(x, 1.10, 0), 0.12, 12, 0.03), "FORK_LOWER")
        fork.add(cylinder(sp(x, 1.00, 0), sp(x, 2.76, 0), 0.09, 12, 0.02), "FORK")
        fork.add(cylinder(FRONT_AXLE + sx * 0.38 * X, FRONT_AXLE + sx * 0.60 * X, 0.07, 10, 0.02), "FORK_LOWER")
        fork.add(beam(sp(sx * 0.46, 2.30, 0.05), sp(sx * 0.22, 2.30, 0.36), 0.05, 0.06, c=0.01), "LIGHT_BUCKET")
    fork.add(cbox(sp(0, 2.15, 0), (0.66, 0.08, 0.17), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 2.68, 0), (0.64, 0.07, 0.17), 0.05, STEER_ROT), "CLAMPS")
    bucket = [(0.27 * math.cos(a), 2.30 + 0.27 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)]
    fork.add(loft([[sp(x * k, 2.30 + (t - 2.30) * k, n) for x, t in bucket] for n, k in ((0.30, 0.70), (0.38, 1.0),
                                                                                        (0.62, 1.06))]), "LIGHT_BUCKET")

    lamp = part("Headlight", FRONT_AXLE, "Steer")
    lamp.add(loft([[sp(x * k, 2.30 + (t - 2.30) * k, n) for x, t in bucket] for n, k in ((0.60, 0.98), (0.66, 0.92),
                                                                                        (0.69, 0.66))]), "HEADLIGHT")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.55, 2.44, 0), sp(sx * 0.55, 2.58, 0), 0.13, 12, 0.02), "BARS")      # clip-on clamp
        bars.add(cylinder(sp(sx * 0.62, 2.52, -0.03), sp(sx * 0.84, 2.48, -0.16), 0.055, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.80, 2.485, -0.13), sp(sx * 1.02, 2.45, -0.25), 0.09, 12, 0.03), "GRIPS")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.30, FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.05), (fhw - 0.06, r0 + 0.10), (-fhw + 0.06, r0 + 0.10),
                                  (-fhw, r0 + 0.05)], 12, [0] * 6, arc=(RAKE - math.radians(40), RAKE + math.radians(30))),
               ["PAINT"], [CHARTS["FRONT_FENDER"]])

    # ---------------- body
    body = part("Bodywork")
    tank = [(-1.20, 0.22, 0.14, 3.42), (-1.02, 0.42, 0.26, 3.44), (-0.64, 0.60, 0.34, 3.42), (-0.08, 0.64, 0.34, 3.36),
            (0.40, 0.56, 0.28, 3.30), (0.58, 0.32, 0.12, 3.26)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.4, 20)) for z, a, b, cy in tank]), "PAINT",
             [CHARTS["BODY_TOP"]] + sides)
    cowl = [(1.55, 0.44, 0.16, 3.28), (1.90, 0.46, 0.26, 3.38), (2.40, 0.40, 0.24, 3.40), (2.70, 0.30, 0.18, 3.38),
            (2.78, 0.20, 0.10, 3.36)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 18)) for z, a, b, cy in cowl]), "PAINT",
             [CHARTS["BODY_TOP"]] + sides)
    side_panel(body, [(0.40, 3.05), (1.05, 3.05), (1.20, 2.75), (1.05, 2.45), (0.40, 2.45), (0.25, 2.75)],
               ((0.30, 1.0), (0.44, 1.0), (0.48, 0.90)), "PAINT", CHARTS["SIDECOVER_R"], CHARTS["SIDECOVER_L"])

    seat = part("Seat")
    cushion = [(0.45, 0.36, 0.08, 3.18), (0.80, 0.46, 0.10, 3.18), (1.40, 0.46, 0.10, 3.20), (1.65, 0.38, 0.08, 3.22)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 3.0, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 3.36, z]), X, Y, superellipse(a, b, 2.0, 14)) for z, a, b in
                 ((2.76, 0.10, 0.07), (2.84, 0.09, 0.06), (2.87, 0.07, 0.045))]), "TAILLIGHT")

    frame = part("Frame")
    frame.add(cylinder(sp(0, 2.29, 0), sp(0, 2.56, 0), 0.17, 14, 0.03), "FRAME")
    for sx in (-1, 1):
        rails = [sp(sx * 0.12, 2.40, -0.12), sp(sx * 0.18, 2.30, -0.62), (sx * 0.28, 0.90, -0.85), (sx * 0.28, 0.85, 0.55),
                 (sx * 0.30, 1.95, 0.85), (sx * 0.32, 3.05, 0.45)]
        frame.add(tube(rails, 0.07, 8), "FRAME")                                                     # cradle loop
        frame.add(tube([sp(sx * 0.10, 2.48, -0.12), (sx * 0.32, 3.05, 0.45), (sx * 0.30, 3.12, 2.55)], 0.07, 8), "FRAME")
        frame.add(beam((sx * 0.30, 3.08, 1.95), (sx * 0.74, 3.00, 1.95), 0.07, 0.08, c=0.02), "FRAME")  # shock mount
        frame.add(cylinder((sx * 0.48, 1.60, 0.62), (sx * 0.90, 1.60, 0.62), 0.08, 10, 0.03), "PEGS")

    engine = part("Engine")
    engine.add(cbox((0, 1.40, -0.20), (0.42, 0.42, 0.62), 0.14), "ENGINE")
    lean = rotation(X, math.radians(-15))
    for sx in (-0.20, 0.20):
        finned_cylinder(engine, np.array([sx, 1.76, -0.42]), lean @ Y, 0.72, 0.17, 0.23)
    engine.add(cbox(np.array([0, 1.76, -0.42]) + 0.80 * (lean @ Y), (0.44, 0.09, 0.24), 0.05, lean), "ENGINE_ACCENT")
    engine.add(cylinder((0.40, 1.30, -0.05), (0.52, 1.30, -0.05), 0.30, 16, 0.05), "ENGINE_ACCENT")
    engine.add(cylinder((-0.40, 1.30, -0.05), (-0.52, 1.30, -0.05), 0.30, 16, 0.05), "ENGINE_ACCENT")

    exhaust = part("Exhaust")
    for sx in (-1, 1):
        exhaust.add(tube(catmull([(sx * 0.20, 2.15, -0.75), (sx * 0.45, 1.40, -0.95), (sx * 0.58, 1.00, -0.40),
                                  (sx * 0.66, 0.98, 0.50)], 4), 0.085, 10, bevel=0.02), "EXHAUST")
        m0, m1 = np.array([sx * 0.66, 0.98, 0.48]), np.array([sx * 0.80, 1.12, 2.00])
        ax = unit(m1 - m0)
        u = unit(np.cross(Y, ax))
        v = np.cross(ax, u)
        exhaust.add(loft([ring(m0, u, v, superellipse(0.09, 0.09, 2, 12)), ring(m0 + 0.3 * (m1 - m0), u, v,
                                                                                superellipse(0.12, 0.12, 2, 12)),
                          ring(m1 - 0.05 * ax, u, v, superellipse(0.19, 0.19, 2, 12)),
                          ring(m1, u, v, superellipse(0.15, 0.15, 2, 12))]), "EXHAUST")

    swing = part("Swingarm")
    swing.add(cylinder(PIVOT - 0.74 * X, PIVOT + 0.74 * X, 0.10, 12, 0.03), "SWINGARM")
    for sx in (-1, 1):
        swing.add(cylinder((sx * 0.66, 1.55, 0.86), (sx * 0.66, 1.36, 2.80), 0.08, 10, 0.03), "SWINGARM")
        swing.add(cylinder(REAR_AXLE + sx * 0.48 * X, REAR_AXLE + sx * 0.76 * X, 0.08, 10, 0.02), "SWINGARM")
        top, bottom = np.array([sx * 0.74, 3.00, 1.95]), np.array([sx * 0.74, 1.50, 2.25])
        swing.add(cylinder(bottom, top, 0.06, 10, 0.02), "SHOCKS")
        swing.add(cylinder(bottom + 0.15 * (top - bottom), bottom + 0.80 * (top - bottom), 0.12, 12, 0.02), "SPRINGS")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "british_green": dict(primary=(20, 80, 50), stripe=(240, 230, 200), plate=(240, 230, 200), number="7",
                          number_color=(20, 80, 50), seat=(60, 40, 28), style="stripe", blocks={}),
    "silver_bullet": dict(primary=(196, 202, 210), stripe=(24, 24, 28), plate=(24, 24, 28), number="1",
                          number_color=(240, 240, 240), seat=(24, 24, 28), style="stripe",
                          blocks=dict(PAINT=(196, 202, 210), SEAT_SIDE=(24, 24, 28), GRIPS=(24, 24, 28))),
    "rocker": dict(primary=(22, 22, 25), stripe=(245, 245, 245), plate=(245, 245, 245), number="59",
                   number_color=(22, 22, 25), seat=(22, 22, 25), style="checker",
                   blocks=dict(PAINT=(22, 22, 25), SEAT_SIDE=(22, 22, 25), GRIPS=(22, 22, 25), WHITEWALL=(240, 240, 240))),
    "cream": dict(primary=(242, 232, 205), stripe=(190, 30, 40), plate=(190, 30, 40), number="3",
                  number_color=(242, 232, 205), seat=(120, 30, 30), style="stripe",
                  blocks=dict(PAINT=(242, 232, 205), SEAT_SIDE=(120, 30, 30), GRIPS=(120, 30, 30))),
    "midnight": dict(primary=(16, 26, 60), stripe=(220, 180, 70), plate=(220, 180, 70), number="9",
                     number_color=(16, 26, 60), seat=(30, 22, 18), style="pinstripe",
                     blocks=dict(PAINT=(16, 26, 60), RIM=(220, 180, 70), SPOKES=(205, 210, 218))),
    "brat": dict(primary=(150, 120, 80), stripe=(60, 45, 30), plate=(60, 45, 30), number="22",
                 number_color=(220, 200, 160), seat=(80, 55, 35), style="plain",
                 blocks=dict(PAINT=(150, 120, 80), RIM=(30, 30, 34), SPOKES=(30, 30, 34), HUB=(30, 30, 34),
                             EXHAUST=(40, 40, 44), LIGHT_BUCKET=(30, 30, 34), FORK=(30, 30, 34), ENGINE_ACCENT=(60, 62, 66))),
    "racing_red": dict(primary=(200, 20, 30), stripe=(250, 250, 250), plate=(250, 250, 250), number="12",
                       number_color=(200, 20, 30), seat=(24, 24, 28), style="stripe",
                       blocks=dict(PAINT=(200, 20, 30), SEAT_SIDE=(24, 24, 28), GRIPS=(24, 24, 28))),
    "petrol": dict(primary=(20, 110, 120), stripe=(255, 140, 30), plate=(255, 140, 30), number="45",
                   number_color=(20, 50, 60), seat=(40, 30, 24), style="stripe",
                   blocks=dict(PAINT=(20, 110, 120), RIM=(255, 140, 30))),
}


def checker_band(pt, c, color, lo, hi, cells=2):
    x, y, w, h = c.rect
    _, y0 = c.frac_to_px(0, hi)
    _, y1 = c.frac_to_px(0, lo)
    size = (y1 - y0) / cells
    for j in range(cells):
        k, xx = 0, x - 10
        while xx < x + w + 10:
            if (k + j) % 2 == 0:
                pt.d.rectangle([xx, y0 + j * size, xx + size, y0 + (j + 1) * size], fill=color)
            xx += size
            k += 1


def paint_skin(pt, skin):
    pri, stripe, style = skin["primary"], skin["stripe"], skin["style"]
    for side in ("BODY_R", "BODY_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        if style == "stripe":   # a racing band along the tank and cowl
            pt.world_poly(c, [(0, 3.22, -1.40), (0, 3.22, 2.90), (0, 3.34, 2.90), (0, 3.34, -1.40)], stripe)
        elif style == "pinstripe":
            for y0 in (3.22, 3.34):
                pt.world_poly(c, [(0, y0, -1.40), (0, y0, 2.90), (0, y0 + 0.025, 2.90), (0, y0 + 0.025, -1.40)], stripe)
        elif style == "checker":
            checker_band(pt, c, stripe, 0.48, 0.66)
    c = CHARTS["BODY_TOP"]
    pt.fill(c, pri)
    if style != "plain":
        pt.bands(c, [(0.42, 0.47, stripe), (0.53, 0.58, stripe)])
    for side in ("SIDECOVER_R", "SIDECOVER_L"):   # number roundel
        c = CHARTS[side]
        pt.fill(c, pri)
        x, y, w, h = c.rect
        cx, cy = c.frac_to_px(0.5, 0.5)
        pt.d.ellipse([cx - 0.40 * w, cy - 0.42 * h, cx + 0.40 * w, cy + 0.42 * h], fill=skin["plate"])
        pt.number(c, skin["number"], skin["number_color"], 0.56, 0.5)
    c = CHARTS["FRONT_FENDER"]
    pt.fill(c, pri)
    if style != "plain":
        pt.bands(c, [(0.44, 0.56, stripe)])
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    pt.ribs(c, tuple(min(255, v + 25) for v in skin["seat"]), 7, 3)
    pt.blocks(dict(skin["blocks"], PAINT=skin["blocks"].get("PAINT", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_cafe.py", "CafeSkin")
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=24)


if __name__ == "__main__":
    main()
