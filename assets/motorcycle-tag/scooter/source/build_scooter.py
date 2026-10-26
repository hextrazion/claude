#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" scooter: a retro step-through with a skinnable UV layout.

Outputs (written to the scooter/ folder):
  MotorcycleTag_Scooter.glb   main file, with the Mint skin embedded
  MotorcycleTag_Scooter.obj   same parts as OBJ objects (+ .mtl -> skins/mint.png)
  skin_template.png           1024x1024 guide: every paintable area, labelled
  uv_overlay.png              transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png            example skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre. The leg
shield, floor and rear cowls are body parts; the single-sided fork, column cover, front
fender and headset (with the headlight) turn in front of the leg shield. The engine unit
on the right is the `Swingarm` part so the rig finds the rear axle.

Run:  python3 build_scooter.py          build everything
      python3 build_scooter.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, beam, cbox, check, cylinder, lathe, loft, ring, superellipse  # noqa: E402
from skinkit import (Atlas, Chart, SkinPart, build, fender_chart, front_chart, side_chart, side_panel,  # noqa: E402
                     spoked_wheel, top_chart)

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_Scooter"

# ---------------------------------------------------------------- layout
RAKE = math.radians(26.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

WHEEL_R, WHEEL_HW = 0.95, 0.36
FRONT_AXLE = np.array([0.0, WHEEL_R, -2.40])
REAR_AXLE = np.array([0.0, WHEEL_R, 2.25])
STEER_LOCK = math.radians(30.0)
FENDER_R = WHEEL_R + 0.10


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


def steer_coords(p):
    q = np.asarray(p) - FRONT_AXLE
    return q @ X, q @ D, q @ FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Mint colour
    ("TIRE", (34, 34, 37)), ("WHITEWALL", (245, 240, 225)), ("RIM", (205, 210, 218)), ("HUB", (205, 210, 218)),
    ("SPOKES", (205, 210, 218)), ("BRAKE", (150, 156, 164)), ("FORK", (60, 64, 70)), ("COLUMN", (60, 64, 70)),
    ("BARS", (205, 210, 218)), ("GRIPS", (36, 36, 40)), ("HEADLIGHT", (255, 248, 225)), ("TAILLIGHT", (255, 40, 52)),
    ("FLOOR", (54, 56, 60)), ("APRON_INNER", (150, 225, 200)), ("FRAME", (54, 56, 60)), ("ENGINE", (90, 94, 100)),
    ("EXHAUST", (205, 210, 218)), ("SEAT_SIDE", (120, 72, 44)), ("PAINT", (150, 225, 200)), ("TRIM", (205, 210, 218)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    front_chart("APRON_FRONT", "Leg shield (front)", 0.6),
    side_chart("SIDECOWL_R", "Side cowl right", 1, 0.35),
    side_chart("SIDECOWL_L", "Side cowl left", -1, 0.35),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FENDER_R),
    Chart("FRONT_COVER", "Column cover (front)", lambda n, c: n @ FWD > 0.5,
          lambda p: (-steer_coords(p)[0], steer_coords(p)[1]), "up"),
    front_chart("HEADSET", "Headset (front)", 0.55),
    top_chart("SEAT", "Seat (top)", 0.5),
)
CHARTS = ATLAS.charts


