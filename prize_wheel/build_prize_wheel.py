#!/usr/bin/env python3
"""
Procedural prize-wheel machine for Roblox ("Aurora Spin Core").

Builds every component as a separate, pivot-correct mesh and exports:
  out/PrizeWheel.glb      full assembly (named nodes, PBR materials)
  out/meshes/*.obj        every component on its own, pivot at its local origin

Conventions
  * 1 unit = 1 stud (after SCALE), Y up, wheel front faces +Z.
  * Base   origin: ground level, centred under the wheel axle.
  * Wheel  origin: hub centre, spins about its local Z axis.
  * Pointer origin: pivot pin centre, swings about its local Z axis.
"""
import math
import os

import numpy as np
import trimesh
from trimesh.graph import smooth_shade
from trimesh.transformations import rotation_matrix as rot
from trimesh.transformations import translation_matrix as trans
from trimesh.visual.material import PBRMaterial

# ---------------------------------------------------------------- parameters
SCALE = 0.7            # global studs scale applied at export
HUB_Y = 18.4           # wheel axle height (pre-scale)
N_SEG = 10             # prize segments
SEG = 2 * math.pi / N_SEG
HALF = SEG / 2
TOP = math.pi / 2      # segment 01 is centred at 12 o'clock
RING_N = 60            # radial resolution of round parts (multiple of 10 & 20)
SMOOTH_ANGLE = math.radians(35)
PZ = 2.2               # pointer pivot z (in front of the rim)
PY = 11.75             # pointer pivot height above the hub
ZC = -1.0              # base column centre z (under the wheel, biased rearward)

SEG_COLORS = ["#E8344E", "#F59E0B", "#12B76A", "#1496F2", "#8B3DFF"]
GEM_COLORS = ["#FF6B80", "#FFC23D", "#4DEB9C", "#4DB8FF", "#B77DFF"]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


# ------------------------------------------------------------------ helpers
def hex_rgba(h, a=1.0):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [a]


def mk(V, F):
    m = trimesh.Trimesh(np.asarray(V, float), np.asarray(F, int), process=True)
    m.update_faces(m.nondegenerate_faces())
    m.remove_unreferenced_vertices()
    if m.volume < 0:
        m.invert()
    return m


def lathe(profile, n=RING_N, theta0=0.0):
    """Revolve a closed (r, z) profile about Z."""
    prof = np.asarray(profile, float)
    P = len(prof)
    th = theta0 + np.arange(n) * 2 * math.pi / n
    V = np.zeros((n * P, 3))
    for i, t in enumerate(th):
        V[i * P:(i + 1) * P] = np.c_[prof[:, 0] * math.cos(t), prof[:, 0] * math.sin(t), prof[:, 1]]
    F = []
    for i in range(n):
        i2 = (i + 1) % n
        for j in range(P):
            j2 = (j + 1) % P
            a, b, c, d = i * P + j, i * P + j2, i2 * P + j2, i2 * P + j
            F += [[a, b, c], [a, c, d]]
    return mk(V, F)


def hull(pts):
    return trimesh.convex.convex_hull(np.asarray(pts, float))


def cbox_pts(sx, sy, sz, b):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    pts = []
    for ax, ay, az in [(hx, hy - b, hz - b), (hx - b, hy, hz - b), (hx - b, hy - b, hz)]:
        for sx_ in (-1, 1):
            for sy_ in (-1, 1):
                for sz_ in (-1, 1):
                    pts.append((sx_ * ax, sy_ * ay, sz_ * az))
    return pts


def cbox(size, b, center=(0, 0, 0), rz=0.0):
    m = hull(cbox_pts(*size, b))
    if rz:
        m.apply_transform(rot(rz, [0, 0, 1]))
    m.apply_translation(center)
    return m


def hexbolt(r=0.24, h=0.18, z0=0.0):
    pts = []
    for k in range(6):
        a = k * math.pi / 3
        c, s = math.cos(a), math.sin(a)
        pts += [(r * c, r * s, 0), (r * c, r * s, h), (0.72 * r * c, 0.72 * r * s, h + 0.07)]
    m = hull(pts)
    m.apply_translation([0, 0, z0])
    return m


def to_y_up(m):
    """Lathe axis Z -> Y (used for the octagonal pedestal parts)."""
    m.apply_transform(rot(-math.pi / 2, [1, 0, 0]))
    return m


