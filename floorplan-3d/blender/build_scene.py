"""Build the ground-floor flat in Blender from the floor plan.

Run with Blender's Python (bpy), e.g.
    python build_scene.py            # with `pip install bpy`
    blender -b -P build_scene.py     # with a Blender install

Outputs (relative to this file):
    ../flat.blend          the full Blender scene (lights + cameras for Cycles)
    ../web/flat.glb        the same model for the browser viewer
    ../web/scene.json      rooms, camera viewpoints and wall collision data

Plan coordinates: measurements were traced from the listing image, where
roughly 60 image pixels = 1 metre. PX/CX/CY below convert image pixels to
metres. Blender axes: +X = towards the street (right of the plan),
+Y = top of the plan, +Z = up.
"""
import json
import math
import os
import sys

import bpy  # noqa: E402  (must come before bmesh)
import bmesh
from mathutils import Euler, Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")
TEX = os.path.join(WEB, "tex")
sys.path.insert(0, HERE)
from textures import TILE_METERS  # noqa: E402

PX = 60.0
CX, CY = 965.0, 605.0
H = 2.8  # ceiling height


def bx(px):
    return (px - CX) / PX


def by(py):
    return -(py - CY) / PX


def P(px, py):
    return Vector((bx(px), by(py)))


# ---------------------------------------------------------------- materials
def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_lin(h, a=1.0):
    h = h.lstrip("#")
    return tuple(srgb_to_lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (a,)


MATS = {}
TILE = {}  # material name -> metres per texture repeat (for UVs)


def set_input(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return


def pmat(name, color="#ffffff", rough=0.5, metal=0.0, tex=None, transmission=0.0,
         emit=None, emit_strength=0.0, sheen=0.0, coat=0.0, alpha=1.0, tile=1.0):
    m = bpy.data.materials.new(name)
    try:
        m.use_nodes = True
    except Exception:
        pass
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    set_input(bsdf, ["Base Color"], hex_lin(color))
    set_input(bsdf, ["Roughness"], rough)
    set_input(bsdf, ["Metallic"], metal)
    if transmission:
        set_input(bsdf, ["Transmission Weight", "Transmission"], transmission)
        set_input(bsdf, ["IOR"], 1.45)
    if emit:
        set_input(bsdf, ["Emission Color", "Emission"], hex_lin(emit))
        set_input(bsdf, ["Emission Strength"], emit_strength)
    if sheen:
        set_input(bsdf, ["Sheen Weight", "Sheen"], sheen)
    if coat:
        set_input(bsdf, ["Coat Weight", "Clearcoat"], coat)
    if alpha < 1:
        set_input(bsdf, ["Alpha"], alpha)
    if tex:
        img = bpy.data.images.load(os.path.join(TEX, tex + ".jpg"), check_existing=True)
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = img
        tn.location = (-400, 200)
        nt.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
        tile = TILE_METERS[tex]
    m.diffuse_color = hex_lin(color)
    MATS[name] = m
    TILE[name] = tile
    return m


def build_materials():
    pmat("WallPaint", "#EEEAE2", 0.92)
    pmat("WallCap", "#3A3836", 0.9)
    pmat("Ceiling", "#F5F3EF", 0.95)
    pmat("GardenWall", "#D2BD93", 0.95, tex="limestone")
    pmat("Ground", "#9C9686", 0.95)
    pmat("Asphalt", "#4A4B4D", 0.9)
    pmat("Pavement", "#CFC7B6", 0.9, tex="limestone")
    # furniture & fittings
    pmat("Oak", "#B98D5F", 0.5)
    pmat("Walnut", "#5B3F2C", 0.45)
    pmat("Joinery", "#ECE7DE", 0.55)
    pmat("Cabinet", "#4F6B5E", 0.45)
    pmat("CabinetCarcass", "#2A2C2B", 0.6)
    pmat("Counter", "#EEECE7", 0.18, tex="marble")
    pmat("Splash", "#F3F1EC", 0.08, coat=0.6)
    pmat("Steel", "#C9CBCC", 0.28, metal=1.0)
    pmat("Chrome", "#E4E6E8", 0.06, metal=1.0)
    pmat("Brass", "#C69C55", 0.25, metal=1.0)
    pmat("BlackGlass", "#0E0F10", 0.05, coat=1.0)
    pmat("Appliance", "#F2F2F0", 0.3)
    pmat("Ceramic", "#F7F7F4", 0.08, coat=0.5)
    pmat("Mirror", "#DDE2E6", 0.02, metal=1.0)
    pmat("Glass", "#E8F1F3", 0.0, transmission=1.0, alpha=0.25)
    pmat("Frame", "#353738", 0.4, metal=0.5)
    pmat("DoorWhite", "#F1EEE8", 0.5)
    pmat("FrontDoor", "#2F5D4E", 0.4)
    pmat("Sofa", "#8D8F86", 0.95, sheen=0.5)
    pmat("Linen", "#F2EFE9", 0.9, sheen=0.4)
    pmat("Duvet", "#E7E1D6", 0.95, sheen=0.4)
    pmat("Throw", "#C27C55", 0.95, sheen=0.5)
    pmat("Accent", "#3F5E73", 0.9, sheen=0.4)
    pmat("Mustard", "#C9973E", 0.9, sheen=0.4)
    pmat("Upholstery", "#BFB3A1", 0.95, sheen=0.4)
    pmat("Leather", "#7A4A2E", 0.45)
    pmat("Rubber", "#1B1B1C", 0.85)
    pmat("PlasticDark", "#2B2D2F", 0.5)
    pmat("Rug", "#D6CBB8", 1.0)
    pmat("RugBlue", "#5B7188", 1.0)
    pmat("Leaf", "#3E6A3A", 0.6)
    pmat("LeafLight", "#6E8F4E", 0.6)
    pmat("Pot", "#B5653F", 0.8)
    pmat("PotWhite", "#EDEBE6", 0.5)
    pmat("Soil", "#3B2E25", 1.0)
    pmat("Bark", "#6E5A48", 0.9)
    pmat("Wicker", "#9A7650", 0.85)
    pmat("Cushion", "#ECE6DA", 0.95, sheen=0.4)
    pmat("Canvas", "#F0EBE0", 0.9)
    pmat("LampShade", "#F6EBD8", 0.8, emit="#FFD9A0", emit_strength=0.0)
    pmat("Bulb", "#FFF4E0", 0.3, emit="#FFE2B0", emit_strength=4.0)
    pmat("Screen", "#0A0B0C", 0.3, coat=0.25)
    pmat("Art1", "#C46B4A", 0.9)
    pmat("Art2", "#2F5D73", 0.9)
    pmat("Art3", "#D9B45A", 0.9)
    pmat("Book1", "#8A3B2E", 0.8)
    pmat("Book2", "#2E4A5E", 0.8)
    pmat("Book3", "#C9B48A", 0.8)
    pmat("Stone", "#D8C8A6", 0.8, tex="limestone")
    pmat("Water", "#7FB2BF", 0.05, transmission=0.6)
    for f in TILE_METERS:
        pmat("Tex_" + f, "#ffffff", {"marble": 0.15, "porcelain": 0.25, "maltese": 0.35,
                                     "terrazzo": 0.3, "oak": 0.45, "walnut": 0.4}.get(f, 0.8),
             tex=f)


# ------------------------------------------------------------- mesh builder
class Builder:
    """Accumulates boxes / cylinders / spheres into one mesh with UVs."""

    def __init__(self):
        self.v, self.f, self.uv, self.fm, self.smooth = [], [], [], [], []
        self.mats = []
        self.xf = Matrix.Identity(4)

    def mi(self, name):
        m = MATS[name]
        if m not in self.mats:
            self.mats.append(m)
        return self.mats.index(m)

    def push(self, ox=0.0, oy=0.0, rz=0.0, oz=0.0):
        """Return a context that offsets/rotates subsequent primitives."""
        b = self

        class Ctx:
            def __enter__(s):
                s.prev = b.xf.copy()
                b.xf = b.xf @ Matrix.Translation((ox, oy, oz)) @ Matrix.Rotation(math.radians(rz), 4, "Z")

            def __exit__(s, *a):
                b.xf = s.prev
        return Ctx()

    def _add(self, verts, faces, uvs, mat, smooth=False):
        base = len(self.v)
        idx = self.mi(mat)
        for p in verts:
            self.v.append((self.xf @ Vector(p)).to_tuple())
        for fc, fu in zip(faces, uvs):
            self.f.append(tuple(base + i for i in fc))
            self.uv.append(fu)
            self.fm.append(idx)
            self.smooth.append(smooth)

    def boxr(self, center, size, mat, rot=(0, 0, 0)):
        cx, cy, cz = center
        sx, sy, sz = (s / 2 for s in size)
        R = Euler(tuple(math.radians(a) for a in rot)).to_matrix()
        loc = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
               (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
        verts = [tuple(Vector((cx, cy, cz)) + R @ Vector(p)) for p in loc]
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (3, 0, 4, 7), (1, 2, 6, 5)]
        t = TILE.get(mat, 1.0)
        W, D, Hh = size[0] / t, size[1] / t, size[2] / t
        uvs = [
            [(0, 0), (0, D), (W, D), (W, 0)],
            [(0, 0), (W, 0), (W, D), (0, D)],
            [(0, 0), (W, 0), (W, Hh), (0, Hh)],
            [(0, 0), (W, 0), (W, Hh), (0, Hh)],
            [(0, 0), (D, 0), (D, Hh), (0, Hh)],
            [(0, 0), (D, 0), (D, Hh), (0, Hh)],
        ]
        self._add(verts, faces, uvs, mat)

    def box(self, x0, x1, y0, y1, z0, z1, mat):
        self.boxr(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
                  (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)), mat)

    def cyl(self, cx, cy, z0, z1, r, mat, r_top=None, n=24, axis="z", sx=1.0, sy=1.0, caps=True):
        """Cylinder/cone. axis 'z' vertical; 'x'/'y' horizontal (z0..z1 then
        means extent along that axis, centred at (cx, cy) with height cz=r_top?)."""
        r_top = r if r_top is None else r_top
        verts, faces, uvs = [], [], []
        for i in range(n):
            a = 2 * math.pi * i / n
            verts.append((math.cos(a) * r * sx, math.sin(a) * r * sy, z0))
            verts.append((math.cos(a) * r_top * sx, math.sin(a) * r_top * sy, z1))
        circ = 2 * math.pi * r
        for i in range(n):
            j = (i + 1) % n
            faces.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
            uvs.append([(circ * i / n, z0), (circ * (i + 1) / n, z0), (circ * (i + 1) / n, z1), (circ * i / n, z1)])
        side_faces = len(faces)
        if caps:
            faces.append(tuple(2 * i for i in reversed(range(n))))
            uvs.append([(verts[2 * i][0], verts[2 * i][1]) for i in reversed(range(n))])
            faces.append(tuple(2 * i + 1 for i in range(n)))
            uvs.append([(verts[2 * i + 1][0], verts[2 * i + 1][1]) for i in range(n)])
        if axis == "z":
            M = Matrix.Translation((cx, cy, 0))
        elif axis == "x":  # cylinder lying along X; (cx,cy) = centre y,z
            M = Matrix.Translation((0, cx, cy)) @ Matrix.Rotation(math.radians(90), 4, "Y")
        else:  # along Y; (cx,cy) = centre x,z
            M = Matrix.Translation((cx, 0, cy)) @ Matrix.Rotation(math.radians(-90), 4, "X")
        verts = [tuple(M @ Vector(p)) for p in verts]
        base = len(self.v)
        idx = self.mi(mat)
        for p in verts:
            self.v.append((self.xf @ Vector(p)).to_tuple())
        for k, (fc, fu) in enumerate(zip(faces, uvs)):
            self.f.append(tuple(base + i for i in fc))
            self.uv.append(fu)
            self.fm.append(idx)
            self.smooth.append(k < side_faces)

    def sph(self, cx, cy, cz, r, mat, sx=1.0, sy=1.0, sz=1.0, n=14):
        verts, faces, uvs = [], [], []
        rings = n // 2
        for i in range(rings + 1):
            th = math.pi * i / rings
            for j in range(n):
                ph = 2 * math.pi * j / n
                verts.append((cx + r * sx * math.sin(th) * math.cos(ph),
                              cy + r * sy * math.sin(th) * math.sin(ph),
                              cz + r * sz * math.cos(th)))
        for i in range(rings):
            for j in range(n):
                a = i * n + j
                b = i * n + (j + 1) % n
                c = (i + 1) * n + (j + 1) % n
                d = (i + 1) * n + j
                faces.append((a, d, c, b))
                uvs.append([(j / n, i / rings), (j / n, (i + 1) / rings),
                            ((j + 1) / n, (i + 1) / rings), ((j + 1) / n, i / rings)])
        self._add(verts, faces, uvs, mat, smooth=True)

    def build(self, name, loc=(0, 0, 0), rotz=0.0, bevel=0.0, collection=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        me.update()
        for m in self.mats:
            me.materials.append(m)
        uvl = me.uv_layers.new(name="UVMap")
        li = 0
        for poly, fu, mi, sm in zip(me.polygons, self.uv, self.fm, self.smooth):
            poly.material_index = mi
            poly.use_smooth = sm
            for k, loop in enumerate(poly.loop_indices):
                uvl.data[loop].uv = fu[k]
        ob = bpy.data.objects.new(name, me)
        ob.location = loc
        ob.rotation_euler = (0, 0, math.radians(rotz))
        (collection or bpy.context.scene.collection).objects.link(ob)
        if bevel > 0:
            mod = ob.modifiers.new("Bevel", "BEVEL")
            mod.width = bevel
            mod.segments = 2
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(40)
            mod.harden_normals = False
        return ob


def coll(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


# ------------------------------------------------------------------- rooms
# Polygons in image pixels (traced from the listing plan).
ROOMS = [
    # id, name, indoor, finish, polygon
    ("gym", "Gym", True, "concrete", [(400, 371), (672, 405), (672, 560), (400, 560)]),
    ("utility", "Utility", True, "porcelain", [(672, 405), (976, 428), (976, 502), (672, 502)]),
    ("hall", "Hallway", True, "maltese", [(976, 428), (1030, 432), (1030, 448), (1463, 448), (1463, 510), (976, 510)]),
    ("entry", "Apartment entrance", True, "maltese", [(1212, 510), (1265, 510), (1265, 598), (1212, 598)]),
    ("stairs", "Stairs", True, "maltese", [(1265, 510), (1353, 510), (1353, 598), (1265, 598)]),
    ("ens", "Ensuite", True, "marble", [(672, 502), (854, 502), (854, 598), (672, 598)]),
    ("bath1", "Bathroom", True, "porcelain", [(854, 502), (976, 502), (976, 598), (854, 598)]),
    ("box", "Box room", True, "concrete", [(976, 510), (1124, 510), (1124, 598), (976, 598)]),
    ("lift", "Lift", True, "concrete", [(1124, 510), (1212, 510), (1212, 598), (1124, 598)]),
    ("wc", "WC", True, "porcelain", [(1353, 510), (1463, 510), (1463, 598), (1353, 598)]),
    ("kitA", "Kitchen / living", True, "terrazzo", [(1463, 448), (1790, 448), (1790, 598), (1463, 598)]),
    ("bed1", "Bedroom 1", True, "oak", [(560, 560), (672, 560), (672, 598), (762, 598), (762, 796), (560, 787)]),
    ("corr", "Corridor", True, "maltese", [(762, 598), (1790, 598), (1790, 666), (1388, 666), (1388, 760), (1120, 760), (1120, 656), (762, 656)]),
    ("bath2", "Bathroom 2", True, "porcelain", [(762, 656), (885, 656), (885, 800), (762, 796)]),
    ("bed2", "Bedroom 2", True, "oak", [(885, 656), (1120, 656), (1120, 845), (885, 845)]),
    ("kitB", "Kitchen / living / dining", True, "oak", [(1388, 666), (1790, 666), (1790, 845), (1388, 845)]),
    ("court", "Courtyard", False, "limestone", [(1120, 760), (1388, 760), (1388, 845), (1120, 845)]),
    ("yard", "Garden yard", False, "limestone", [(110, 365), (400, 371), (400, 560), (560, 560), (560, 787), (80, 815)]),
    ("patio", "Patio", False, "terracotta", [(270, 560), (560, 560), (560, 725), (270, 725)]),
    ("planted", "Planted yard", False, "pebble", [(305, 371), (400, 371), (400, 545), (305, 545)]),
]
LABELLED = {"gym", "utility", "hall", "ens", "bath1", "box", "wc", "kitA", "bed1", "corr",
            "bath2", "bed2", "kitB", "court", "yard", "patio", "lift", "stairs"}


def polygon_object(name, pts_px, z, mat_name, collection, down=False):
    pts = [P(*p) for p in pts_px]
    t = TILE[mat_name]
    bm = bmesh.new()
    vs = [bm.verts.new((p.x, p.y, z)) for p in pts]
    face = bm.faces.new(vs if not down else list(reversed(vs)))
    uv = bm.loops.layers.uv.new("UVMap")
    for loop in face.loops:
        co = loop.vert.co
        loop[uv].uv = (co.x / t, co.y / t)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(MATS[mat_name])
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


def centroid(pts_px):
    # area-weighted polygon centroid in metres
    A = cx = cy = 0.0
    pts = [P(*p) for p in pts_px]
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % len(pts)]
        c = x0 * y1 - x1 * y0
        A += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    A *= 0.5
    return cx / (6 * A), cy / (6 * A), abs(A)


def point_in_poly(x, y, pts):
    inside = False
    for i in range(len(pts)):
        x0, y0 = pts[i]
        x1, y1 = pts[i - 1]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


DOWNLIGHTS = None
DOWNLIGHT_POS = []


def build_floors():
    global DOWNLIGHTS
    cf = coll("Floors")
    cc = coll("Ceilings")
    DOWNLIGHTS = Builder()
    info = []
    for i, (rid, name, indoor, finish, poly) in enumerate(ROOMS):
        src = MATS["Tex_" + finish]
        m = src.copy()
        m.name = "Floor_" + rid
        MATS[m.name] = m
        TILE[m.name] = TILE["Tex_" + finish]
        z = (0.012 if indoor else 0.004) + 0.0004 * i
        if rid in ("patio", "planted"):
            z += 0.006
        polygon_object("floor_" + rid, poly, z, m.name, cf)
        if indoor:
            polygon_object("ceil_" + rid, poly, H, "Ceiling", cc, down=True)
        cx, cy, area = centroid(poly)
        if indoor and rid not in ("lift",):
            xs = [bx(p[0]) for p in poly]
            ys = [by(p[1]) for p in poly]
            nx = max(1, round((max(xs) - min(xs)) / 1.7))
            ny = max(1, round((max(ys) - min(ys)) / 1.7))
            for ix in range(nx):
                for iy in range(ny):
                    x = min(xs) + (ix + 0.5) * (max(xs) - min(xs)) / nx
                    y = min(ys) + (iy + 0.5) * (max(ys) - min(ys)) / ny
                    if point_in_poly(x, y, [P(*p) for p in poly]):
                        DOWNLIGHT_POS.append((x, y))
                        DOWNLIGHTS.cyl(x, y, H - 0.012, H - 0.002, 0.06, "Frame", n=16)
                        DOWNLIGHTS.cyl(x, y, H - 0.016, H - 0.011, 0.045, "Bulb", n=16)
        info.append({"id": rid, "name": name, "indoor": indoor, "finish": finish,
                     "tile": TILE_METERS[finish], "area": round(area, 1),
                     "c": [round(cx, 3), round(cy, 3)], "label": rid in LABELLED,
                     "poly": [[round(bx(x), 3), round(by(y), 3)] for x, y in poly]})
    DOWNLIGHTS.build("ceil_downlights", collection=cc)
    # ground, pavement and street around the house
    b = Builder()
    b.box(-200, 200, -200, 200, -0.06, -0.01, "Ground")
    b.build("ground", collection=cf)
    pv = Builder()
    pv.box(bx(1790) + 0.15, bx(1790) + 2.4, -6.0, 5.5, -0.01, 0.02, "Pavement")
    pv.build("pavement", collection=cf)
    st = Builder()
    st.box(bx(1790) + 2.4, bx(1790) + 9.5, -30, 30, -0.03, -0.005, "Asphalt")
    st.build("street", collection=cf)
    return info


# ------------------------------------------------------------------- walls
# (start px, end px, thickness m, openings [(from, to, kind, swing)])
# opening coordinates are along the wall's dominant axis, in image px.
WALLS = [
    ((400, 371), (672, 405), 0.30, []),
    ((672, 405), (1030, 432), 0.30, []),
    ((1030, 432), (1030, 448), 0.30, []),
    ((1030, 448), (1790, 448), 0.30, []),
    ((1790, 448), (1790, 845), 0.30, [(475, 575, "win"), (607, 660, "front", -1), (690, 820, "win")]),
    ((1790, 845), (885, 845), 0.30, []),
    ((885, 845), (885, 800), 0.20, []),
    ((885, 800), (762, 796), 0.30, []),
    ((762, 796), (560, 787), 0.30, []),
    ((560, 787), (560, 560), 0.25, [(640, 740, "win")]),
    ((400, 560), (560, 560), 0.25, [(415, 545, "slide")]),
    ((560, 560), (672, 560), 0.12, []),
    ((400, 560), (400, 371), 0.25, [(420, 520, "win")]),
    ((672, 405), (672, 598), 0.12, [(428, 474, "door", -1)]),
    ((672, 502), (976, 502), 0.12, []),
    ((976, 428), (976, 598), 0.12, [(452, 497, "door", 1)]),
    ((854, 502), (854, 598), 0.12, []),
    ((976, 510), (1212, 510), 0.12, []),
    ((1353, 510), (1463, 510), 0.12, [(1380, 1424, "door", 1)]),
    ((1124, 510), (1124, 598), 0.12, []),
    ((1212, 510), (1212, 598), 0.12, []),
    ((1265, 510), (1265, 598), 0.12, []),
    ((1353, 510), (1353, 598), 0.12, []),
    ((1463, 448), (1463, 598), 0.12, [(458, 503, "door", 1)]),
    ((672, 598), (1790, 598), 0.12, [(697, 742, "door", -1), (885, 930, "door", -1),
                                      (1055, 1100, "door", 1), (1146, 1192, "lift"),
                                      (1217, 1261, "aptdoor", 1)]),
    ((762, 598), (762, 796), 0.12, [(608, 650, "door", -1)]),
    ((762, 656), (1120, 656), 0.12, [(790, 832, "door", -1), (1068, 1110, "door", -1)]),
    ((885, 656), (885, 800), 0.12, []),
    ((1120, 656), (1120, 845), 0.20, [(775, 830, "win")]),
    ((1120, 760), (1388, 760), 0.20, [(1168, 1340, "slide")]),
    ((1388, 666), (1388, 845), 0.20, [(778, 830, "win")]),
    ((1388, 666), (1790, 666), 0.12, [(1420, 1468, "door", -1)]),
]

GARDEN_WALLS = [
    ((110, 365), (400, 371), 0.25),
    ((110, 365), (80, 815), 0.25),
    ((80, 815), (560, 787), 0.25),
]


def obox_verts(a, b, t, z0, z1):
    d = (b - a)
    L = d.length
    u = d / L
    v = Vector((-u.y, u.x))
    return u, v, L


def wall_piece(builder, a, b, t, z0, z1, mat="WallPaint"):
    """Oriented box from 2D point a to b (metres)."""
    d = b - a
    L = d.length
    if L < 1e-4:
        return
    ang = math.degrees(math.atan2(d.y, d.x))
    c = (a + b) / 2
    builder.boxr((c.x, c.y, (z0 + z1) / 2), (L, t, z1 - z0), mat, rot=(0, 0, ang))


COLLIDERS = []  # [x0,y0,x1,y1,thickness] in metres (Blender XY)


def build_walls():
    cw = coll("Walls")
    co = coll("Openings")
    walls = Builder()
    opn = Builder()
    leaves = []
    for (p0, p1, t, ops) in WALLS:
        a, b = P(*p0), P(*p1)
        d = b - a
        L = d.length
        u = d / L
        horizontal = abs(p1[0] - p0[0]) >= abs(p1[1] - p0[1])
        ext = t / 2 - 0.003  # close corners; stop just short of coplanar faces (Cycles artefacts)
        a2, b2 = a - u * ext, b + u * ext
        L2 = L + 2 * ext

        def param(coord):
            if horizontal:
                return ((coord - p0[0]) / (p1[0] - p0[0])) * L + ext
            return ((coord - p0[1]) / (p1[1] - p0[1])) * L + ext

        spans = []
        for op in ops:
            s0, s1 = sorted((param(op[0]), param(op[1])))
            spans.append((s0, s1, op[2], op[3] if len(op) > 3 else 1))
        spans.sort()
        cur = 0.0
        for s0, s1, kind, swing in spans:
            if s0 > cur:
                wall_piece(walls, a2 + u * cur, a2 + u * s0, t, 0, H)
                COLLIDERS.append([*(a2 + u * cur), *(a2 + u * s0), t])
            pa, pb = a2 + u * s0, a2 + u * s1
            w = s1 - s0
            nrm = Vector((-u.y, u.x))
            if kind in ("door", "aptdoor", "front", "lift"):
                wall_piece(walls, pa, pb, t, 2.1, H)
                # frame / architrave
                for pp in (pa + u * 0.025, pb - u * 0.025):
                    wall_piece(opn, pp - u * 0.025, pp + u * 0.025, t + 0.03, 0, 2.1,
                               "DoorWhite" if kind != "front" else "FrontDoor")
                wall_piece(opn, pa, pb, t + 0.03, 2.1, 2.16,
                           "DoorWhite" if kind != "front" else "FrontDoor")
                if kind == "lift":
                    wall_piece(opn, pa + u * 0.05, pb - u * 0.05, 0.05, 0, 2.1, "Steel")
                    COLLIDERS.append([*pa, *pb, t])
                else:
                    leaves.append((pa + u * 0.05, u, nrm * swing, w - 0.1, t, kind))
            elif kind == "win":
                wall_piece(walls, pa, pb, t, 0, 0.9)
                wall_piece(walls, pa, pb, t, 2.2, H)
                COLLIDERS.append([*pa, *pb, t])
                # frame
                fr = 0.05
                wall_piece(opn, pa, pa + u * fr, 0.08, 0.9, 2.2, "Frame")
                wall_piece(opn, pb - u * fr, pb, 0.08, 0.9, 2.2, "Frame")
                wall_piece(opn, pa, pb, 0.08, 0.9, 0.9 + fr, "Frame")
                wall_piece(opn, pa, pb, 0.08, 2.2 - fr, 2.2, "Frame")
                if w > 1.2:
                    m = (pa + pb) / 2
                    wall_piece(opn, m - u * 0.025, m + u * 0.025, 0.08, 0.9, 2.2, "Frame")
                wall_piece(opn, pa + u * fr, pb - u * fr, 0.012, 0.9 + fr, 2.2 - fr, "Glass")
                # sill
                wall_piece(opn, pa, pb, t + 0.06, 0.88, 0.92, "Stone")
            elif kind == "slide":
                wall_piece(walls, pa, pb, t, 2.3, H)
                fr = 0.05
                wall_piece(opn, pa, pa + u * fr, 0.1, 0, 2.3, "Frame")
                wall_piece(opn, pb - u * fr, pb, 0.1, 0, 2.3, "Frame")
                wall_piece(opn, pa, pb, 0.1, 2.3 - fr, 2.3, "Frame")
                wall_piece(opn, pa, pb, 0.1, 0, 0.03, "Frame")
                half = w / 2
                # fixed panel (first half) and sliding panel parked behind it
                for k, off in enumerate((-0.025, 0.025)):
                    q0 = pa + u * (fr + (0 if k == 0 else half * 0.35))
                    q1 = q0 + u * (half)
                    q0o, q1o = q0 + nrm * off, q1 + nrm * off
                    wall_piece(opn, q0o, q0o + u * 0.04, 0.04, 0.03, 2.25, "Frame")
                    wall_piece(opn, q1o - u * 0.04, q1o, 0.04, 0.03, 2.25, "Frame")
                    wall_piece(opn, q0o + u * 0.04, q1o - u * 0.04, 0.012, 0.05, 2.23, "Glass")
                COLLIDERS.append([*pa, *(pa + u * (half * 1.35 + fr)), t])
            cur = s1
        if cur < L2:
            wall_piece(walls, a2 + u * cur, b2, t, 0, H)
            COLLIDERS.append([*(a2 + u * cur), *b2, t])
    wob = walls.build("Walls", collection=cw)
    # top faces get the dark "poche" cap
    cap_idx = len(wob.data.materials)
    wob.data.materials.append(MATS["WallCap"])
    for poly in wob.data.polygons:
        if poly.normal.z > 0.9 and poly.center.z > H - 0.01:
            poly.material_index = cap_idx
    opn.build("Openings", collection=co)

    # door leaves, slightly open
    for i, (hinge, u, n, w, t, kind) in enumerate(leaves):
        b = Builder()
        open_deg = 70 if kind != "front" else 85
        mat = {"front": "FrontDoor", "aptdoor": "Walnut"}.get(kind, "DoorWhite")
        dirv = (u * math.cos(math.radians(open_deg)) + n * math.sin(math.radians(open_deg)))
        hinge_off = hinge + n * (t / 2 - 0.02)
        c = hinge_off + dirv * (w / 2)
        ang = math.degrees(math.atan2(dirv.y, dirv.x))
        b.boxr((c.x, c.y, 1.04), (w, 0.04, 2.06), mat, rot=(0, 0, ang))
        hp = hinge_off + dirv * (w - 0.07)
        side = Vector((-dirv.y, dirv.x))
        for s in (1, -1):
            q = hp + side * 0.035 * s
            b.boxr((q.x, q.y, 1.02), (0.12, 0.015, 0.02), "Brass" if kind == "front" else "Chrome", rot=(0, 0, ang))
        b.build(f"door_{i:02d}", collection=co, bevel=0.004)

    gw = Builder()
    for p0, p1, t in GARDEN_WALLS:
        a, b = P(*p0), P(*p1)
        u = (b - a).normalized()
        wall_piece(gw, a - u * (t / 2 - .003), b + u * (t / 2 - .003), t, 0, 1.9, "GardenWall")
        wall_piece(gw, a - u * t / 2, b + u * t / 2, t + 0.06, 1.9, 1.96, "Stone")
        COLLIDERS.append([*(a - u * t / 2), *(b + u * t / 2), t])
    gw.build("GardenWalls", collection=cw)


# --------------------------------------------------------------- furniture
def bed(b, w=1.6, l=2.05):
    b.box(-w / 2 + 0.06, w / 2 - 0.06, -l / 2 + 0.06, l / 2 - 0.06, 0, 0.1, "Walnut")
    b.box(-w / 2 - 0.04, w / 2 + 0.04, -l / 2, l / 2, 0.1, 0.32, "Upholstery")
    b.box(-w / 2, w / 2, -l / 2 + 0.03, l / 2 - 0.05, 0.32, 0.55, "Linen")
    b.box(-w / 2 - 0.03, w / 2 + 0.03, -l / 2 - 0.02, l / 2 - 0.6, 0.5, 0.6, "Duvet")
    b.box(-w / 2 - 0.04, w / 2 + 0.04, -l / 2 - 0.03, -l / 2 + 0.5, 0.58, 0.63, "Throw")
    for s in (-1, 1):
        b.boxr((s * w / 4, l / 2 - 0.3, 0.64), (w / 2 - 0.12, 0.36, 0.16), "Linen", rot=(-12, 0, 0))
    b.boxr((0.0, l / 2 - 0.5, 0.66), (0.45, 0.14, 0.32), "Accent", rot=(-15, 0, 0))
    b.box(-w / 2 - 0.08, w / 2 + 0.08, l / 2 - 0.02, l / 2 + 0.07, 0.1, 1.2, "Upholstery")


def nightstand(b, lamp=True):
    b.box(-0.24, 0.24, -0.2, 0.2, 0.15, 0.55, "Oak")
    for sx in (-0.2, 0.2):
        for sy in (-0.16, 0.16):
            b.cyl(sx, sy, 0, 0.15, 0.015, "Walnut", n=8)
    b.box(-0.2, 0.2, -0.205, -0.2, 0.36, 0.38, "Walnut")
    if lamp:
        b.cyl(0.05, 0.02, 0.55, 0.58, 0.07, "Brass")
        b.cyl(0.05, 0.02, 0.58, 0.86, 0.01, "Brass", n=8)
        b.cyl(0.05, 0.02, 0.78, 0.99, 0.15, "LampShade", r_top=0.11)
        b.sph(0.05, 0.02, 0.84, 0.04, "Bulb", n=8)
    b.box(-0.18, -0.02, -0.08, 0.1, 0.55, 0.6, "Book2")


def wardrobe(b, w, h=2.3, d=0.6):
    b.box(-w / 2, w / 2, -d / 2 + 0.02, d / 2, 0, h, "Oak")
    n = max(2, round(w / 0.5))
    pw = w / n
    for i in range(n):
        x0 = -w / 2 + i * pw + 0.003
        b.box(x0, x0 + pw - 0.006, -d / 2, -d / 2 + 0.022, 0.003, h - 0.003, "Joinery")
        hx = x0 + (pw - 0.06 if i % 2 == 0 else 0.06)
        b.box(hx - 0.008, hx + 0.008, -d / 2 - 0.025, -d / 2, 0.9, 1.3, "Brass")


def sofa(b, w=2.2, d=0.95, mat="Sofa"):
    b.box(-w / 2, w / 2, -d / 2, d / 2, 0.1, 0.42, mat)
    b.box(-w / 2, w / 2, d / 2 - 0.22, d / 2, 0.42, 0.82, mat)
    for s in (-1, 1):
        b.box(s * w / 2 - (0.18 if s > 0 else 0), s * w / 2 + (0.18 if s < 0 else 0), -d / 2, d / 2, 0.1, 0.62, mat)
    inner = w - 0.36
    n = 3 if w > 2 else 2
    cw = inner / n
    for i in range(n):
        x0 = -inner / 2 + i * cw
        b.box(x0 + 0.01, x0 + cw - 0.01, -d / 2 + 0.03, d / 2 - 0.22, 0.42, 0.55, mat)
        b.boxr((x0 + cw / 2, d / 2 - 0.3, 0.7), (cw - 0.03, 0.18, 0.4), mat, rot=(-10, 0, 0))
    b.boxr((-inner / 2 + 0.25, d / 2 - 0.42, 0.72), (0.42, 0.13, 0.42), "Mustard", rot=(-14, 0, 12))
    b.boxr((inner / 2 - 0.25, d / 2 - 0.42, 0.72), (0.42, 0.13, 0.42), "Throw", rot=(-14, 0, -10))
    for sx in (-w / 2 + 0.08, w / 2 - 0.08):
        for sy in (-d / 2 + 0.08, d / 2 - 0.08):
            b.cyl(sx, sy, 0, 0.1, 0.02, "Walnut", n=8)


def coffee_table(b, w=1.0, d=0.55):
    b.cyl(0, 0, 0.36, 0.4, w / 2, "Counter", sy=d / w, n=32)
    b.cyl(0, 0, 0, 0.36, 0.14, "Walnut", sy=d / w * 1.3, n=20)
    b.box(-0.2, 0.05, -0.1, 0.12, 0.4, 0.46, "Book1")
    b.cyl(0.25, 0.0, 0.4, 0.55, 0.06, "PotWhite")


def tv_unit(b, w=1.8):
    b.box(-w / 2, w / 2, -0.2, 0.2, 0.12, 0.5, "Walnut")
    for i in range(3):
        x0 = -w / 2 + i * w / 3
        b.box(x0 + 0.004, x0 + w / 3 - 0.004, -0.205, -0.2, 0.13, 0.49, "Oak")
    for sx in (-w / 2 + 0.06, w / 2 - 0.06):
        b.cyl(sx, 0, 0, 0.12, 0.02, "Brass", n=8)
    b.box(-0.68, 0.68, 0.12, 0.16, 0.85, 1.62, "Screen")
    b.box(-0.69, 0.69, 0.16, 0.18, 0.84, 1.63, "PlasticDark")
    b.cyl(w / 2 - 0.2, 0, 0.5, 0.75, 0.08, "PotWhite")
    b.sph(w / 2 - 0.2, 0, 0.88, 0.16, "Leaf", sz=1.2)


def chair(b, x, y, rz):
    with b.push(x, y, rz):
        b.box(-0.22, 0.22, -0.22, 0.22, 0.43, 0.47, "Oak")
        b.box(-0.2, 0.2, -0.2, 0.2, 0.47, 0.5, "Upholstery")
        for sx in (-0.19, 0.19):
            for sy in (-0.19, 0.19):
                b.cyl(sx, sy, 0, 0.43, 0.017, "Walnut", n=8)
        b.boxr((0, 0.2, 0.68), (0.42, 0.03, 0.3), "Oak", rot=(-6, 0, 0))
        for sx in (-0.19, 0.19):
            b.box(sx - 0.015, sx + 0.015, 0.185, 0.215, 0.47, 0.82, "Walnut")


def dining(b, w=1.6, d=0.9, chairs=6, pendant=True):
    b.box(-w / 2, w / 2, -d / 2, d / 2, 0.72, 0.76, "Oak")
    for sx in (-w / 2 + 0.08, w / 2 - 0.08):
        for sy in (-d / 2 + 0.08, d / 2 - 0.08):
            b.box(sx - 0.03, sx + 0.03, sy - 0.03, sy + 0.03, 0, 0.72, "Walnut")
    per = chairs // 2
    for i in range(per):
        x = -w / 2 + w * (i + 0.5) / per
        chair(b, x, -d / 2 - 0.12, 180)
        chair(b, x, d / 2 + 0.12, 0)
    b.cyl(0.1, 0.05, 0.76, 0.98, 0.07, "PotWhite", r_top=0.05)
    b.sph(0.1, 0.05, 1.05, 0.1, "LeafLight", sz=0.8)
    b.box(-0.45, -0.1, -0.12, 0.15, 0.76, 0.765, "Linen")
    if pendant:
        for px in ((-w / 4, w / 4) if w > 1.3 else (0,)):
            b.cyl(px, 0, 1.55, H, 0.004, "PlasticDark", n=6)
            b.cyl(px, 0, 1.42, 1.62, 0.18, "Brass", r_top=0.04, caps=False)
            b.sph(px, 0, 1.47, 0.05, "Bulb", n=8)


def kitchen_run(b, L, fridge=True, sink=None, hob=None, upper=True, window=None):
    """Run along local x from -L/2..L/2, back against +y, facing -y."""
    x0 = -L / 2
    b.box(x0, L / 2, -0.25, 0.3, 0, 0.1, "CabinetCarcass")
    start = x0
    if fridge:
        b.box(x0, x0 + 0.7, -0.33, 0.3, 0, 2.05, "Steel")
        b.box(x0 + 0.005, x0 + 0.695, -0.335, -0.33, 1.2, 1.205, "PlasticDark")
        for z0, z1 in ((0.3, 1.1), (1.35, 1.95)):
            b.box(x0 + 0.62, x0 + 0.64, -0.38, -0.335, z0, z1, "Chrome")
        start = x0 + 0.72
    b.box(start, L / 2, -0.29, 0.3, 0.1, 0.86, "CabinetCarcass")
    n = max(1, round((L / 2 - start) / 0.6))
    pw = (L / 2 - start) / n
    for i in range(n):
        a = start + i * pw
        b.box(a + 0.003, a + pw - 0.003, -0.31, -0.29, 0.103, 0.857, "Cabinet")
        b.box(a + 0.05, a + pw - 0.05, -0.33, -0.31, 0.8, 0.815, "Brass")
    b.box(start - 0.01, L / 2, -0.32, 0.3, 0.86, 0.9, "Counter")
    b.box(start, L / 2, 0.28, 0.3, 0.9, 1.5, "Splash")
    if sink is not None:
        b.box(sink - 0.38, sink + 0.38, -0.22, 0.17, 0.9, 0.903, "Steel")
        b.box(sink - 0.34, sink + 0.34, -0.19, 0.14, 0.903, 0.905, "PlasticDark")
        b.cyl(sink, 0.22, 0.9, 1.22, 0.02, "Chrome", n=10)
        b.boxr((sink, 0.12, 1.22), (0.025, 0.22, 0.025), "Chrome")
    if hob is not None:
        b.box(hob - 0.3, hob + 0.3, -0.24, 0.2, 0.9, 0.906, "BlackGlass")
        for dx in (-0.14, 0.14):
            for dy in (-0.1, 0.08):
                b.cyl(hob + dx, dy, 0.906, 0.907, 0.09, "PlasticDark", n=20)
        b.box(hob - 0.3, hob + 0.3, -0.315, -0.3, 0.15, 0.78, "BlackGlass")
        b.box(hob - 0.25, hob + 0.25, -0.34, -0.315, 0.72, 0.735, "Steel")
        b.box(hob - 0.3, hob + 0.3, 0.0, 0.3, 1.6, 1.7, "Steel")
        b.box(hob - 0.13, hob + 0.13, 0.1, 0.3, 1.7, H, "Steel")
    if upper:
        segs = [(start, L / 2)]
        for cut in [c for c in (hob, window) if c is not None]:
            hw = 0.38 if cut == hob else 0.7
            new = []
            for s0, s1 in segs:
                if cut - hw > s0:
                    new.append((s0, min(s1, cut - hw)))
                if cut + hw < s1:
                    new.append((max(s0, cut + hw), s1))
            segs = new
        for s0, s1 in segs:
            if s1 - s0 < 0.3:
                continue
            b.box(s0, s1, -0.04, 0.3, 1.55, 2.25, "CabinetCarcass")
            nn = max(1, round((s1 - s0) / 0.5))
            pw = (s1 - s0) / nn
            for i in range(nn):
                a = s0 + i * pw
                b.box(a + 0.003, a + pw - 0.003, -0.06, -0.04, 1.553, 2.247, "Cabinet")
    # a few things on the counter
    b.cyl(L / 2 - 0.25, 0.1, 0.9, 1.15, 0.06, "PotWhite")
    b.sph(L / 2 - 0.25, 0.1, 1.25, 0.11, "LeafLight", sz=1.1)
    b.box(L / 2 - 0.65, L / 2 - 0.4, 0.15, 0.26, 0.9, 1.25, "Walnut")


def toilet(b):
    b.cyl(0, -0.05, 0, 0.36, 0.13, "Ceramic", r_top=0.17, sy=1.3)
    b.cyl(0, -0.05, 0.36, 0.41, 0.19, "Ceramic", sy=1.25)
    b.box(-0.19, 0.19, 0.13, 0.3, 0.36, 0.8, "Ceramic")
    b.box(-0.05, 0.05, 0.18, 0.24, 0.8, 0.81, "Chrome")


def vanity(b, w=0.8, mirror=True):
    b.box(-w / 2, w / 2, -0.23, 0.23, 0.38, 0.82, "Oak")
    b.box(-w / 2 + 0.01, w / 2 - 0.01, -0.235, -0.23, 0.39, 0.81, "Walnut")
    b.box(-w / 2, w / 2, -0.24, 0.23, 0.82, 0.85, "Counter")
    b.cyl(0, -0.02, 0.85, 0.98, 0.19, "Ceramic", r_top=0.2, sy=0.8)
    b.cyl(0, -0.02, 0.975, 0.981, 0.16, "PlasticDark", sy=0.8)
    b.cyl(0, 0.17, 0.85, 1.12, 0.015, "Chrome", n=10)
    b.boxr((0, 0.1, 1.12), (0.02, 0.14, 0.02), "Chrome")
    if mirror:
        b.box(-w / 2 + 0.04, w / 2 - 0.04, 0.215, 0.235, 1.1, 1.85, "Mirror")
        b.box(-w / 2 + 0.03, w / 2 - 0.03, 0.225, 0.24, 1.09, 1.86, "Brass")


def bathtub(b, L=1.7, w=0.75):
    t = 0.07
    b.box(-L / 2, L / 2, -w / 2, w / 2, 0, 0.12, "Ceramic")
    b.box(-L / 2, L / 2, -w / 2, -w / 2 + t, 0.12, 0.58, "Ceramic")
    b.box(-L / 2, L / 2, w / 2 - t, w / 2, 0.12, 0.58, "Ceramic")
    b.box(-L / 2, -L / 2 + t, -w / 2, w / 2, 0.12, 0.58, "Ceramic")
    b.box(L / 2 - t, L / 2, -w / 2, w / 2, 0.12, 0.58, "Ceramic")
    b.cyl(L / 2 - 0.15, w / 2 - 0.02, 0.58, 0.85, 0.015, "Chrome", n=10)
    b.boxr((L / 2 - 0.15, w / 2 - 0.12, 0.85), (0.025, 0.2, 0.025), "Chrome")
    b.box(-L / 2 + 0.25, -L / 2 + 0.55, -w / 2 + 0.1, -w / 2 + 0.25, 0.58, 0.61, "Linen")


def shower(b, w=0.9, d=1.2, glass="front"):
    b.box(-w / 2, w / 2, -d / 2, d / 2, 0, 0.05, "Ceramic")
    b.box(-0.1, 0.1, -0.05, 0.05, 0.049, 0.052, "Chrome")
    if glass in ("front", "both"):
        b.box(-w / 2, w / 2 * 0.15, -d / 2, -d / 2 + 0.012, 0.05, 2.0, "Glass")
        b.box(-w / 2, w / 2 * 0.15, -d / 2 - 0.005, -d / 2 + 0.017, 1.97, 2.0, "Chrome")
    if glass in ("side", "both"):
        b.box(-w / 2, -w / 2 + 0.012, -d / 2, d / 2 * 0.3, 0.05, 2.0, "Glass")
    b.cyl(w / 2 - 0.15, d / 2 - 0.03, 0.9, 2.1, 0.012, "Chrome", n=10)
    b.boxr((w / 2 - 0.15, d / 2 - 0.15, 2.1), (0.02, 0.25, 0.02), "Chrome")
    b.cyl(w / 2 - 0.15, d / 2 - 0.27, 2.06, 2.09, 0.12, "Chrome")


def washer(b, x=0.0):
    with b.push(x, 0):
        b.box(-0.3, 0.3, -0.3, 0.3, 0, 0.85, "Appliance")
        b.box(-0.29, 0.29, -0.305, -0.3, 0.74, 0.83, "PlasticDark")
        b.cyl(-0.0, 0.42, -0.32, -0.3, 0.2, "Chrome", axis="y")
        b.cyl(-0.0, 0.42, -0.33, -0.31, 0.16, "BlackGlass", axis="y")


def utility_run(b, L=2.2):
    b.box(-L / 2, L / 2, -0.3, 0.3, 0.86, 0.9, "Counter")
    washer(b, -L / 2 + 0.32)
    washer(b, -L / 2 + 0.96)
    b.box(-L / 2 + 1.3, L / 2, -0.29, 0.3, 0.0, 0.86, "Joinery")
    b.box(L / 2 - 0.7, L / 2 - 0.2, -0.2, 0.15, 0.9, 0.905, "Steel")
    b.cyl(L / 2 - 0.45, 0.22, 0.9, 1.2, 0.02, "Chrome", n=10)
    b.box(-L / 2, L / 2, 0.0, 0.3, 1.55, 2.2, "Joinery")
    b.cyl(-L / 2 + 0.3, -0.1, 0.9, 1.18, 0.16, "Wicker", r_top=0.18)


def shelving(b, w=1.2, d=0.4, h=2.0, n=5):
    for sx in (-w / 2, w / 2 - 0.03):
        b.box(sx, sx + 0.03, -d / 2, d / 2, 0, h, "Oak")
    for i in range(n):
        z = 0.05 + i * (h - 0.1) / (n - 1)
        b.box(-w / 2, w / 2, -d / 2, d / 2, z, z + 0.025, "Oak")
        if i < n - 1:
            x = -w / 2 + 0.06
            k = 0
            while x < w / 2 - 0.3:
                bw = 0.22 + 0.08 * ((i + k) % 3)
                mat = ("Book1", "Book2", "Book3", "Wicker", "Canvas")[(i * 3 + k) % 5]
                b.box(x, min(x + bw, w / 2 - 0.05), -d / 2 + 0.04, d / 2 - 0.04, z + 0.025, z + 0.025 + 0.2 + 0.06 * (k % 2), mat)
                x += bw + 0.05
                k += 1


def treadmill(b):
    b.box(-0.4, 0.4, -0.9, 0.9, 0.04, 0.2, "PlasticDark")
    b.box(-0.3, 0.3, -0.85, 0.85, 0.2, 0.215, "Rubber")
    for s in (-1, 1):
        b.boxr((s * 0.36, 0.78, 0.7), (0.06, 0.08, 1.1), "PlasticDark", rot=(-10, 0, 0))
    b.boxr((0, 0.68, 1.27), (0.8, 0.3, 0.06), "PlasticDark", rot=(-35, 0, 0))
    b.boxr((0, 0.66, 1.29), (0.4, 0.2, 0.01), "Screen", rot=(-35, 0, 0))


def gym_bench(b):
    b.box(-0.15, 0.15, -0.6, 0.6, 0.38, 0.48, "Leather")
    for sy in (-0.45, 0.45):
        b.box(-0.2, 0.2, sy - 0.03, sy + 0.03, 0, 0.38, "Steel")


def dumbbell_rack(b, w=1.2):
    for sx in (-w / 2, w / 2 - 0.05):
        b.box(sx, sx + 0.05, -0.2, 0.2, 0, 0.85, "PlasticDark")
    for z in (0.3, 0.65):
        b.boxr((0, 0, z), (w, 0.4, 0.03), "PlasticDark", rot=(-12, 0, 0))
        for i in range(5):
            x = -w / 2 + 0.15 + i * (w - 0.3) / 4
            r = 0.05 + 0.012 * i
            b.cyl(-0.0, z + r + 0.02, x - 0.13, x - 0.07, r, "Rubber", axis="x", n=12)
            b.cyl(-0.0, z + r + 0.02, x + 0.07, x + 0.13, r, "Rubber", axis="x", n=12)
            b.cyl(-0.0, z + r + 0.02, x - 0.07, x + 0.07, 0.015, "Chrome", axis="x", n=8)


def plant(b, h=1.2, r=0.18, pot="Pot", leaf="Leaf"):
    b.cyl(0, 0, 0, r * 2.1, r, pot, r_top=r * 1.15)
    b.cyl(0, 0, r * 2.05, r * 2.1, r * 1.05, "Soil")
    b.cyl(0, 0, r * 2, h * 0.65, 0.02, "Bark", n=6)
    rnd = __import__("random").Random(int(h * 1000) + int(r * 100))
    for i in range(22):
        a = rnd.uniform(0, 6.283)
        d = rnd.uniform(0.0, 0.22) * h / 1.2
        z = h * rnd.uniform(0.5, 0.95)
        b.sph(math.cos(a) * d, math.sin(a) * d, z, h * rnd.uniform(0.07, 0.12),
              leaf if rnd.random() < 0.6 else "LeafLight", sx=1.0, sy=rnd.uniform(0.6, 1), sz=rnd.uniform(0.4, 0.7), n=10)


def olive_tree(b, h=2.8):
    b.cyl(0, 0, 0, 0.5, 0.35, "Stone", r_top=0.38)
    b.cyl(0, 0, 0.48, 0.5, 0.33, "Soil")
    b.cyl(0, 0, 0.5, h * 0.6, 0.06, "Bark", r_top=0.04, n=8)
    rnd = __import__("random").Random(int(h * 100))
    for k in range(3):  # a few branches
        a = k * 2.1 + 0.4
        b.cyl(math.cos(a) * 0.18, math.sin(a) * 0.18, h * 0.5, h * 0.72, 0.03, "Bark", r_top=0.015, n=6)
    for i in range(46):
        a = rnd.uniform(0, 6.283)
        d = rnd.uniform(0.0, 0.75)
        z = h * rnd.uniform(0.6, 0.95)
        b.sph(math.cos(a) * d, math.sin(a) * d, z, rnd.uniform(0.13, 0.22),
              "LeafLight" if rnd.random() < 0.55 else "Leaf", sy=rnd.uniform(0.6, 1), sz=rnd.uniform(0.45, 0.7), n=10)


def lounger(b):
    b.box(-0.33, 0.33, -0.9, 0.6, 0.18, 0.3, "Wicker")
    b.box(-0.3, 0.3, -0.88, 0.58, 0.3, 0.36, "Cushion")
    b.boxr((0, 0.85, 0.58), (0.66, 0.08, 0.7), "Wicker", rot=(-50, 0, 0))
    b.boxr((0, 0.78, 0.6), (0.6, 0.05, 0.64), "Cushion", rot=(-50, 0, 0))
    for sx in (-0.28, 0.28):
        for sy in (-0.85, 0.85):
            b.box(sx - 0.03, sx + 0.03, sy - 0.03, sy + 0.03, 0, 0.18, "Wicker")


def outdoor_table(b, r=0.55, chairs=4, parasol=True):
    b.cyl(0, 0, 0.72, 0.75, r, "Stone", n=32)
    b.cyl(0, 0, 0, 0.72, 0.04, "Frame", n=10)
    b.cyl(0, 0, 0, 0.03, 0.25, "Frame")
    for i in range(chairs):
        a = 360 * i / chairs
        x = math.sin(math.radians(a)) * (r + 0.25)
        y = -math.cos(math.radians(a)) * (r + 0.25)
        with b.push(x, y, a + 180):
            b.box(-0.24, 0.24, -0.22, 0.22, 0.4, 0.45, "Wicker")
            b.box(-0.22, 0.22, -0.2, 0.2, 0.45, 0.5, "Cushion")
            b.boxr((0, 0.21, 0.68), (0.48, 0.05, 0.4), "Wicker", rot=(-8, 0, 0))
            for sx in (-0.2, 0.2):
                for sy in (-0.18, 0.18):
                    b.cyl(sx, sy, 0, 0.4, 0.015, "Frame", n=6)
    if parasol:
        b.cyl(0, 0, 0.75, 2.4, 0.02, "Walnut", n=8)
        b.cyl(0, 0, 2.05, 2.45, 1.3, "Canvas", r_top=0.03, n=16, caps=False)
        b.cyl(0, 0, 2.03, 2.05, 1.3, "Canvas", n=16)


def bbq(b):
    b.sph(0, 0, 0.8, 0.3, "Rubber", sz=0.8)
    for i in range(3):
        a = i * 2.09
        b.cyl(math.cos(a) * 0.2, math.sin(a) * 0.2, 0, 0.7, 0.015, "Frame", n=6)


def stairs(b, steps=6, w=0.7, run=0.24, rise=0.18, back_steps=6):
    for i in range(steps):
        b.box(-w, 0, -i * run - run, -i * run, 0, rise * (i + 1), "Oak")
    land_y = -steps * run
    b.box(-w, w, land_y - 0.4, land_y, 0, rise * steps + 0.02, "Oak")
    for i in range(back_steps):
        y = land_y + i * run
        b.box(0.02, w, y, y + run, 0, rise * (steps + i + 1), "Oak")
    b.box(-0.03, 0.03, land_y, 0, 0, rise * steps + 0.9, "Joinery")
    b.boxr((-w + 0.03, -steps * run / 2, rise * steps / 2 + 0.9), (0.04, steps * run * 1.25, 0.04), "Walnut",
           rot=(math.degrees(math.atan(rise / run)), 0, 0))


def rug(b, w, d, mat="Rug"):
    b.box(-w / 2, w / 2, -d / 2, d / 2, 0.0, 0.012, mat)
    b.box(-w / 2 + 0.08, w / 2 - 0.08, -d / 2 + 0.08, d / 2 - 0.08, 0.012, 0.014,
          "RugBlue" if mat == "Rug" else "Rug")


def art(b, w=0.8, h=0.6, z=1.5, mat="Art1"):
    b.box(-w / 2 - 0.03, w / 2 + 0.03, -0.015, 0.015, z - h / 2 - 0.03, z + h / 2 + 0.03, "Walnut")
    b.box(-w / 2, w / 2, -0.02, -0.015, z - h / 2, z + h / 2, "Canvas")
    b.box(-w / 3, w / 6, -0.025, -0.02, z - h / 4, z + h / 3, mat)
    b.box(w / 6, w / 2.6, -0.025, -0.02, z - h / 3, z, "Art3")


def desk(b, w=1.1):
    b.box(-w / 2, w / 2, -0.3, 0.3, 0.72, 0.75, "Oak")
    for sx in (-w / 2 + 0.04, w / 2 - 0.04):
        b.box(sx - 0.02, sx + 0.02, -0.28, 0.28, 0, 0.72, "Walnut")
    b.box(-0.25, 0.15, 0.0, 0.25, 0.75, 0.77, "PlasticDark")
    b.boxr((-0.05, 0.12, 0.88), (0.36, 0.01, 0.24), "Screen", rot=(-75, 0, 0))
    b.cyl(0.4, 0.15, 0.75, 1.15, 0.01, "Brass", n=6)
    b.cyl(0.4, 0.05, 1.08, 1.2, 0.08, "LampShade", r_top=0.06)
    chair(b, 0, -0.55, 180)


def console(b, w=1.0):
    b.box(-w / 2, w / 2, -0.15, 0.15, 0.78, 0.82, "Walnut")
    for sx in (-w / 2 + 0.03, w / 2 - 0.03):
        b.box(sx - 0.015, sx + 0.015, -0.13, 0.13, 0, 0.78, "Brass")
    b.cyl(-0.3, 0, 0.82, 1.1, 0.07, "PotWhite", r_top=0.05)
    b.sph(-0.3, 0, 1.2, 0.12, "LeafLight", sz=1.3)
    b.box(0.05, 0.35, -0.08, 0.08, 0.82, 0.86, "Book3")


def lift_car(b):
    b.box(-0.6, 0.6, -0.6, 0.6, 0, H - 0.05, "Steel")


def doormat(b):
    b.box(-0.35, 0.35, -0.22, 0.22, 0, 0.015, "Wicker")


def front_steps(b):
    # limestone threshold and a pair of potted plants either side of the door
    b.box(0.0, 0.9, -0.6, 0.6, -0.01, 0.03, "Stone")
    for sy in (-0.85, 0.85):
        b.cyl(0.55, sy, 0, 0.55, 0.2, "Pot", r_top=0.24)
        b.sph(0.55, sy, 0.8, 0.3, "Leaf", sz=1.15)


def wall_mirror(b, w=1.2, h=1.8):
    b.box(-w / 2, w / 2, -0.02, 0.0, 0.3, 0.3 + h, "Mirror")
    b.box(-w / 2 - 0.02, w / 2 + 0.02, -0.0, 0.01, 0.28, 0.32 + h, "PlasticDark")


def yoga_mat(b):
    b.box(-0.3, 0.3, -0.9, 0.9, 0, 0.006, "Accent")


def planter_box(b, w=1.2, d=0.4):
    b.box(-w / 2, w / 2, -d / 2, d / 2, 0, 0.45, "Stone")
    b.box(-w / 2 + 0.04, w / 2 - 0.04, -d / 2 + 0.04, d / 2 - 0.04, 0.44, 0.45, "Soil")
    for i in range(4):
        x = -w / 2 + 0.15 + i * (w - 0.3) / 3
        b.sph(x, 0, 0.6, 0.18, "Leaf" if i % 2 else "LeafLight", sz=1.2)


def towel_rail(b):
    b.box(-0.25, 0.25, -0.04, 0.0, 0.9, 1.6, "Chrome")
    b.box(-0.22, 0.22, -0.07, -0.04, 1.05, 1.45, "Linen")


# Furniture placements: (id, builder, kwargs, plan X m, plan Y m (Blender), rot deg, room)
# rot: 0 = item faces -Y (towards the bottom of the plan), 90 = faces +X (street).
def place_furniture():
    cfur = coll("Furniture")
    items = []

    def add(name, fn, x, y, rot=0, room=None, bevel=0.006, **kw):
        b = Builder()
        fn(b, **kw)
        ob = b.build("furn_" + name, loc=(x, y, 0), rotz=rot, bevel=bevel, collection=cfur)
        items.append({"name": ob.name, "room": room})
        return ob

    # Gym  X -9.42..-4.88 / Y 0.75..3.9
    add("treadmill", treadmill, -8.55, 2.15, 180, "gym")
    add("bench", gym_bench, -6.7, 2.05, 90, "gym")
    add("dumbbells", dumbbell_rack, -5.6, 1.03, 180, "gym")
    add("gymmirror", wall_mirror, -4.96, 1.5, -90, "gym", w=1.1)
    add("yogamat", yoga_mat, -7.4, 1.25, 90, "gym")
    add("gymplant", plant, -9.05, 1.05, 0, "gym", h=1.4)

    # Utility X -4.88..0.18 / Y 1.72..3.3
    add("utility", utility_run, -3.4, 2.02, 180, "utility")
    add("utilshelf", shelving, -1.0, 2.75, 180, "utility", w=1.0, d=0.35, h=2.0)

    # Ensuite X -4.88..-1.85 / Y 0.12..1.72
    add("ens_shower", shower, -2.33, 0.92, 0, "ens", w=0.9, d=1.5, glass="side")
    add("ens_wc", toilet, -3.25, 1.36, 0, "ens")
    add("ens_vanity", vanity, -4.25, 1.4, 0, "ens")

    # Bathroom 1 X -1.85..0.18
    add("bath1_tub", bathtub, -0.83, 1.27, 0, "bath1")
    add("bath1_wc", toilet, -0.2, 0.55, -90, "bath1")
    add("bath1_vanity", vanity, -1.55, 0.6, 90, "bath1", w=0.7)

    # Box room X 0.18..2.65 / Y 0.12..1.58
    add("box_shelf", shelving, 1.0, 1.3, 0, "box", w=1.4)
    add("box_shelf2", shelving, 0.42, 0.75, 90, "box", w=0.9, d=0.35, h=1.8, n=4)

    # Lift
    add("lift_car", lift_car, bx(1168), by(554), 0, "lift", bevel=0.01)
    # Entrance + stairs
    add("entry_mat", doormat, bx(1238), by(585), 0, "entry")
    add("stairs", stairs, bx(1309), by(512), 0, "stairs", bevel=0.004, steps=4, back_steps=4, run=0.25)
    # WC X 6.47..8.3 / Y 0.12..1.58
    add("wc_wc", toilet, 7.65, 0.5, 180, "wc")
    add("wc_vanity", vanity, 8.0, 1.05, -90, "wc", w=0.55)

    # Kitchen / living A  X 8.3..13.75 / Y 0.12..2.62
    add("kitA_run", kitchen_run, 10.3, 2.17, 0, "kitA", L=2.6, fridge=True, sink=0.5, hob=-0.25)
    add("kitA_dining", dining, 10.0, 0.95, 0, "kitA", w=1.2, d=0.8, chairs=4)
    add("kitA_sofa", sofa, 12.6, 0.65, 180, "kitA", w=2.0, d=0.9)
    add("kitA_tv", tv_unit, 12.7, 2.25, 0, "kitA", w=1.4)
    add("kitA_coffee", coffee_table, 12.6, 1.45, 0, "kitA", w=0.9, d=0.5)
    add("kitA_rug", rug, 12.6, 1.35, 0, "kitA", bevel=0, w=2.2, d=1.5)

    # Bedroom 1  X -6.75..-3.38 / Y -3.17..0.75
    add("bed1_bed", bed, -5.3, -1.85, 180, "bed1", w=1.5)
    add("bed1_ns1", nightstand, -6.32, -2.62, 180, "bed1")
    add("bed1_ns2", nightstand, -4.28, -2.62, 180, "bed1")
    add("bed1_wardrobe", wardrobe, -5.81, 0.37, 0, "bed1", w=1.75)
    add("bed1_desk", desk, -3.75, -1.6, -90, "bed1")
    add("bed1_rug", rug, -5.3, -1.6, 0, "bed1", bevel=0, w=2.2, d=1.6, mat="RugBlue")

    # Bathroom 2  X -3.38..-1.33 / Y -3.25..-0.85
    add("bath2_shower", shower, -1.83, -2.5, 180, "bath2", w=0.9, d=1.0, glass="front")
    add("bath2_wc", toilet, -3.0, -2.05, 90, "bath2")
    add("bath2_vanity", vanity, -1.65, -1.35, -90, "bath2", w=0.7)
    add("bath2_towel", towel_rail, -3.3, -1.25, 90, "bath2")

    # Bedroom 2  X -1.33..2.58 / Y -4.0..-0.85
    add("bed2_bed", bed, -0.15, -2.55, 90, "bed2")
    add("bed2_ns1", nightstand, -1.05, -1.5, 90, "bed2")
    add("bed2_ns2", nightstand, -1.05, -3.6, 90, "bed2")
    add("bed2_wardrobe", wardrobe, 0.35, -1.21, 0, "bed2", w=2.1)
    add("bed2_chair", sofa, 2.05, -3.3, -90, "bed2", w=0.9, d=0.8, mat="Upholstery")
    add("bed2_rug", rug, 0.45, -2.55, 90, "bed2", bevel=0, w=2.3, d=1.7)
    add("bed2_art", art, -1.25, -2.55, 90, "bed2", w=1.1, h=0.7, z=1.7, mat="Art1")

    # Corridor / landing / courtyard
    add("corr_console", console, 2.83, -1.7, 90, "corr")
    add("corr_art", art, 2.7, -1.7, 90, "corr", w=0.9, h=0.6, z=1.55, mat="Art2")
    add("corr_plant", plant, 6.75, -1.15, 0, "corr", h=1.5)
    add("corr_rug", rug, 10.5, -0.48, 0, "corr", bevel=0, w=4.0, d=0.7, mat="RugBlue")
    add("court_tree", olive_tree, 3.3, -3.4, 0, "court")
    add("court_table", outdoor_table, 5.6, -3.3, 0, "court", r=0.35, chairs=2, parasol=False)
    add("court_planter", planter_box, 6.6, -3.65, 0, "court", w=0.8, d=0.35)

    # Kitchen / living / dining B  X 7.05..13.75 / Y -4.0..-1.02
    add("kitB_run", kitchen_run, 8.65, -3.53, 180, "kitB", L=2.9, fridge=True, sink=-0.4, hob=0.55)
    add("kitB_dining", dining, 10.75, -1.95, 0, "kitB", w=1.4, d=0.85, chairs=4)
    add("kitB_sofa", sofa, 12.4, -3.37, 180, "kitB", w=2.2)
    add("kitB_coffee", coffee_table, 12.4, -2.55, 0, "kitB", w=1.0, d=0.5)
    add("kitB_tv", tv_unit, 12.45, -1.3, 0, "kitB", w=1.6)
    add("kitB_rug", rug, 12.4, -2.6, 0, "kitB", bevel=0, w=2.4, d=1.6)
    add("kitB_plant", plant, 7.45, -2.3, 0, "kitB", h=1.6, pot="PotWhite")

    # Outdoor: yard, patio, planted yard, front steps
    add("yard_lounger1", lounger, -13.2, -0.2, 0, "yard")
    add("yard_lounger2", lounger, -12.3, -0.25, 0, "yard")
    add("yard_tree", olive_tree, -13.3, 2.6, 0, "yard", h=3.2)
    add("yard_bbq", bbq, -11.9, 3.0, 0, "yard")
    add("yard_planter", planter_box, -12.6, -2.6, 0, "yard", w=1.6)
    add("patio_table", outdoor_table, -9.2, -0.6, 0, "patio")
    add("patio_plant1", plant, -7.15, -1.95, 0, "patio", h=1.2)
    add("planted_tree", olive_tree, -10.2, 2.4, 0, "planted", h=2.6)
    add("planted_plant", plant, -10.4, 1.25, 0, "planted", h=0.9, pot="PotWhite")
    add("front_steps", front_steps, bx(1790) + 0.15, by(633), 0, None, bevel=0.004)
    return items


# ------------------------------------------------------------ lights/cams
def build_lights(rooms):
    cl = coll("Lights")
    # sun
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = 3.2
    sun.angle = math.radians(1.2)
    sun.color = (1.0, 0.96, 0.9)
    so = bpy.data.objects.new("Sun", sun)
    so.rotation_euler = Euler((math.radians(42), math.radians(0), math.radians(128)))
    cl.objects.link(so)
    # ceiling area lights per indoor room (used for interior renders)
    for r in rooms:
        if not r["indoor"] or r["id"] in ("lift",):
            continue
        xs = [p[0] for p in r["poly"]]
        ys = [p[1] for p in r["poly"]]
        sx = max(0.4, (max(xs) - min(xs)) * 0.45)
        sy = max(0.4, (max(ys) - min(ys)) * 0.45)
        L = bpy.data.lights.new("Ceil_" + r["id"], "AREA")
        L.shape = "RECTANGLE"
        L.size, L.size_y = sx, sy
        L.energy = max(8.0, r["area"] * 3.0)
        L.color = (1.0, 0.91, 0.82)
        o = bpy.data.objects.new("Ceil_" + r["id"], L)
        o.location = (r["c"][0], r["c"][1], H - 0.02)
        cl.objects.link(o)
    # recessed downlights: soft spots pointing at the floor
    for k, (x, y) in enumerate(DOWNLIGHT_POS):
        L = bpy.data.lights.new(f"Down_{k:02d}", "SPOT")
        L.energy = 55.0
        L.spot_size = math.radians(115)
        L.spot_blend = 0.75
        L.shadow_soft_size = 0.04
        L.color = (1.0, 0.88, 0.74)
        o = bpy.data.objects.new(L.name, L)
        o.location = (x, y, H - 0.03)
        cl.objects.link(o)
    # lamps / pendants: small point lights at emissive bulbs
    for ob in bpy.data.objects:
        if not ob.name.startswith("furn_"):
            continue
        if any(k in ob.name for k in ("_ns", "dining", "desk")):
            pts = []
            me = ob.data
            bulb_idx = [i for i, m in enumerate(me.materials) if m and m.name == "Bulb"]
            if not bulb_idx:
                continue
            vs = [ob.matrix_world @ v.co for v in me.vertices]
            for poly in me.polygons:
                if poly.material_index in bulb_idx:
                    pts.append(sum((vs[i] for i in poly.vertices), Vector()) / len(poly.vertices))
            if not pts:
                continue
            # cluster bulbs (each bulb sphere -> one light)
            clusters = []
            for p in pts:
                for c in clusters:
                    if (c[0] / c[1] - p).length < 0.15:
                        c[0] += p
                        c[1] += 1
                        break
                else:
                    clusters.append([p.copy(), 1])
            for k, (s, n) in enumerate(clusters):
                L = bpy.data.lights.new(f"Lamp_{ob.name}_{k}", "POINT")
                L.energy = 25.0
                L.shadow_soft_size = 0.05
                L.color = (1.0, 0.8, 0.6)
                o = bpy.data.objects.new(L.name, L)
                o.location = s / n
                cl.objects.link(o)


def look_at_cam(name, pos, target, lens=24, coll_=None):
    cam = bpy.data.cameras.new(name)
    cam.lens = lens
    cam.clip_start = 0.05
    cam.clip_end = 200
    o = bpy.data.objects.new(name, cam)
    o.location = pos
    d = Vector(target) - Vector(pos)
    o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    (coll_ or bpy.context.scene.collection).objects.link(o)
    return o


# Views rendered in Cycles. pos/target in Blender metres.
VIEWS = [
    {"id": "aerial", "title": "The whole floor from above", "pos": (19.0, -15.5, 15.5), "target": (1.2, 0.2, 0.0),
     "lens": 30, "interior": False, "res": (1600, 900)},
    {"id": "kitchen-dining", "title": "Kitchen, living and dining", "pos": (13.45, -2.25, 1.5), "target": (8.6, -2.75, 0.95),
     "lens": 18, "interior": True},
    {"id": "kitchen-living", "title": "Kitchen and living, apartment side", "pos": (13.45, 1.5, 1.55), "target": (9.0, 1.6, 0.95),
     "lens": 18, "interior": True},
    {"id": "bedroom", "title": "Bedroom 2", "pos": (2.25, -1.75, 1.55), "target": (-0.8, -2.9, 0.75),
     "lens": 18, "interior": True},
    {"id": "ensuite", "title": "Ensuite", "pos": (-2.95, 0.28, 1.65), "target": (-4.6, 1.5, 0.85),
     "lens": 16, "interior": True},
    {"id": "corridor", "title": "Corridor from the front door", "pos": (12.4, -0.5, 1.6), "target": (-2.0, -0.5, 1.25),
     "lens": 22, "interior": True},
    {"id": "garden", "title": "Garden yard and patio", "pos": (-13.9, -2.85, 1.7), "target": (-7.5, 1.0, 0.9),
     "lens": 20, "interior": False},
]


def build_cameras():
    cc = coll("Cameras")
    for v in VIEWS:
        look_at_cam("cam_" + v["id"], v["pos"], v["target"], v["lens"], cc)


# ---------------------------------------------------------------- world
def build_world():
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    try:
        w.use_nodes = True
    except Exception:
        pass
    nt = w.node_tree
    bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
    sky = nt.nodes.new("ShaderNodeTexSky")
    for t in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try:
            sky.sky_type = t
            break
        except Exception:
            continue
    for attr, val in (("sun_disc", False), ("sun_elevation", math.radians(48)),
                      ("sun_rotation", math.radians(128 + 90)), ("altitude", 50.0)):
        try:
            setattr(sky, attr, val)
        except Exception:
            pass
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.35


def to_gltf(x, y, z=0.0):
    # Blender (x, y, z) -> glTF (x, z, -y)
    return [round(x, 3), round(z, 3), round(-y, 3)]


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    build_materials()
    rooms = build_floors()
    build_walls()
    items = place_furniture()
    build_lights(rooms)
    build_cameras()
    build_world()

    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    blend = os.path.join(ROOT, "flat.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    # ---- glTF for the browser (no lights/cameras/ceiling lights) ----
    for ob in bpy.data.objects:
        ob.select_set(ob.type == "MESH")
    glb = os.path.join(WEB, "flat.glb")
    kw = dict(filepath=glb, export_format="GLB", use_selection=True, export_apply=True,
              export_yup=True, export_lights=False, export_cameras=False)
    try:
        bpy.ops.export_scene.gltf(export_image_format="JPEG", export_jpeg_quality=86, **kw)
    except TypeError:
        bpy.ops.export_scene.gltf(**kw)

    # ---- scene.json for the viewer ----
    def g2(p):  # Blender XY -> glTF XZ
        return [round(p[0], 3), round(-p[1], 3)]

    data = {
        "ceiling": H,
        "rooms": [{**r, "c": g2(r["c"]), "poly": [g2(p) for p in r["poly"]]} for r in rooms],
        "furniture": items,
        "colliders": [[round(c[0], 3), round(-c[1], 3), round(c[2], 3), round(-c[3], 3), round(c[4], 3)]
                      for c in COLLIDERS],
        "views": [{"id": v["id"], "title": v["title"], "pos": to_gltf(*v["pos"]),
                   "target": to_gltf(*v["target"]), "lens": v["lens"], "interior": v["interior"]}
                  for v in VIEWS],
        "finishes": {k: v for k, v in TILE_METERS.items()},
    }
    with open(os.path.join(WEB, "scene.json"), "w") as f:
        json.dump(data, f, indent=1)
    print("objects:", len(bpy.data.objects), "furniture:", len(items), "colliders:", len(COLLIDERS))


if __name__ == "__main__":
    main()
