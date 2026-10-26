"""Shared skin pipeline for the Motorcycle Tag bikes (dirt bike, superbike, ...).

A bike's single texture has two zones:
  panels (top)  plastics projected flat, as seen from outside the bike, so numbers and
                stripes painted upright read correctly on the model
  blocks (bottom rows)  solid swatches; every mechanical part samples the centre of its
                block, so filling a block recolours that part

Each bike script defines its blocks, its charts (panels) and its geometry, then calls
build() to pack the texture, bake normals and write GLB, OBJ, template, overlay and skins.
Needs numpy and Pillow.
"""
import json
import math
import os
import struct
from collections import defaultdict

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from build_motorcycle import loft, unit

TEX = 1024


# ---------------------------------------------------------------- texture layout
class Atlas:
    def __init__(self, blocks, block_px=64):
        self.blocks = blocks                         # [(name, default rgb)]
        self.index = {name: i for i, (name, _) in enumerate(blocks)}
        self.block_px = block_px
        self.per_row = TEX // block_px
        rows = -(-len(blocks) // self.per_row)
        self.panel_h = TEX - rows * block_px
        self.charts = {}

    def add(self, *charts):
        for c in charts:
            self.charts[c.name] = c

    def block_rect(self, i):
        b = self.block_px
        return (i % self.per_row) * b, self.panel_h + (i // self.per_row) * b, b, b

    def block_uv(self, i):
        x, y, w, h = self.block_rect(i)
        return (x + w / 2) / TEX, (y + h / 2) / TEX

    def pack(self, pad=14, label=22):
        """Skyline-pack the panels at the largest uniform texel density that fits.
        Each panel keeps `label` pixels above it for its name on the template."""
        charts = [c for c in self.charts.values() if c.points]
        items = sorted(charts, key=lambda c: -(c.bounds()[1][1] - c.bounds()[0][1]))

        def place(scale):
            sky = np.full(TEX, pad + label, float)   # lowest free y per pixel column
            rects = {}
            for c in items:
                mn, mx = c.bounds()
                w, h = (mx - mn) * scale
                span = int(math.ceil(w)) + pad
                best = None
                for x in range(pad, TEX - span + 1, 4):
                    y = sky[x:x + span].max()
                    if best is None or y < best[1]:
                        best = (x, y)
                if best is None or best[1] + h + pad > self.panel_h:
                    return None
                x, y = best
                rects[c.name] = (x, y, w, h)
                sky[x:x + span] = y + h + pad + label
            return rects

        lo, hi = 10.0, 1000.0
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if place(mid) else (lo, mid)
        rects = place(lo)
        for c in charts:
            c.rect, c.scale = rects[c.name], lo
        return lo


class Chart:
    """A paintable panel. pred(normal, centroid) picks its faces; proj maps a 3D point to
    (right, up) as seen by someone looking at that surface."""

    def __init__(self, name, label, pred, proj, front):
        self.name, self.label, self.pred, self.proj, self.front = name, label, pred, proj, front
        self.points = []
        self.tris = []      # (3, 2) projected triangles, for the template wireframe
        self.rect = None

    def bounds(self):
        p = np.array(self.points)
        return p.min(0), p.max(0)

    def to_px(self, sx, sy):
        (mn, mx), (x, y, w, h), s = self.bounds(), self.rect, self.scale
        return x + (sx - mn[0]) * s, y + (mx[1] - sy) * s

    def frac_to_px(self, ff, fy):
        """ff: 0 = rear/bottom edge .. 1 = edge nearest the bike's front (or top for top-down panels)."""
        mn, mx = self.bounds()
        fx = ff if self.front in ("right", "up") else 1 - ff
        return self.to_px(mn[0] + fx * (mx[0] - mn[0]), mn[1] + fy * (mx[1] - mn[1]))

    def world_to_px(self, p):
        return self.to_px(*self.proj(np.asarray(p, float)))


def side_chart(name, label, sign, min_dot=0.4):
    # Viewed from the right (+X) the bike's front (-Z) is on the viewer's right; from the left, on the left.
    return Chart(name, label, lambda n, c: n[0] * sign > min_dot, lambda p: (-sign * p[2], p[1]),
                 "right" if sign > 0 else "left")


def top_chart(name, label, min_dot=0.4):
    # Viewed from above with the front at the top of the image.
    return Chart(name, label, lambda n, c: n[1] > min_dot, lambda p: (p[0], -p[2]), "up")


def front_chart(name, label, min_dot=0.5):
    # Viewed from in front of the bike: the bike's right (+X) is on the viewer's left.
    return Chart(name, label, lambda n, c: -n[2] > min_dot, lambda p: (-p[0], p[1]), "up")


# ---------------------------------------------------------------- parts
class SkinPart:
    def __init__(self, atlas, name, pivot=(0, 0, 0), group="Body"):
        self.atlas = atlas
        self.name, self.group = name, group
        self.pivot = np.asarray(pivot, float)
        self.verts, self.faces, self.kinds, self.raw = [], [], [], []
        self.count = 0

    def add(self, prim, block, charts=()):
        """block: block name, or a list of names indexed by a lathe's per-face colours.
        charts: panels to try in order; faces no chart claims get the block."""
        verts, faces = np.asarray(prim[0], float), np.asarray(prim[1], int)
        index = self.atlas.index
        if isinstance(block, str):
            fblocks = np.full(len(faces), index[block])
        else:
            fblocks = np.array([index[block[k]] for k in prim[2]])
        c = verts.mean(0)
        a, b, d = verts[faces[:, 0]] - c, verts[faces[:, 1]] - c, verts[faces[:, 2]] - c
        if np.einsum("ij,ij->i", a, np.cross(b, d)).sum() < 0:
            faces = faces[:, [0, 2, 1]]
        P = verts[faces]
        fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        area = np.linalg.norm(fn, axis=1)
        keep = area > 1e-9
        faces, P, fn, fblocks = faces[keep], P[keep], fn[keep] / area[keep, None], fblocks[keep]
        for f in range(len(faces)):
            for ch in charts:
                if ch.pred(fn[f], P[f].mean(0)):
                    tri = np.array([ch.proj(p) for p in P[f]])
                    ch.points.extend(tri)
                    ch.tris.append(tri)
                    self.kinds.append(ch)
                    self.raw.append(tri)
                    break
            else:
                self.kinds.append(int(fblocks[f]))
                self.raw.append(None)
        self.verts.append(verts)
        self.faces.append(faces + self.count)
        self.count += len(verts)
        return self

    def world(self):
        return np.concatenate(self.verts), np.concatenate(self.faces)

    def corner_uvs(self):
        out = np.zeros((len(self.kinds), 3, 2))
        for f, (kind, raw) in enumerate(zip(self.kinds, self.raw)):
            if isinstance(kind, Chart):
                out[f] = [np.array(kind.to_px(*p)) / TEX for p in raw]
            else:
                out[f] = self.atlas.block_uv(kind)
        return out


def side_panel(part, profile, xs, block, chart_r, chart_l):
    """Prism from a convex side-view profile [(z, y)], with sections [(x, scale)] going outward."""
    c = np.mean(profile, axis=0)
    for sx, chart in ((1, chart_r), (-1, chart_l)):
        part.add(loft([[np.array([sx * x, c[1] + (y - c[1]) * s, c[0] + (z - c[0]) * s]) for z, y in profile]
                       for x, s in xs]), block, [chart])


# ---------------------------------------------------------------- images
def font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def text_color(rgb):
    return (20, 20, 22) if sum(rgb) > 380 else (245, 245, 245)


def draw_wire(draw, chart, color, width=1):
    for tri in chart.tris:
        pts = [chart.to_px(*p) for p in tri]
        draw.line(pts + [pts[0]], fill=color, width=width)


def write_template(atlas, path_template, path_overlay, up_labels=()):
    img = Image.new("RGB", (TEX, TEX), (43, 45, 49))
    ov = Image.new("RGBA", (TEX, TEX), (0, 0, 0, 0))
    d, do = ImageDraw.Draw(img), ImageDraw.Draw(ov)
    for c in atlas.charts.values():
        if c.rect is None:
            continue
        x, y, w, h = c.rect
        d.rectangle([x - 6, y - 6, x + w + 6, y + h + 6], fill=(70, 74, 80))
        for tri in c.tris:
            d.polygon([c.to_px(*p) for p in tri], fill=(232, 234, 238))
        draw_wire(d, c, (175, 180, 188))
        draw_wire(do, c, (255, 255, 255, 140))
        do.rectangle([x - 6, y - 6, x + w + 6, y + h + 6], outline=(255, 210, 0, 200), width=2)
        arrow = {"right": "FRONT \u2192", "left": "\u2190 FRONT", "up": "\u2191 FRONT"}[c.front]
        if c.name in up_labels:
            arrow = "\u2191 UP"
        lx = min(x, TEX - 4 - d.textlength(c.label, font=font(15)))  # keep labels inside the image
        d.text((lx, y - 4), c.label, fill=(255, 210, 0), font=font(15), anchor="lb")
        d.text((x + w / 2, y + h / 2), arrow, fill=(110, 116, 126), font=font(14), anchor="mm")
    for i, (name, rgb) in enumerate(atlas.blocks):
        x, y, w, h = atlas.block_rect(i)
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=rgb, outline=(20, 20, 22))
        do.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 210, 0, 160))
        label = name.replace("_", "\n", 1)
        d.multiline_text((x + w / 2, y + h / 2), label, fill=text_color(rgb), font=font(9), anchor="mm", align="center")
    img.save(path_template)
    ov.save(path_overlay)