def at(m, pos=(0, 0, 0), rz=0.0):
    if rz:
        m.apply_transform(rot(rz, [0, 0, 1]))
    m.apply_translation(pos)
    return m


def merge(parts):
    return trimesh.util.concatenate(parts)


def shade(m):
    return smooth_shade(m, angle=SMOOTH_ANGLE)


# ------------------------------------------------------------------ materials
def pbr(color, metal, rough, emissive=None, alpha=1.0, name=None):
    kw = dict(baseColorFactor=hex_rgba(color, alpha), metallicFactor=metal, roughnessFactor=rough, name=name)
    if emissive:
        kw["emissiveFactor"] = emissive
    if alpha < 1:
        kw["alphaMode"] = "BLEND"
    return PBRMaterial(**kw)


MAT = {
    "Paint": pbr("#E6EAF4", 0.35, 0.34, name="PearlPaint"),
    "Metal": pbr("#3B404C", 0.80, 0.42, name="BrushedGunmetal"),
    "Accent": pbr("#4A3DFF", 0.25, 0.12, name="GlossIndigo"),
    "Neon": pbr("#00C8FF", 0.0, 0.4, emissive=[0.0, 0.78, 1.0], name="CyanLED"),
    "Glass": pbr("#BDEFFF", 0.0, 0.05, alpha=0.38, name="Acrylic"),
    "PointerPaint": pbr("#FF4D5E", 0.2, 0.15, name="GlossCoral"),
    "PointerCore": pbr("#FFF2D6", 0.0, 0.4, emissive=[1.0, 0.85, 0.55], name="HotCore"),
}


# --------------------------------------------------------------------- wheel
def seg_angle(i):
    return TOP - i * SEG


def panel(theta_c, r0=3.85, r1=8.65, d=0.42, k=8):
    """Recessed, bevelled prize panel (annular sector with parallel-sided gaps)."""
    loops = [(0.0, 0.0), (0.0, 0.38), (0.14, 0.50), (0.45, 0.50), (0.70, 0.32)]
    L = []
    for inset, z in loops:
        R0, R1, dd = r0 + inset, r1 - inset, d + inset
        a_half = HALF - math.asin(dd / R1)
        b_half = HALF - math.asin(dd / R0)
        pts = [(R1, theta_c + t) for t in np.linspace(-a_half, a_half, k + 1)]
        pts += [(R0, theta_c + t) for t in np.linspace(b_half, -b_half, k + 1)]
        L.append([(r * math.cos(a), r * math.sin(a), z) for r, a in pts])
    M = 2 * (k + 1)
    V = [p for loop in L for p in loop]
    F = []
    for j in range(len(L) - 1):
        for i in range(M):
            i2 = (i + 1) % M
            a, a2, b, b2 = j * M + i, j * M + i2, (j + 1) * M + i, (j + 1) * M + i2
            F += [[a, a2, b2], [a, b2, b]]
    top = (len(L) - 1) * M
    for i in range(k):
        o0, o1, n1, n0 = i, i + 1, M - 2 - i, M - 1 - i
        F += [[top + o0, top + o1, top + n1], [top + o0, top + n1, top + n0]]  # +z cap
        F += [[o0, n1, o1], [o0, n0, n1]]                                      # -z cap
    return mk(V, F)


def gem(theta_c, radius=6.25):
    """Elongated hex crystal that sits in the panel pocket (emissive)."""
    def hx(sx, sy, z):
        return [(sx * x, sy * y, z) for x, y in [(1, 0), (.5, 1), (-.5, 1), (-1, 0), (-.5, -1), (.5, -1)]]
    pts = hx(1.30, 0.66, 0.32) + hx(1.30, 0.66, 0.58) + hx(0.78, 0.40, 0.80)
    m = hull(pts)
    m.apply_transform(rot(theta_c, [0, 0, 1]))
    m.apply_translation([radius * math.cos(theta_c), radius * math.sin(theta_c), 0])
    return m