# ---------------------------------------------------------------- parts
def build_parts():
    parts = []

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels: small pressed-steel style
    spoked_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, WHEEL_R, WHEEL_HW, 5, 0.20, ((-0.33, -0.30),))
    spoked_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, WHEEL_R, WHEEL_HW, 5, 0.20)

    # ---------------- steering assembly
    fork = part("Fork", FRONT_AXLE, "Steer")
    fork.add(cbox(sp(-0.50, 0.65, 0), (0.08, 0.72, 0.10), 0.04, STEER_ROT), "FORK")      # single-sided leg
    fork.add(cylinder(FRONT_AXLE - 0.37 * X, FRONT_AXLE - 0.52 * X, 0.08, 10, 0.02), "FORK")
    fork.add(cbox(sp(-0.25, 1.40, 0), (0.33, 0.08, 0.12), 0.04, STEER_ROT), "FORK")      # crown
    fork.add(cylinder(sp(0, 1.40, 0), sp(0, 2.90, 0), 0.09, 12, 0.02), "COLUMN")
    fork.add(loft([ring(sp(0, t, 0.03), X, FWD, superellipse(a, b, 2.6, 16))
                   for t, a, b in ((1.50, 0.13, 0.09), (1.58, 0.17, 0.12), (2.62, 0.17, 0.12), (2.72, 0.13, 0.09))]),
             "PAINT", [CHARTS["FRONT_COVER"]])

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.40, FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.07), (fhw - 0.08, r0 + 0.14), (-fhw + 0.08, r0 + 0.14),
                                  (-fhw, r0 + 0.07)], 16, [0] * 6, arc=(RAKE - math.radians(75), RAKE + math.radians(24))),
               ["PAINT"], [CHARTS["FRONT_FENDER"]])

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    bars.add(loft([ring(sp(0, t, 0.05), X, FWD, superellipse(a, b, 2.4, 20))
                   for t, a, b in ((2.84, 0.30, 0.18), (2.94, 0.46, 0.26), (3.12, 0.44, 0.24), (3.22, 0.30, 0.15))]),
             "PAINT", [CHARTS["HEADSET"]])
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.36, 3.03, -0.02), sp(sx * 0.62, 3.02, -0.07), 0.06, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.60, 3.02, -0.06), sp(sx * 0.92, 3.00, -0.12), 0.09, 12, 0.03), "GRIPS")

    lamp = part("Headlight", FRONT_AXLE, "Steer")
    disc = [(0.15 * math.cos(a), 3.02 + 0.13 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 14, endpoint=False)]
    lamp.add(loft([[sp(x * k, 3.02 + (t - 3.02) * k, n) for x, t in disc] for n, k in ((0.26, 1.0), (0.33, 0.95),
                                                                                     (0.36, 0.72))]), "HEADLIGHT")

    # ---------------- body
    body = part("Bodywork")
    apron = []
    for y, zc, hw in ((0.86, -1.15, 0.70), (1.60, -1.20, 0.74), (2.40, -1.10, 0.66), (2.78, -1.02, 0.50)):
        us = np.linspace(-1, 1, 9)
        front = [np.array([hw * u, y, zc - 0.10 * (1 - u * u)]) for u in us]
        back = [np.array([hw * u, y, zc + 0.07 + 0.02 * (1 - u * u)]) for u in reversed(us)]
        apron.append(front + back)
    body.add(loft(apron), "APRON_INNER", [CHARTS["APRON_FRONT"]])
    side_panel(body, [(0.30, 2.08), (1.40, 2.22), (2.60, 2.18), (3.15, 1.80), (2.90, 1.15), (1.25, 1.05), (0.40, 1.30)],
               ((0.46, 0.92), (0.62, 1.0), (0.78, 0.96), (0.86, 0.80), (0.89, 0.55)), "PAINT",
               CHARTS["SIDECOWL_R"], CHARTS["SIDECOWL_L"])
    tail = [(0.25, 0.46, 0.16, 2.14), (1.40, 0.50, 0.17, 2.22), (2.60, 0.44, 0.16, 2.18), (3.10, 0.30, 0.12, 2.05),
            (3.22, 0.18, 0.08, 1.98)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.6, 16)) for z, a, b, cy in tail]), "PAINT")

    seat = part("Seat")
    cushion = [(0.30, 0.40, 0.10, 2.40), (0.90, 0.46, 0.13, 2.42), (1.70, 0.46, 0.13, 2.46), (2.30, 0.42, 0.12, 2.52),
               (2.55, 0.30, 0.08, 2.52)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.8, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])

    tl = part("TailLight")
    tl.add(loft([ring(np.array([0, 2.04, z]), X, Y, superellipse(a, b, 2.4, 12))
                 for z, a, b in ((3.14, 0.16, 0.07), (3.24, 0.15, 0.06), (3.27, 0.11, 0.045))]), "TAILLIGHT")

    frame = part("Frame")
    frame.add(cbox((0, 0.82, -0.30), (0.50, 0.06, 0.82), 0.03), "FLOOR")
    frame.add(cbox((0, 1.05, 0.66), (0.30, 0.22, 0.38), 0.06), "FRAME")
    for sx in (-1, 1):
        frame.add(beam((sx * 0.48, 0.90, -1.05), (sx * 0.48, 0.90, 0.48), 0.05, 0.05, c=0.01), "TRIM")   # floor rails

    engine = part("Swingarm")  # engine and swing arm unit on the right, named for the rig
    engine.add(cbox((0.58, 0.78, 1.35), (0.10, 0.20, 0.45), 0.06), "ENGINE")
    engine.add(beam((0.58, 0.80, 0.70), (0.58, 0.95, 2.25), 0.16, 0.24, c=0.05), "ENGINE")
    engine.add(cylinder(REAR_AXLE + 0.36 * X, REAR_AXLE + 0.66 * X, 0.09, 10, 0.02), "ENGINE")
    engine.add(cylinder((0.68, 0.66, 1.95), (0.68, 0.74, 2.85), 0.14, 12, 0.03), "EXHAUST")
    return parts