class Painter:
    """Drawing helpers for skins, in each panel's own coordinates."""

    def __init__(self, atlas, base):
        self.atlas = atlas
        self.img = Image.new("RGB", (TEX, TEX), base)
        self.d = ImageDraw.Draw(self.img)

    def fill(self, c, color, grow=10):
        x, y, w, h = c.rect
        self.d.rectangle([x - grow, y - grow, x + w + grow, y + h + grow], fill=color)

    def poly(self, c, pts, color):
        """pts in (toward-front fraction, up fraction) of the panel's bounds."""
        self.d.polygon([c.frac_to_px(ff, fy) for ff, fy in pts], fill=color)

    def world_poly(self, c, pts, color):
        self.d.polygon([c.world_to_px(p) for p in pts], fill=color)

    def number(self, c, text, color, size_frac=0.62, cy=0.5):
        x, y, w, h = c.rect
        cx, py = c.frac_to_px(0.5, cy)
        self.d.text((cx, py), text, fill=color, font=font(max(8, int(h * size_frac))), anchor="mm")

    def text_at(self, c, p, text, color, height_studs):
        self.d.text(c.world_to_px(p), text, fill=color, font=font(max(8, int(height_studs * c.scale))), anchor="mm")

    def bands(self, c, bands, grow=10):
        """Full-length bands across a top-down panel: [(lo, hi, colour)] as fractions of its width."""
        x, y, w, h = c.rect
        for lo, hi, col in bands:
            x0, _ = c.frac_to_px(lo, 0)
            x1, _ = c.frac_to_px(hi, 0)
            self.d.rectangle([min(x0, x1), y - grow, max(x0, x1), y + h + grow], fill=col)

    def ribs(self, c, color, count=12, width=3):
        x, y, w, h = c.rect
        for k in range(1, count):
            yy = y + h * k / count
            self.d.line([(x + w * 0.12, yy), (x + w * 0.88, yy)], fill=color, width=width)

    def blocks(self, overrides):
        for i, (name, rgb) in enumerate(self.atlas.blocks):
            x, y, w, h = self.atlas.block_rect(i)
            self.d.rectangle([x, y, x + w - 1, y + h - 1], fill=overrides.get(name, rgb))

    def save(self, path):
        self.img.save(path)


