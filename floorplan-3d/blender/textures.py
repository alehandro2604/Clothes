"""Procedural, seamlessly tiling floor/material textures for the flat.

Run with any Python that has numpy + Pillow:
    python textures.py ../web/tex

Every texture tiles in both directions. TILE_METERS says how many metres
one copy of the image covers; build_scene.py uses it to scale the UVs.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024

TILE_METERS = {
    "oak": 2.0,
    "walnut": 2.0,
    "maltese": 0.8,
    "terrazzo": 1.5,
    "porcelain": 1.2,
    "marble": 2.0,
    "concrete": 2.0,
    "limestone": 3.0,
    "terracotta": 1.2,
    "pebble": 1.0,
    "woodlight": 1.0,
    "wooddark": 1.0,
}
FABRIC_NORMAL_TILE = 0.12  # metres per repeat of fabric_n.png


def hexrgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)


def tnoise(rng, cells, size=SIZE):
    """Tileable smooth value noise in [0,1]."""
    g = rng.random((cells, cells)).astype(np.float32)
    big = np.tile(g, (3, 3))
    im = Image.fromarray((big * 255).astype(np.uint8)).resize(
        (size * 3, size * 3), Image.BICUBIC)
    a = np.asarray(im, dtype=np.float32)[size:2 * size, size:2 * size] / 255.0
    return a


def fbm(rng, base=4, octaves=5, size=SIZE):
    acc = np.zeros((size, size), np.float32)
    amp, tot, cells = 1.0, 0.0, base
    for _ in range(octaves):
        acc += amp * tnoise(rng, cells, size)
        tot += amp
        amp *= 0.5
        cells *= 2
    return acc / tot


def save(arr, path, q=90):
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(path, quality=q)


# ---------------------------------------------------------------- wood planks
def planks(rng, palette, rows=10, meters=2.0, gap_dark=0.45):
    S = SIZE
    img = np.zeros((S, S, 3), np.float32)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    n1 = fbm(rng, 8, 4)
    n2 = fbm(rng, 2, 3)
    row_h = S / rows
    for r in range(rows):
        y0, y1 = int(round(r * row_h)), int(round((r + 1) * row_h))
        # plank cut positions along x, wrapping so the row tiles
        cuts, x = [], rng.uniform(0, S)
        start = x
        while True:
            cuts.append(x % S)
            x += rng.uniform(0.35, 0.8) * S
            if x - start >= S - 0.2 * S:
                break
        cuts = sorted(cuts)
        seg_bounds = cuts + [cuts[0] + S]
        for i in range(len(cuts)):
            a, b = seg_bounds[i], seg_bounds[i + 1]
            col = palette[rng.integers(len(palette))] * rng.uniform(0.9, 1.08)
            freq = rng.uniform(3.5, 7.0)
            ph = rng.uniform(0, 6.28)
            k = rng.integers(1, 3)
            xs = np.arange(int(a), int(b)) % S
            band = slice(y0, y1)
            sub_y = yy[band][:, xs]
            sub_x = xx[band][:, xs]
            wav = (sub_y + 9 * np.sin(2 * np.pi * k * sub_x / S + ph)
                   + 14 * n1[band][:, xs])
            grain = 0.5 + 0.5 * np.sin(wav * (2 * np.pi / freq))
            grain = grain ** 6
            shade = 1.0 - 0.13 * grain - 0.10 * (n2[band][:, xs] - 0.5)
            img[band, xs] = col[None, None, :] * shade[..., None]
            # plank end joint
            img[y0:y1, int(a) % S] *= gap_dark
        img[y0:y0 + 2, :] *= gap_dark
    img = np.asarray(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
                     .filter(ImageFilter.GaussianBlur(0.6)), np.float32)
    return img


# ------------------------------------------------------- Maltese cement tile
def maltese_tile(rng, T=256):
    cream = (233, 222, 200)
    red = (166, 70, 48)
    blue = (54, 84, 112)
    ochre = (196, 148, 62)
    char = (45, 45, 45)
    im = Image.new("RGB", (T * 2, T * 2), cream)  # draw at 2x then shrink
    d = ImageDraw.Draw(im)
    s = T * 2
    c = s / 2
    # quarter motifs in corners -> full rosettes where 4 tiles meet
    for cx, cy in [(0, 0), (s, 0), (0, s), (s, s)]:
        d.ellipse([cx - s * 0.46, cy - s * 0.46, cx + s * 0.46, cy + s * 0.46], fill=red)
        d.ellipse([cx - s * 0.38, cy - s * 0.38, cx + s * 0.38, cy + s * 0.38], fill=cream)
        d.ellipse([cx - s * 0.31, cy - s * 0.31, cx + s * 0.31, cy + s * 0.31], fill=blue)
        for k in range(8):
            ang = k * math.pi / 4
            px, py = cx + math.cos(ang) * s * 0.2, cy + math.sin(ang) * s * 0.2
            d.ellipse([px - s * 0.06, py - s * 0.06, px + s * 0.06, py + s * 0.06], fill=ochre)
        d.ellipse([cx - s * 0.1, cy - s * 0.1, cx + s * 0.1, cy + s * 0.1], fill=cream)
    # centre diamond and four-petal flower
    r = s * 0.3
    d.polygon([(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=ochre)
    r2 = s * 0.23
    d.polygon([(c, c - r2), (c + r2, c), (c, c + r2), (c - r2, c)], fill=cream)
    for ang in (0, math.pi / 2, math.pi, 1.5 * math.pi):
        px, py = c + math.cos(ang) * s * 0.1, c + math.sin(ang) * s * 0.1
        d.ellipse([px - s * 0.075, py - s * 0.075, px + s * 0.075, py + s * 0.075], fill=red)
    d.ellipse([c - s * 0.05, c - s * 0.05, c + s * 0.05, c + s * 0.05], fill=blue)
    # thin border line
    d.rectangle([s * 0.03, s * 0.03, s * 0.97, s * 0.97], outline=char, width=3)
    im = im.resize((T, T), Image.LANCZOS)
    return np.asarray(im, np.float32)


def maltese(rng):
    T = SIZE // 4
    base = maltese_tile(rng, T)
    img = np.zeros((SIZE, SIZE, 3), np.float32)
    for i in range(4):
        for j in range(4):
            tile = base * rng.uniform(0.93, 1.04)
            img[i * T:(i + 1) * T, j * T:(j + 1) * T] = tile
    n = fbm(rng, 16, 4)
    img *= (0.94 + 0.1 * n)[..., None]
    for k in range(5):  # grout
        p = (k * T) % SIZE
        img[max(p - 2, 0):p + 2, :] = (176, 168, 152)
        img[:, max(p - 2, 0):p + 2] = (176, 168, 152)
    return img


# ------------------------------------------------------------- terrazzo
def terrazzo(rng):
    base = hexrgb("#E6E0D4")
    n = fbm(rng, 6, 5)
    img = np.ones((SIZE, SIZE, 3), np.float32) * base * (0.96 + 0.06 * n)[..., None]
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im)
    chips = ["#B65F3F", "#8C8C88", "#2F2F2F", "#F5F2EC", "#C9A46A", "#6E8070", "#D7B8A0"]
    for _ in range(2600):
        x, y = rng.uniform(0, SIZE, 2)
        rad = rng.choice([2, 3, 4, 6, 9, 14], p=[0.3, 0.25, 0.2, 0.13, 0.08, 0.04])
        col = chips[rng.integers(len(chips))]
        npts = rng.integers(4, 7)
        ang0 = rng.uniform(0, 6.28)
        pts = [(math.cos(ang0 + k * 6.28 / npts) * rad * rng.uniform(0.6, 1.2),
                math.sin(ang0 + k * 6.28 / npts) * rad * rng.uniform(0.6, 1.2)) for k in range(npts)]
        for ox in (-SIZE, 0, SIZE):
            for oy in (-SIZE, 0, SIZE):
                if -20 < x + ox < SIZE + 20 and -20 < y + oy < SIZE + 20:
                    d.polygon([(x + ox + a, y + oy + b) for a, b in pts], fill=col)
    return np.asarray(im, np.float32)


# ------------------------------------------------------------- marble
def marble(rng):
    n = fbm(rng, 3, 6)
    n2 = fbm(rng, 5, 5)
    xx = np.mgrid[0:SIZE, 0:SIZE][1].astype(np.float32)
    v = np.abs(np.sin(2 * np.pi * (xx / SIZE * 2 + n * 3.5)))
    veins = np.clip(1 - v, 0, 1) ** 9
    v2 = np.abs(np.sin(2 * np.pi * (xx / SIZE * 3 + n2 * 5)))
    veins2 = np.clip(1 - v2, 0, 1) ** 20
    base = hexrgb("#F1EFEB")
    vein = hexrgb("#8E8D8A")
    img = base * (0.97 + 0.04 * n2)[..., None]
    img = img * (1 - 0.55 * veins[..., None]) + vein * 0.55 * veins[..., None]
    img = img * (1 - 0.35 * veins2[..., None]) + vein * 0.35 * veins2[..., None]
    return img


# ------------------------------------------------------------- concrete
def concrete(rng):
    n = fbm(rng, 4, 7)
    sp = rng.random((SIZE, SIZE)) > 0.996
    base = hexrgb("#A9A7A2")
    img = base * (0.86 + 0.24 * n)[..., None]
    img[sp] *= 0.75
    return img


# ------------------------------------------------------------- porcelain
def porcelain(rng):
    tiles = 2
    T = SIZE // tiles
    n = fbm(rng, 6, 5)
    base = hexrgb("#DAD6CF")
    img = base * (0.97 + 0.05 * n)[..., None]
    for i in range(tiles):
        for j in range(tiles):
            img[i * T:(i + 1) * T, j * T:(j + 1) * T] *= rng.uniform(0.975, 1.02)
    g = hexrgb("#B9B3AA")
    for k in range(tiles + 1):
        p = (k * T) % SIZE
        img[max(p - 2, 0):p + 2, :] = g
        img[:, max(p - 2, 0):p + 2] = g
    return img


# --------------------------------------------------- limestone paving slabs
def limestone(rng):
    base = hexrgb("#D6C197")
    n = fbm(rng, 8, 5)
    img = np.zeros((SIZE, SIZE, 3), np.float32)
    rows = 5
    rh = SIZE / rows
    joint = hexrgb("#A99670")
    for r in range(rows):
        y0, y1 = int(r * rh), int((r + 1) * rh)
        x = rng.uniform(0, SIZE)
        start = x
        cuts = []
        while x - start < SIZE - 120:
            cuts.append(x % SIZE)
            x += rng.uniform(160, 360)
        cuts = sorted(cuts)
        bounds = cuts + [cuts[0] + SIZE]
        for i in range(len(cuts)):
            xs = np.arange(int(bounds[i]), int(bounds[i + 1])) % SIZE
            img[y0:y1, xs] = base * rng.uniform(0.9, 1.06)
            img[y0:y1, int(bounds[i]) % SIZE] = joint
            img[y0:y1, (int(bounds[i]) + 1) % SIZE] = joint
        img[y0:y0 + 3, :] = joint
    img *= (0.88 + 0.18 * n)[..., None]
    pits = rng.random((SIZE, SIZE)) > 0.997
    img[pits] *= 0.8
    return img


# ------------------------------------------------------------- terracotta
def terracotta(rng):
    tiles = 4
    T = SIZE // tiles
    n = fbm(rng, 8, 5)
    img = np.zeros((SIZE, SIZE, 3), np.float32)
    for i in range(tiles):
        for j in range(tiles):
            img[i * T:(i + 1) * T, j * T:(j + 1) * T] = hexrgb("#B9693F") * rng.uniform(0.85, 1.08)
    img *= (0.88 + 0.2 * n)[..., None]
    g = hexrgb("#CFC3AE")
    for k in range(tiles + 1):
        p = (k * T) % SIZE
        img[max(p - 3, 0):p + 3, :] = g
        img[:, max(p - 3, 0):p + 3] = g
    return img


# ------------------------------------------------------------- pebbles
def pebble(rng):
    img = np.ones((SIZE, SIZE, 3), np.float32) * hexrgb("#7D7569")
    im = Image.fromarray(img.astype(np.uint8))
    d = ImageDraw.Draw(im)
    cols = ["#D9D2C3", "#BDB4A3", "#E8E2D6", "#A39C8E", "#CFC6B4", "#8F887B"]
    for _ in range(5200):
        x, y = rng.uniform(0, SIZE, 2)
        a, b = rng.uniform(5, 14), rng.uniform(4, 10)
        col = cols[rng.integers(len(cols))]
        for ox in (-SIZE, 0, SIZE):
            for oy in (-SIZE, 0, SIZE):
                if -20 < x + ox < SIZE + 20 and -20 < y + oy < SIZE + 20:
                    d.ellipse([x + ox - a, y + oy - b, x + ox + a, y + oy + b], fill=col,
                              outline="#5E574D")
    return np.asarray(im, np.float32)


# ------------------------------------------------- continuous wood grain
def woodgrain(rng, base, dark):
    S = SIZE
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    n = fbm(rng, 3, 5)
    n2 = fbm(rng, 16, 3)
    # growth rings: stretched along x, wobbling with noise; x-periodic so it tiles
    rings = np.sin(2 * np.pi * (yy / S * 16 + 0.55 * n + 0.04 * np.sin(2 * np.pi * xx / S * 2)))
    rings = (0.5 + 0.5 * rings) ** 7
    fine = (0.5 + 0.5 * np.sin(2 * np.pi * (yy / S * 70 + 4 * n2))) ** 4
    base, dark = hexrgb(base), hexrgb(dark)
    t = np.clip(0.4 * rings + 0.22 * fine + 0.2 * (n - 0.5), 0, 1)[..., None]
    return base * (1 - t) + dark * t


# ------------------------------------------------- fabric weave normal map
def fabric_normal(rng):
    S = 512
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    k = 2 * np.pi * 48 / S  # 48 threads per repeat
    warp = np.abs(np.sin(xx * k / 2))
    weft = np.abs(np.sin(yy * k / 2))
    over = (np.floor(xx * 48 / S) + np.floor(yy * 48 / S)) % 2
    h = np.where(over > 0, warp * 0.6 + weft * 0.4, weft * 0.6 + warp * 0.4)
    h += 0.35 * tnoise(rng, 24, S) + 0.15 * tnoise(rng, 96, S)
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 1.6
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 1.6
    nz = np.ones_like(h)
    L = np.sqrt(gx * gx + gy * gy + nz)
    nrm = np.stack([-gx / L, gy / L, nz / L], -1)
    return (nrm * 0.5 + 0.5) * 255


# ------------------------------------------------- leaf sprigs (RGBA)
def _leaf(d, cx, cy, ang, length, width, col, vein):
    pts = []
    for i in range(21):
        t = i / 20
        w = width * math.sin(math.pi * t) ** 0.8 * (1 - 0.25 * t)
        pts.append((t * length, w))
    pts += [(x, -y) for x, y in reversed(pts)]
    ca, sa = math.cos(ang), math.sin(ang)
    poly = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]
    d.polygon(poly, fill=col)
    d.line([(cx, cy), (cx + length * 0.92 * ca, cy + length * 0.92 * sa)], fill=vein, width=2)


def sprig(rng, kind):
    S = 1024
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if kind == "olive":
        stem = [(S * 0.5, S * 0.98)]
        x, y = S * 0.5, S * 0.98
        for i in range(10):
            x += rng.uniform(-18, 18)
            y -= S * 0.088
            stem.append((x, y))
        d.line(stem, fill=(92, 78, 60, 255), width=7)
        for i, (sx, sy) in enumerate(stem[1:]):
            for side in (-1, 1):
                ang = -math.pi / 2 + side * rng.uniform(0.5, 1.1)
                g = rng.uniform(0.85, 1.1)
                top = rng.random() < 0.5
                col = (int(118 * g), int(134 * g), int(94 * g), 255) if top else (int(160 * g), int(170 * g), int(140 * g), 255)
                _leaf(d, sx, sy, ang, rng.uniform(150, 210) * (1 - i * 0.03), rng.uniform(17, 24), col,
                      (int(175 * g), int(182 * g), int(150 * g), 255))
        _leaf(d, stem[-1][0], stem[-1][1], -math.pi / 2, 160, 18, (120, 136, 96, 255), (170, 178, 146, 255))
    else:  # broad leaves for houseplants and shrubs
        for i in range(9):
            ang = -math.pi / 2 + rng.uniform(-1.25, 1.25)
            cx, cy = S * 0.5 + rng.uniform(-60, 60), S * 0.96
            L = rng.uniform(420, 600)
            ex, ey = cx + math.cos(ang) * L * 0.35, cy + math.sin(ang) * L * 0.35
            d.line([(cx, cy), (ex, ey)], fill=(74, 96, 52, 255), width=8)
            g = rng.uniform(0.8, 1.15)
            col = (int(52 * g), int(98 * g), int(48 * g), 255)
            _leaf(d, ex, ey, ang + rng.uniform(-0.3, 0.3), L * 0.68, L * 0.2, col, (int(110 * g), int(150 * g), int(90 * g), 255))
    # soft shading & slight blur for antialiasing
    a = np.asarray(im, np.float32)
    n = tnoise(rng, 32, S)
    a[..., :3] *= (0.85 + 0.3 * n)[..., None]
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA").resize((512, 512), Image.LANCZOS)
    return im


def main(out):
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(7)
    oak_pal = [hexrgb(c) for c in ("#C49A6C", "#B88B5C", "#CFA779", "#B4855A", "#C79F72")]
    walnut_pal = [hexrgb(c) for c in ("#6B4A33", "#5E402B", "#77543A", "#563A28")]
    jobs = {
        "oak": lambda: planks(rng, oak_pal),
        "walnut": lambda: planks(rng, walnut_pal, gap_dark=0.6),
        "maltese": lambda: maltese(rng),
        "terrazzo": lambda: terrazzo(rng),
        "porcelain": lambda: porcelain(rng),
        "marble": lambda: marble(rng),
        "concrete": lambda: concrete(rng),
        "limestone": lambda: limestone(rng),
        "terracotta": lambda: terracotta(rng),
        "pebble": lambda: pebble(rng),
    }
    jobs["woodlight"] = lambda: woodgrain(rng, "#C9A273", "#9C7448")
    jobs["wooddark"] = lambda: woodgrain(rng, "#6A4A33", "#3E2A1D")
    for name, fn in jobs.items():
        save(fn(), os.path.join(out, f"{name}.jpg"))
        print("wrote", name)
    save(fabric_normal(rng), os.path.join(out, "fabric_n.png"))
    sprig(rng, "olive").save(os.path.join(out, "leaf_olive.png"), optimize=True)
    sprig(rng, "broad").save(os.path.join(out, "leaf_broad.png"), optimize=True)
    print("wrote fabric_n, leaf_olive, leaf_broad")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tex")
