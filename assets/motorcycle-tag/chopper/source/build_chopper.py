#!/usr/bin/env python3
"""Builds the "Motorcycle Tag" chopper: long, low, raked-out, with a skinnable UV layout.

Outputs (written to the chopper/ folder):
  MotorcycleTag_Chopper.glb   main file, with the Outlaw skin embedded
  MotorcycleTag_Chopper.obj   same parts as OBJ objects (+ .mtl -> skins/outlaw.png)
  skin_template.png           1024x1024 guide: every paintable area, labelled
  uv_overlay.png              transparent UV wireframe to put on top of a skin while painting
  skins/<name>.png            example skins; a skin is just a different texture

Same conventions as the other bikes: studs, +Y up, front faces -Z, each wheel its own mesh
centred on its axle, and the steering axis passes through the front wheel centre. The frame
is a rigid hardtail; its rear stays are the `Swingarm` part so the rig finds the rear axle.

Run:  python3 build_chopper.py          build everything
      python3 build_chopper.py --check  also sweep the steering and report clearances
Needs numpy and Pillow.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "source"))
from shapes import X, Y, Z, beam, catmull, cbox, check, cylinder, lathe, loft, ring, rotation, superellipse, tube, unit  # noqa: E402
from skinkit import Atlas, SkinPart, build, fender_chart, side_chart, side_panel, spoked_wheel, top_chart  # noqa: E402

OUT_DIR = os.path.abspath(os.path.join(HERE, ".."))
NAME = "MotorcycleTag_Chopper"

# ---------------------------------------------------------------- layout
RAKE = math.radians(34.0)
D = np.array([0.0, math.cos(RAKE), math.sin(RAKE)])     # steering axis, up and back
FWD = np.array([0.0, math.sin(RAKE), -math.cos(RAKE)])  # perpendicular to D, forward
STEER_ROT = np.column_stack([X, D, -FWD])               # local x, y = steering axis, z = back

FRONT_R, FRONT_HW = 1.36, 0.26    # tall, skinny front
REAR_R, REAR_HW = 1.25, 0.75      # fat rear
FRONT_AXLE = np.array([0.0, FRONT_R, -3.30])
REAR_AXLE = np.array([0.0, REAR_R, 2.75])
STEER_LOCK = math.radians(30.0)
FRONT_FENDER_R = FRONT_R + 0.10
REAR_FENDER_R = REAR_R + 0.12


def sp(x, t, n):
    """Point in the steering frame: x right, t along the steering axis, n forward."""
    return FRONT_AXLE + x * X + t * D + n * FWD


# ---------------------------------------------------------------- texture: solid blocks, then paintable panels
BLOCKS = [  # name, Outlaw colour
    ("TIRE", (30, 30, 33)), ("WHITEWALL", (30, 30, 33)), ("RIM", (205, 210, 218)), ("HUB", (205, 210, 218)),
    ("SPOKES", (205, 210, 218)), ("BRAKE", (150, 156, 164)), ("FORK", (205, 210, 218)), ("CLAMPS", (205, 210, 218)),
    ("BARS", (205, 210, 218)), ("GRIPS", (20, 20, 22)), ("HEADLIGHT", (255, 244, 214)), ("LIGHT_BUCKET", (205, 210, 218)),
    ("TAILLIGHT", (255, 40, 52)), ("FRAME", (22, 22, 25)), ("ENGINE_CASE", (40, 42, 46)), ("CYLINDERS", (60, 62, 68)),
    ("ENGINE_CHROME", (205, 210, 218)), ("EXHAUST", (205, 210, 218)), ("PEGS", (40, 42, 46)), ("SPRINGS", (205, 210, 218)),
    ("SEAT_SIDE", (60, 38, 26)), ("PAINT", (22, 22, 25)),
]
ATLAS = Atlas(BLOCKS)
ATLAS.add(
    side_chart("TANK_R", "Tank right", 1, 0.35),
    side_chart("TANK_L", "Tank left", -1, 0.35),
    top_chart("TANK_TOP", "Tank (top)", 0.55),
    side_chart("SIDECOVER_R", "Oil tank cover right", 1),
    side_chart("SIDECOVER_L", "Oil tank cover left", -1),
    fender_chart("REAR_FENDER", "Rear fender (unrolled)", REAR_AXLE, REAR_FENDER_R),
    fender_chart("FRONT_FENDER", "Front fender (unrolled)", FRONT_AXLE, FRONT_FENDER_R),
    top_chart("SEAT", "Seat (top)", 0.5),
)
CHARTS = ATLAS.charts


# ---------------------------------------------------------------- parts
def finned_cylinder(part, base, axis, length, r_in, r_out, fins=5):
    """A cylinder barrel with chunky cooling fins along `axis`."""
    pts, radii = [], []
    for k in range(fins * 2 + 1):
        a = length * k / (fins * 2)
        r = r_out if k % 2 else r_in
        for da in (-0.035, 0.035):
            pts.append(base + (a + da) * axis)
            radii.append(r)
    pts, radii = pts[1:-1], radii[1:-1]
    part.add(tube(pts, radii, 12), "CYLINDERS")


def build_parts():
    parts = []

    def part(name, pivot=(0, 0, 0), group="Body"):
        p = SkinPart(ATLAS, name, pivot, group)
        parts.append(p)
        return p

    # ---------------- wheels
    spoked_wheel(part("FrontWheel", FRONT_AXLE, "Wheel"), FRONT_AXLE, FRONT_R, FRONT_HW, 10, 0.06, ((-0.25, -0.22),))
    spoked_wheel(part("RearWheel", REAR_AXLE, "Wheel"), REAR_AXLE, REAR_R, REAR_HW, 5, 0.22)

    # ---------------- steering assembly: long fork, apes, headlight bucket, bobbed fender
    fork = part("Fork", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        x = sx * 0.42
        fork.add(cylinder(sp(x, -0.06, 0), sp(x, 1.25, 0), 0.11, 12, 0.03), "FORK")
        fork.add(cbox(sp(x, 0.0, 0.02), (0.09, 0.15, 0.13), 0.04, STEER_ROT), "FORK")
        fork.add(cylinder(sp(x, 1.15, 0), sp(x, 3.22, 0), 0.085, 12, 0.02), "FORK")
        fork.add(cylinder(FRONT_AXLE + sx * 0.27 * X, FRONT_AXLE + sx * 0.50 * X, 0.07, 10, 0.02), "FORK")
    fork.add(cbox(sp(0, 2.72, 0), (0.56, 0.08, 0.18), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 3.15, 0), (0.54, 0.07, 0.18), 0.05, STEER_ROT), "CLAMPS")
    fork.add(cbox(sp(0, 2.40, 0.16), (0.30, 0.05, 0.16), 0.03, STEER_ROT), "LIGHT_BUCKET")
    bucket = [(0.24 * math.cos(a), 2.40 + 0.24 * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 14, endpoint=False)]
    fork.add(loft([[sp(x * k, 2.40 + (t - 2.40) * k, n) for x, t in bucket] for n, k in ((0.30, 0.75), (0.36, 1.0),
                                                                                        (0.60, 1.08))]), "LIGHT_BUCKET")

    lamp = part("Headlight", FRONT_AXLE, "Steer")
    lamp.add(loft([[sp(x * k, 2.40 + (t - 2.40) * k, n) for x, t in bucket] for n, k in ((0.58, 0.98), (0.64, 0.92),
                                                                                        (0.67, 0.70))]), "HEADLIGHT")

    bars = part("Handlebars", FRONT_AXLE, "Steer")
    for sx in (-1, 1):
        bars.add(cylinder(sp(sx * 0.30, 3.20, 0), sp(sx * 0.30, 3.42, -0.02), 0.075, 10, 0.02), "BARS")
        bars.add(cylinder(sp(sx * 0.80, 4.13, -0.24), sp(sx * 1.06, 4.10, -0.38), 0.09, 12, 0.03), "GRIPS")
    apes = [sp(-0.88, 4.12, -0.28), sp(-0.66, 4.15, -0.16), sp(-0.52, 3.72, -0.06), sp(-0.32, 3.42, -0.02),
            sp(0.32, 3.42, -0.02), sp(0.52, 3.72, -0.06), sp(0.66, 4.15, -0.16), sp(0.88, 4.12, -0.28)]
    bars.add(tube(catmull(apes, 4), 0.065, 10, bevel=0.02), "BARS")

    fender = part("FrontFender", FRONT_AXLE, "Steer")
    fhw, r0 = 0.22, FRONT_FENDER_R
    fender.add(lathe(FRONT_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.06), (fhw - 0.06, r0 + 0.10), (-fhw + 0.06, r0 + 0.10),
                                  (-fhw, r0 + 0.06)], 12, [0] * 6, arc=(RAKE - math.radians(42), RAKE + math.radians(28))),
               ["PAINT"], [CHARTS["FRONT_FENDER"]])

    # ---------------- body
    body = part("Bodywork")
    tank = [(-1.12, 0.20, 0.13, 3.68), (-0.98, 0.40, 0.25, 3.66), (-0.66, 0.52, 0.33, 3.58), (-0.28, 0.50, 0.31, 3.44),
            (0.0, 0.34, 0.20, 3.31), (0.10, 0.16, 0.09, 3.27)]
    body.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.2, 20)) for z, a, b, cy in tank]), "PAINT",
             [CHARTS["TANK_TOP"], CHARTS["TANK_R"], CHARTS["TANK_L"]])
    side_panel(body, [(0.25, 2.42), (1.05, 2.42), (1.15, 1.85), (0.95, 1.45), (0.35, 1.45), (0.20, 1.85)],
               ((0.28, 1.0), (0.46, 1.0), (0.51, 0.92)), "PAINT", CHARTS["SIDECOVER_R"], CHARTS["SIDECOVER_L"])
    fhw, r0 = 0.82, REAR_FENDER_R
    body.add(lathe(REAR_AXLE, [(-fhw, r0), (fhw, r0), (fhw, r0 + 0.06), (fhw - 0.06, r0 + 0.10), (-fhw + 0.06, r0 + 0.10),
                               (-fhw, r0 + 0.06)], 18, [0] * 6, arc=(math.radians(-14), math.radians(100))),
             ["PAINT"], [CHARTS["REAR_FENDER"]])

    seat = part("Seat")
    cushion = [(0.0, 0.26, 0.08, 2.74), (0.25, 0.44, 0.12, 2.72), (0.85, 0.50, 0.13, 2.72), (1.25, 0.42, 0.12, 2.80),
               (1.40, 0.26, 0.08, 2.85)]
    seat.add(loft([ring(np.array([0, cy, z]), X, Y, superellipse(a, b, 2.8, 16)) for z, a, b, cy in cushion]), "SEAT_SIDE",
             [CHARTS["SEAT"]])
    for sx in (-1, 1):
        seat.add(cylinder((sx * 0.24, 2.66, 1.18), (sx * 0.24, 2.24, 1.26), 0.075, 10, 0.02), "SPRINGS")

    tl = part("TailLight")
    th = math.radians(78)
    tpos = REAR_AXLE + (REAR_FENDER_R + 0.12) * np.array([0, math.cos(th), math.sin(th)])
    back = np.array([0, math.cos(th), math.sin(th)])
    side = np.cross(X, back)
    tl.add(loft([ring(tpos + d * back, X, side, superellipse(a, b, 2.4, 12)) for d, a, b in
                 ((-0.04, 0.12, 0.07), (0.04, 0.11, 0.06), (0.07, 0.08, 0.045))]), "TAILLIGHT")

    frame = part("Frame")
    frame.add(cylinder(sp(0, 2.86, 0), sp(0, 3.02, 0), 0.17, 14, 0.03), "FRAME")
    frame.add(beam(sp(0, 2.93, -0.16), (0, 2.66, 0.36), 0.16, 0.16, c=0.04), "FRAME")             # backbone
    frame.add(beam(sp(0, 2.97, -0.10), sp(0, 2.88, -0.62), 0.15, 0.15, c=0.04), "FRAME")           # neck to down tube
    frame.add(beam(sp(0, 2.88, -0.56), (0, 0.86, -1.36), 0.15, 0.15, c=0.04), "FRAME")             # down tube
    frame.add(beam((0, 2.70, 0.34), (0, 0.92, 0.56), 0.14, 0.14, c=0.04), "FRAME")                 # seat post
    for sx in (-1, 1):
        frame.add(beam((sx * 0.06, 0.84, -1.36), (sx * 0.36, 0.86, 0.56), 0.12, 0.12, c=0.03), "FRAME")
        frame.add(cylinder((sx * 0.30, 1.05, -1.24), (sx * 0.86, 1.05, -1.24), 0.085, 10, 0.03), "PEGS")

    stays = part("Swingarm")  # rigid hardtail rear stays, named for the rig
    for sx in (-1, 1):
        stays.add(beam((sx * 0.14, 2.64, 0.40), (sx * 0.92, 2.62, 1.20), 0.10, 0.12, c=0.03), "FRAME")
        stays.add(beam((sx * 0.92, 2.62, 1.20), (sx * 0.92, 1.32, 2.75), 0.10, 0.12, c=0.03), "FRAME")
        stays.add(beam((sx * 0.36, 0.88, 0.56), (sx * 0.92, 0.95, 1.36), 0.10, 0.12, c=0.03), "FRAME")
        stays.add(beam((sx * 0.92, 0.95, 1.36), (sx * 0.92, 1.22, 2.75), 0.10, 0.12, c=0.03), "FRAME")
        stays.add(cbox((sx * 0.93, 1.25, 2.75), (0.06, 0.17, 0.17), 0.03), "FRAME")
        stays.add(cylinder(REAR_AXLE + sx * 0.70 * X, REAR_AXLE + sx * 1.00 * X, 0.10, 10, 0.02), "ENGINE_CHROME")

    engine = part("Engine")
    engine.add(cbox((0, 1.20, -0.40), (0.34, 0.36, 0.55), 0.14), "ENGINE_CASE")
    engine.add(cbox((0, 1.15, 0.38), (0.30, 0.30, 0.25), 0.08), "ENGINE_CASE")
    for lean, z0 in ((-30, -0.58), (30, -0.22)):  # V-twin: front cylinder leans forward, rear leans back
        ax = rotation(X, math.radians(lean)) @ Y
        base = np.array([0, 1.42, z0])
        finned_cylinder(engine, base, ax, 0.78, 0.25, 0.31)
        engine.add(cbox(base + 0.88 * ax, (0.28, 0.10, 0.26), 0.05, rotation(X, math.radians(lean))), "ENGINE_CHROME")
    engine.add(cylinder((0.36, 1.86, -0.40), (0.52, 1.86, -0.40), 0.30, 16, 0.05), "ENGINE_CHROME")   # air cleaner
    engine.add(cbox((-0.40, 1.02, 0.08), (0.07, 0.28, 0.68), 0.06), "ENGINE_CHROME")                  # primary cover

    exhaust = part("Exhaust")
    lower = catmull([(0.22, 2.05, -0.95), (0.70, 1.70, -0.86), (1.10, 1.48, -0.30), (1.10, 1.46, 1.50), (1.10, 1.52, 3.42)], 5)
    upper = catmull([(0.22, 2.12, 0.14), (0.78, 1.98, 0.36), (1.10, 1.80, 0.90), (1.10, 1.78, 2.20), (1.10, 1.84, 3.36)], 5)
    for path in (lower, upper):
        exhaust.add(tube(path, 0.075, 10, bevel=0.02), "EXHAUST")
    return parts


# ---------------------------------------------------------------- skins
def flames(pt, c, base, tip, count=4, y0=0.12, y1=0.88, reach=(0.55, 0.85)):
    """Flame tongues licking back from the front edge of a side panel."""
    band = (y1 - y0) / count
    for i in range(count):
        mid = y0 + (i + 0.5) * band
        length = reach[0] + (reach[1] - reach[0]) * ((i * 37) % 10) / 9
        for col, grow in ((base, 1.0), (tip, 0.6)):
            top, bottom = [], []
            for k in range(13):
                u = k / 12
                ff = 1.08 - u * length * grow
                wave = 0.07 * math.sin(u * math.pi * 1.6 + i)
                top.append((ff, mid + band * 0.55 * grow * (1 - u) ** 0.8 + wave))
                bottom.append((ff, mid - band * 0.55 * grow * (1 - u) ** 1.3 + wave))
            pt.poly(c, top + list(reversed(bottom)), col)


SKINS = {
    "outlaw": dict(primary=(22, 22, 25), flame=(255, 110, 20), flame_tip=(255, 220, 60), accent=(255, 110, 20),
                   seat=(60, 38, 26), blocks={}),
    "cherry": dict(primary=(190, 10, 30), flame=None, accent=(250, 250, 250), seat=(250, 246, 236),
                   blocks=dict(PAINT=(190, 10, 30), WHITEWALL=(250, 250, 250), SEAT_SIDE=(250, 246, 236),
                               FRAME=(190, 10, 30))),
    "ghost": dict(primary=(240, 242, 246), flame=(40, 120, 255), flame_tip=(130, 220, 255), accent=(40, 120, 255),
                  seat=(30, 30, 34), blocks=dict(PAINT=(240, 242, 246), FRAME=(240, 242, 246), WHITEWALL=(240, 242, 246),
                                                 SEAT_SIDE=(30, 30, 34))),
    "desert": dict(primary=(150, 140, 96), flame=None, accent=(245, 240, 225), seat=(95, 70, 45), star=True,
                   blocks=dict(PAINT=(150, 140, 96), FRAME=(60, 62, 52), RIM=(60, 62, 52), HUB=(60, 62, 52),
                               SPOKES=(60, 62, 52), FORK=(60, 62, 52), EXHAUST=(40, 40, 40), SEAT_SIDE=(95, 70, 45),
                               ENGINE_CHROME=(90, 92, 84), CLAMPS=(60, 62, 52), BARS=(60, 62, 52))),
    "midnight_blue": dict(primary=(18, 30, 80), flame=None, accent=(205, 210, 218), seat=(30, 22, 18),
                          blocks=dict(PAINT=(18, 30, 80), FRAME=(18, 30, 80), WHITEWALL=(240, 240, 240))),
    "emerald": dict(primary=(10, 90, 50), flame=(232, 180, 60), flame_tip=(255, 230, 140), accent=(232, 180, 60),
                    seat=(60, 38, 26), blocks=dict(PAINT=(10, 90, 50), FRAME=(10, 90, 50))),
    "hellfire": dict(primary=(170, 10, 20), flame=(255, 200, 20), flame_tip=(255, 240, 150), accent=(255, 200, 20),
                     seat=(24, 24, 26), blocks=dict(PAINT=(170, 10, 20), FRAME=(24, 24, 26))),
    "chrome_king": dict(primary=(200, 205, 214), flame=(24, 24, 28), flame_tip=(80, 84, 92), accent=(24, 24, 28),
                        seat=(24, 24, 28), blocks=dict(PAINT=(200, 205, 214), FRAME=(200, 205, 214), RIM=(24, 24, 28),
                                                       SPOKES=(24, 24, 28), WHITEWALL=(240, 240, 240))),
}


def star(pt, c, color, cx=0.5, cy=0.5, r=0.32):
    x, y, w, h = c.rect
    px, py = c.frac_to_px(cx, cy)
    R = r * min(w, h)
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = R if k % 2 == 0 else R * 0.4
        pts.append((px + rr * math.cos(a), py + rr * math.sin(a)))
    pt.d.polygon(pts, fill=color)


def paint_skin(pt, skin):
    pri, acc = skin["primary"], skin["accent"]
    for side in ("TANK_R", "TANK_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        if skin["flame"]:
            flames(pt, c, skin["flame"], skin["flame_tip"])
        elif skin.get("star"):
            star(pt, c, acc, 0.5, 0.48, 0.42)
        else:  # classic scallop pinstripe
            pt.poly(c, [(0.05, 0.40), (1.0, 0.36), (1.0, 0.46), (0.05, 0.50)], acc)
    c = CHARTS["TANK_TOP"]
    pt.fill(c, pri)
    if skin["flame"]:
        pt.bands(c, [(0.44, 0.56, skin["flame"])])
    else:
        pt.bands(c, [(0.47, 0.53, acc)])
    for side in ("SIDECOVER_R", "SIDECOVER_L"):
        c = CHARTS[side]
        pt.fill(c, pri)
        pt.poly(c, [(0.1, 0.42), (0.9, 0.42), (0.9, 0.58), (0.1, 0.58)], acc)
    for name in ("REAR_FENDER", "FRONT_FENDER"):
        c = CHARTS[name]
        pt.fill(c, pri)
        pt.bands(c, [(0.46, 0.54, acc)])
    c = CHARTS["SEAT"]
    pt.fill(c, skin["seat"])
    pt.ribs(c, tuple(max(0, v - 25) for v in skin["seat"]), 8, 4)
    pt.blocks(dict(skin["blocks"], PAINT=skin["blocks"].get("PAINT", pri)))


# ---------------------------------------------------------------- main
def main():
    parts = build_parts()
    build(OUT_DIR, NAME, ATLAS, parts, SKINS, paint_skin, math.degrees(RAKE), "Motorcycle Tag build_chopper.py",
          "ChopperSkin")
    if "--check" in sys.argv:
        check(parts, axis=D, front=FRONT_AXLE, rear=REAR_AXLE, lock_rad=STEER_LOCK, spin_period=72)


if __name__ == "__main__":
    main()