# ---------------------------------------------------------------- normals + export
def bake(part, smooth_deg=40.0):
    """Angle-based smoothing (hard edges above smooth_deg), then dedupe vertices."""
    V, F = part.world()
    UV = part.corner_uvs()
    P = V[F]
    fn = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    fu = fn / np.linalg.norm(fn, axis=1, keepdims=True)
    key = {}
    gid = np.array([key.setdefault(tuple(k), len(key)) for k in np.round(V * 1e4).astype(np.int64)])
    G = gid[F]
    by_group = defaultdict(list)
    for f in range(len(F)):
        for c in range(3):
            by_group[G[f, c]].append(f)
    by_group = {g: np.array(fs) for g, fs in by_group.items()}
    cos_t = math.cos(math.radians(smooth_deg))
    out, pos, nor, uv, idx = {}, [], [], [], []
    for f in range(len(F)):
        for c in range(3):
            fs = by_group[G[f, c]]
            n = unit(fn[fs[fu[fs] @ fu[f] > cos_t]].sum(0))
            k = (G[f, c], *np.round(n * 1e3).astype(int), *np.round(UV[f, c] * 1e5).astype(int))
            if k not in out:
                out[k] = len(pos)
                pos.append(V[F[f, c]] - part.pivot)
                nor.append(n)
                uv.append(UV[f, c])
            idx.append(out[k])
    return (np.array(pos, np.float32), np.array(nor, np.float32), np.array(uv, np.float32), np.array(idx, np.uint32))