def build_wheel():
    parts = {}

    # --- dark brushed frame: back plate, dividers, hub housing, bolts, axle
    frame = []
    back = [(0, -1.0), (4.0, -1.0), (4.1, -1.15), (4.3, -1.15), (4.4, -1.0), (7.0, -1.0), (7.1, -1.15),
            (7.3, -1.15), (7.4, -1.0), (9.0, -1.0), (9.4, -0.6), (9.4, 0.1), (0, 0.1)]
    frame.append(lathe(back))
    for m_ in range(N_SEG):
        phi = TOP - HALF - m_ * SEG
        frame.append(cbox((5.9, 0.5, 0.95), 0.12, (6.5, 0, 0.475)).apply_transform(rot(phi, [0, 0, 1])))
    hub = [(0, 0.0), (3.6, 0.0), (3.6, 0.45), (3.35, 0.7), (2.6, 0.7), (2.6, 1.1), (2.35, 1.35), (1.95, 1.35),
           (1.95, 1.7), (1.7, 1.95), (1.3, 1.95), (1.15, 1.8), (1.15, 1.45), (0, 1.45)]
    frame.append(lathe(hub))
    axle = [(0, -3.4), (0.6, -3.4), (0.8, -3.2), (0.8, -1.0), (0, -1.0)]
    frame.append(lathe(axle, 24))
    for k in range(6):                                   # hub flange bolts
        a = TOP + k * math.pi / 3
        frame.append(at(hexbolt(0.2, 0.16, 0.7), (3.0 * math.cos(a), 3.0 * math.sin(a), 0)))
    for m_ in range(N_SEG):                              # rim bolts at the dividers
        a = TOP - HALF - m_ * SEG
        frame.append(at(hexbolt(0.24, 0.16, 1.2), (10.48 * math.cos(a), 10.48 * math.sin(a), 0)))
    parts["Wheel_Frame"] = ("Metal", merge(frame))

    # --- painted outer rim (layered, with an LED channel)
    rim = [(9.4, -1.2), (10.5, -1.2), (10.8, -0.9), (10.8, 0.9), (10.5, 1.2), (10.15, 1.2), (10.15, 1.0),
           (9.8, 1.0), (9.8, 1.2), (9.55, 1.2), (9.4, 1.05)]
    parts["Wheel_Rim"] = ("Paint", lathe(rim))

    # --- glossy inner accent bezel
    acc = [(8.85, -0.3), (9.5, -0.3), (9.5, 1.25), (9.3, 1.5), (9.05, 1.5), (8.85, 1.3)]
    parts["Wheel_Accent"] = ("Accent", lathe(acc))

    # --- LED: 20 arc bars in the rim channel + hub ring
    leds = []
    for j in range(20):
        a0 = TOP + j * math.pi / 10
        pts = []
        for t in np.linspace(-math.radians(5.8), math.radians(5.8), 4):
            for r in (9.88, 10.07):
                for z in (1.0, 1.1):
                    pts.append((r * math.cos(a0 + t), r * math.sin(a0 + t), z))
        leds.append(hull(pts))
    leds.append(lathe([(2.0, 1.35), (2.2, 1.35), (2.2, 1.43), (2.0, 1.43)], 48))
    parts["Wheel_LED"] = ("Neon", merge(leds))

    # --- hub glass + core
    parts["Hub_Glass"] = ("Glass", lathe([(0, 1.45), (1.1, 1.45), (1.05, 1.65), (0.9, 1.85), (0.6, 2.0),
                                          (0.3, 2.07), (0, 2.1)], 36))
    parts["Hub_Core"] = ("Neon", lathe([(0, 1.45), (0.8, 1.45), (0.8, 1.6), (0.55, 1.78), (0, 1.78)], 6))

    # --- prize panels + gems (one mesh each so they can be recoloured / textured)
    for i in range(N_SEG):
        th = seg_angle(i)
        parts[f"Segment_{i + 1:02d}"] = (f"Seg{i % 5}", panel(th))
        parts[f"SegmentGem_{i + 1:02d}"] = (f"Gem{i % 5}", gem(th))
    return parts