# ---------------------------------------------------------------- skins
SKINS = {
    "mint": dict(primary=(150, 225, 200), secondary=(250, 244, 228), accent=(200, 60, 50), seat=(120, 72, 44),
                 pattern="stripe", blocks={}),
    "bubblegum": dict(primary=(255, 160, 205), secondary=(255, 255, 255), accent=(255, 255, 255), seat=(255, 255, 255),
                      pattern="dots", blocks=dict(PAINT=(255, 160, 205), APRON_INNER=(255, 255, 255),
                                                  SEAT_SIDE=(255, 255, 255), WHITEWALL=(255, 255, 255))),
    "taxi": dict(primary=(255, 205, 20), secondary=(24, 24, 26), accent=(24, 24, 26), seat=(24, 24, 26),
                 pattern="checker", blocks=dict(PAINT=(255, 205, 20), APRON_INNER=(24, 24, 26), WHITEWALL=(34, 34, 37),
                                                SEAT_SIDE=(24, 24, 26))),
    "racer": dict(primary=(248, 248, 250), secondary=(220, 30, 40), accent=(30, 70, 200), seat=(30, 30, 34),
                  pattern="racing", number="5",
                  blocks=dict(PAINT=(248, 248, 250), APRON_INNER=(30, 70, 200), SEAT_SIDE=(30, 30, 34),
                              WHITEWALL=(34, 34, 37))),
}


def dots(pt, c, color, spacing=0.20):
    x, y, w, h = c.rect
    r = spacing * c.scale * 0.28
    step = spacing * c.scale
    row = 0
    yy = y - 10
    while yy < y + h + 10:
        xx = x - 10 + (step / 2 if row % 2 else 0)
        while xx < x + w + 10:
            pt.d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=color)
            xx += step
        yy += step * 0.87
        row += 1


def checker(pt, c, color, lo=0.40, hi=0.62, cells=2):
    """A checkered band across a side panel, `cells` squares tall."""
    x, y, w, h = c.rect
    _, y0 = c.frac_to_px(0, hi)
    _, y1 = c.frac_to_px(0, lo)
    size = (y1 - y0) / cells
    for j in range(cells):
        k = 0
        xx = x - 10
        while xx < x + w + 10:
            if (k + j) % 2 == 0:
                pt.d.rectangle([xx, y0 + j * size, xx + size, y0 + (j + 1) * size], fill=color)
            xx += size
            k += 1


def paint_skin(pt, skin):
    pri, sec, acc, pattern = skin["primary"], skin["secondary"], skin["accent"], skin["pattern"]
    for side in ("SIDECOWL_R", "SIDECOWL_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        if pattern == "stripe":
            pt.poly(c, [(0.0, 0.60), (1.0, 0.66), (1.0, 0.74), (0.0, 0.68)], acc)
        elif pattern == "dots":
            dots(pt, c, sec)
        elif pattern == "checker":
            checker(pt, c, sec)
        elif pattern == "racing":
            pt.poly(c, [(0.0, 0.30), (1.0, 0.55), (1.0, 0.68), (0.0, 0.43)], sec)
            pt.poly(c, [(0.0, 0.47), (1.0, 0.72), (1.0, 0.80), (0.0, 0.55)], acc)
            x, y, w, h = c.rect   # number roundel
            cx, cy = c.frac_to_px(0.42, 0.42)
            r = 0.26 * h
            pt.d.ellipse([cx - r * 1.12, cy - r * 1.12, cx + r * 1.12, cy + r * 1.12], fill=(24, 24, 26))
            pt.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(250, 250, 250))
            pt.number(c, skin["number"], (24, 24, 26), 0.36, 0.42)
    c = CHARTS["APRON_FRONT"]
    pt.fill(c, pri)
    if pattern == "dots":
        dots(pt, c, sec)
    elif pattern == "checker":
        checker(pt, c, sec, 0.10, 0.22)
    elif pattern == "racing":
        pt.bands(c, [(0.36, 0.46, sec), (0.54, 0.64, acc)])
        pt.number(c, skin["number"], (24, 24, 26), 0.30, 0.55)
    else:
        pt.poly(c, [(0.42, 0.0), (0.58, 0.0), (0.58, 1.0), (0.42, 1.0)], acc)   # centre "tie" stripe
    for name in ("FRONT_FENDER", "FRONT_COVER", "HEADSET"):
        c = CHARTS[name]
        pt.fill(c, pri)
        if pattern == "racing":
            pt.bands(c, [(0.30, 0.45, sec), (0.55, 0.70, acc)])
        elif pattern == "checker" and name == "FRONT_FENDER":
            pt.bands(c, [(0.40, 0.60, sec)])
        elif pattern == "stripe":
            pt.bands(c, [(0.46, 0.54, acc)])
        elif pattern == "dots":
            dots(pt, c, sec, 0.14)
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    pt.ribs(c, tuple(max(0, v - 30) for v in skin["seat"]), 6, 3)
    pt.blocks(dict(skin["blocks"], PAINT=skin["blocks"].get("PAINT", pri), APRON_INNER=skin["blocks"].get("APRON_INNER", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_scooter.py",
          "ScooterSkin", up_labels=("APRON_FRONT", "FRONT_COVER", "HEADSET"))
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=72)


if __name__ == "__main__":
    main()