def write_glb(path, name, parts, baked, png, rake_deg, generator, material):
    blob, views, accessors = bytearray(), [], []

    def view(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), **({"target": target} if target else {})})
        blob.extend(data)
        return len(views) - 1

    def accessor(arr, kind, ctype, target, minmax=False):
        a = {"bufferView": view(arr.tobytes(), target), "componentType": ctype, "count": len(arr), "type": kind}
        if minmax:
            a["min"], a["max"] = arr.min(0).astype(float).tolist(), arr.max(0).astype(float).tolist()
        accessors.append(a)
        return len(accessors) - 1

    meshes, nodes = [], []
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        small = idx.max() < 65535
        prim = {"attributes": {"POSITION": accessor(pos, "VEC3", 5126, 34962, True),
                               "NORMAL": accessor(nor, "VEC3", 5126, 34962),
                               "TEXCOORD_0": accessor(uv, "VEC2", 5126, 34962)},
                "indices": accessor(idx.astype(np.uint16 if small else np.uint32), "SCALAR", 5123 if small else 5125, 34963),
                "material": 0}
        meshes.append({"name": p.name, "primitives": [prim]})
        nodes.append({"name": p.name, "mesh": len(meshes) - 1, "translation": p.pivot.tolist(), "extras": {"group": p.group}})
    image_view = view(png)
    nodes.append({"name": name, "children": list(range(len(parts))),
                  "extras": {"units": "studs", "forward": "-Z", "up": "+Y", "steeringRakeDeg": rake_deg,
                             "steeringAxis": "through FrontWheel centre, tilted back by steeringRakeDeg"}})
    gltf = {
        "asset": {"version": "2.0", "generator": generator},
        "scene": 0, "scenes": [{"name": name, "nodes": [len(nodes) - 1]}], "nodes": nodes, "meshes": meshes,
        "materials": [{"name": material, "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0,
                                                                   "roughnessFactor": 0.6}}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "images": [{"name": "skin", "bufferView": image_view, "mimeType": "image/png"}],
        "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    while len(blob) % 4:
        blob.append(0)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(blob)))
        fh.write(struct.pack("<I4s", len(js), b"JSON") + js)
        fh.write(struct.pack("<I4s", len(blob), b"BIN\x00") + bytes(blob))


def write_obj(path, name, parts, baked, texture, material):
    mtl = os.path.splitext(os.path.basename(path))[0] + ".mtl"
    lines = [f"# {name} - units: studs, +Y up, front faces -Z", f"mtllib {mtl}"]
    base = 1
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        lines.append(f"o {p.name}")
        lines += [f"v {a:.5f} {b:.5f} {c:.5f}" for a, b, c in pos + p.pivot]
        lines += [f"vt {a:.5f} {1 - b:.5f}" for a, b in uv]
        lines += [f"vn {a:.4f} {b:.4f} {c:.4f}" for a, b, c in nor]
        lines += [f"usemtl {material}", "s off"]
        lines += ["f " + " ".join(f"{i}/{i}/{i}" for i in t) for t in idx.reshape(-1, 3) + base]
        base += len(pos)
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(os.path.dirname(path), mtl), "w") as fh:
        fh.write(f"newmtl {material}\nKa 0 0 0\nKd 1 1 1\nKs 0.1 0.1 0.1\nNs 30\nd 1\nillum 2\nmap_Kd {texture}\n")


def report(parts, baked, density):
    total = 0
    print(f"{'part':12s} {'group':6s} {'tris':>5s}  size (studs)        pivot")
    for p, (pos, nor, uv, idx) in zip(parts, baked):
        size, ctr = pos.max(0) - pos.min(0), (pos.max(0) + pos.min(0)) / 2
        total += len(idx) // 3
        note = f"  bbox centre offset {np.abs(ctr).max():.4f}" if p.group == "Wheel" else ""
        print(f"{p.name:12s} {p.group:6s} {len(idx) // 3:5d}  {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}  "
              f"{np.round(p.pivot, 3).tolist()}{note}")
    allv = np.concatenate([b[0] + p.pivot for p, b in zip(parts, baked)])
    ext = allv.max(0) - allv.min(0)
    print(f"total: {total} triangles; bike {ext[0]:.2f} W x {ext[1]:.2f} H x {ext[2]:.2f} L studs; "
          f"panel texel density {density:.0f} px/stud")


def build(out_dir, name, atlas, parts, skins, paint, rake_deg, generator, material, up_labels=()):
    """Pack, bake and write every output. skins: {name: spec}; paint(painter, spec) draws one skin.
    The first skin is embedded in the GLB and referenced by the OBJ."""
    density = atlas.pack()
    baked = [bake(p) for p in parts]
    os.makedirs(os.path.join(out_dir, "skins"), exist_ok=True)
    for skin_name, spec in skins.items():
        painter = Painter(atlas, spec["primary"])
        paint(painter, spec)
        painter.save(os.path.join(out_dir, "skins", f"{skin_name}.png"))
    write_template(atlas, os.path.join(out_dir, "skin_template.png"), os.path.join(out_dir, "uv_overlay.png"), up_labels)
    first = next(iter(skins))
    with open(os.path.join(out_dir, "skins", f"{first}.png"), "rb") as fh:
        write_glb(os.path.join(out_dir, name + ".glb"), name, parts, baked, fh.read(), rake_deg, generator, material)
    write_obj(os.path.join(out_dir, name + ".obj"), name, parts, baked, f"skins/{first}.png", material)
    report(parts, baked, density)