# ------------------------------------------------------------------- pointer
def build_pointer():
    parts = {}
    poly = np.array([(-1.15, 0.6), (1.15, 0.6), (1.35, -0.8), (0, -3.7), (-1.35, -0.8)])
    c = poly.mean(axis=0)
    small = c + (poly - c) * 0.78
    pts = []
    for z, p in [(-0.55, small), (-0.30, poly), (0.30, poly), (0.55, small)]:
        pts += [(x, y, z) for x, y in p]
    parts["Pointer_Body"] = ("PointerPaint", hull(pts))

    core = np.array([(-0.5, 0.0), (0.5, 0.0), (0.6, -1.0), (0, -2.4), (-0.6, -1.0)])
    core[:, 1] -= 0.25
    cs = core.mean(axis=0) + (core - core.mean(axis=0)) * 0.7
    cp = []
    for sgn in (1, -1):
        cp += [(x, y, sgn * 0.50) for x, y in core] + [(x, y, sgn * 0.66) for x, y in cs]
    parts["Pointer_Core"] = ("PointerCore", hull(cp))

    boss = [(0, -0.9), (0.65, -0.9), (0.85, -0.7), (0.85, 0.7), (0.65, 0.9), (0, 0.9)]
    parts["Pointer_Pivot"] = ("Metal", lathe(boss, 24))
    return parts


# ---------------------------------------------------------------------- base
def beam_geometry(sign):
    """Support arm: saddle end -> roller. Returns (start, end, angle)."""
    p0 = np.array([sign * 4.2, 6.3])
    a = math.radians(48)
    p1 = np.array([sign * 12.4 * math.sin(a), HUB_Y - 12.4 * math.cos(a)])
    d = p1 - p0
    return p0, p1, math.atan2(d[1], d[0]), float(np.linalg.norm(d))


def build_base():
    body, metal, accent, neon, glass = [], [], [], [], []
    O = 22.5 * math.pi / 180   # octagon flat-front orientation

    def oct_(profile, group):
        m = to_y_up(lathe(profile, 8, O))
        m.apply_translation([0, 0, ZC])
        group.append(m)

    # pedestal: foot, tiered body, accent collar, LED ring
    oct_([(0, 0), (8.0, 0), (8.6, 0.6), (8.6, 1.2), (8.0, 1.8), (0, 1.8)], metal)
    oct_([(0, 1.7), (6.4, 1.7), (6.4, 2.0), (6.2, 2.0), (6.2, 2.15), (6.4, 2.15), (6.4, 2.4), (5.9, 2.9),
          (4.4, 4.1), (3.3, 4.1), (3.3, 6.4), (0, 6.4)], body)
    oct_([(3.2, 4.1), (4.15, 4.1), (4.15, 4.5), (3.9, 4.8), (3.2, 4.8)], accent)
    oct_([(6.6, 1.8), (7.0, 1.8), (7.0, 1.88), (6.6, 1.88)], neon)
    for k in range(8):
        a = O + k * math.pi / 4
        b = hexbolt(0.26, 0.16)
        b.apply_transform(rot(-math.pi / 2, [1, 0, 0]))
        b.apply_translation([7.5 * math.cos(a), 1.8, ZC - 7.5 * math.sin(a)])
        metal.append(b)

    # saddle + support arms + rollers
    metal.append(cbox((10.8, 1.6, 6.2), 0.4, (0, 6.3, ZC)))
    for sx in (-2.4, 2.4):
        for sz in (-1.3, 1.3):
            b = hexbolt(0.24, 0.14)
            b.apply_transform(rot(-math.pi / 2, [1, 0, 0]))
            b.apply_translation([sx, 7.1, ZC - sz])
            metal.append(b)
    for sign in (-1, 1):
        p0, p1, ang, L = beam_geometry(sign)
        u = np.array([math.cos(ang), math.sin(ang)])
        mid = (p0 + p1) / 2
        body.append(cbox((L + 1.4, 1.8, 2.0), 0.28, (mid[0], mid[1], 0), rz=ang))
        accent.append(at(lathe([(0, -1.0), (1.15, -1.0), (1.35, -0.8), (1.35, 0.8), (1.15, 1.0), (0, 1.0)], 24),
                         (p1[0], p1[1], 0)))
        metal.append(at(lathe([(0, -1.35), (0.8, -1.35), (0.95, -1.2), (0.95, 1.2), (0.8, 1.35), (0, 1.35)], 24),
                        (p1[0], p1[1], 0)))
        # acrylic lens over an LED core, with a bolt at each end
        c = p0 + u * 2.7
        glass.append(cbox((2.4, 0.55, 0.22), 0.07, (c[0], c[1], 1.07), rz=ang))
        neon.append(cbox((2.1, 0.26, 0.12), 0.03, (c[0], c[1], 1.04), rz=ang))
        for s in (0.8, 4.5):
            q = p0 + u * s
            metal.append(at(hexbolt(0.26, 0.15, 1.0), (q[0], q[1], 0)))

    # rear spine, axle collar, pointer arm and pivot cheeks
    ay0, ay1 = HUB_Y + 12.45, HUB_Y + 13.65
    lo = np.array(cbox_pts(5.6, 1.6, 2.2, 0.35)) + [0, 3.4, -3.5]
    hi = np.array(cbox_pts(2.2, 1.6, 2.2, 0.3)) + [0, ay1 - 0.8, -3.5]
    body.append(hull(np.vstack([lo, hi])))
    metal.append(at(lathe([(0, -2.5), (2.9, -2.5), (2.9, -1.7), (2.6, -1.4), (0, -1.4)], RING_N), (0, HUB_Y, 0)))
    metal.append(at(lathe([(0, -4.85), (1.0, -4.85), (1.1, -4.7), (1.1, -4.6), (0, -4.6)], 24), (0, HUB_Y, 0)))
    body.append(cbox((2.2, ay1 - ay0, 8.3), 0.3, (0, (ay0 + ay1) / 2, -0.45)))
    for z in (1.05, 3.35):
        accent.append(cbox((1.7, 0.9, 0.4), 0.1, (0, HUB_Y + PY + 0.75, z)))
        accent.append(at(lathe([(0, -0.2), (1.0, -0.2), (1.0, 0.2), (0, 0.2)], 24), (0, HUB_Y + PY, z)))
    metal.append(at(lathe([(0, 0), (0.42, 0), (0.42, 0.2), (0, 0.2)], 16), (0, HUB_Y + PY, 3.55)))
    neon.append(cbox((0.9, 0.7, 0.14), 0.04, (0, (ay0 + ay1) / 2, 3.75)))
    neon.append(cbox((0.6, 19.0, 0.1), 0.03, (0, 18.5, -4.65)))
    return {
        "Base_Body": ("Paint", merge(body)),
        "Base_Metal": ("Metal", merge(metal)),
        "Base_Accent": ("Accent", merge(accent)),
        "Base_LED": ("Neon", merge(neon)),
        "Base_Glass": ("Glass", merge(glass)),
    }


# -------------------------------------------------------------------- export
def seg_material(key):
    idx = int(key[-1])
    if key.startswith("Seg"):
        return pbr(SEG_COLORS[idx], 0.1, 0.3, name=f"SegPaint{idx}")
    return pbr(GEM_COLORS[idx], 0.0, 0.3, emissive=[c * 0.8 for c in hex_rgba(GEM_COLORS[idx])[:3]], alpha=0.95, name=f"SegGem{idx}")


def material_for(key):
    return MAT[key] if key in MAT else seg_material(key)


def finalize(mesh, matkey):
    mesh = shade(mesh)
    mesh.apply_scale(SCALE)
    mesh.visual = trimesh.visual.TextureVisuals(material=material_for(matkey))
    return mesh


def main():
    os.makedirs(os.path.join(OUT, "meshes"), exist_ok=True)
    groups = {
        "Base": ((0, 0, 0), build_base()),
        "Wheel": ((0, HUB_Y, 0), build_wheel()),
        "Pointer": ((0, HUB_Y + PY, PZ), build_pointer()),
    }
    scene = trimesh.Scene(base_frame="PrizeWheel")
    total = 0
    for gname, (pos, parts) in groups.items():
        scene.graph.update(frame_to=gname, frame_from="PrizeWheel", matrix=trans(np.array(pos) * SCALE))
        for name, (matkey, mesh) in parts.items():
            m = finalize(mesh, matkey)
            total += len(m.faces)
            scene.add_geometry(m, node_name=name, geom_name=name, parent_node_name=gname)
            m.export(os.path.join(OUT, "meshes", f"{name}.obj"))
            print(f"{gname:8s}{name:18s}{len(m.faces):6d} tris")
    print("TOTAL tris:", total)
    scene.export(os.path.join(OUT, "PrizeWheel.glb"), include_normals=True)
    print("wrote", os.path.join(OUT, "PrizeWheel.glb"))


if __name__ == "__main__":
    main()
