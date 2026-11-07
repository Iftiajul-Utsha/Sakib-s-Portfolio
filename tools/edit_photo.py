"""Edit the portrait: B&W grade, red Matrix-style code over the mountains/sky,
person kept clean in front, subtle red rim glow.

Outputs (in ../assets):
  portrait_edit.jpg   full edited image (for the website / social)
  bg_layer.png        background with code (person region filled)  -> Blender back plane
  person_layer.png    person cut-out with alpha                     -> Blender front plane
  depth.png           simple depth map (white = near)
"""
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageEnhance

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(7)
np.random.seed(7)

RED = (229, 9, 20)

img = Image.open(SRC).convert("RGB")
W, H = img.size  # 1536 x 2048
S = W / 1500.0   # polygon below was traced in 1500-wide coords

# ---------- 1. person mask (hand-traced silhouette, feathered) ----------
poly = [
    (0, 2000), (0, 1640), (60, 1560), (130, 1470), (200, 1420), (300, 1360),
    (390, 1300), (460, 1290), (540, 1220), (560, 1180), (600, 1150), (590, 1060),
    (600, 960), (620, 900), (640, 840), (690, 790), (760, 772), (840, 778),
    (920, 798), (970, 840), (990, 880), (1080, 898), (1150, 928), (1158, 962),
    (1100, 990), (1012, 1002), (1010, 1060), (1000, 1125), (960, 1145),
    (950, 1200), (920, 1250), (875, 1275), (885, 1305), (900, 1335),
    (1000, 1368), (1050, 1400), (1100, 1460), (1150, 1530), (1200, 1595),
    (1232, 1640), (1245, 1800), (1262, 1900), (1290, 2000),
]
poly = [(x * S, y * S) for x, y in poly]
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).polygon(poly, fill=255)
mask_hard = mask
mask = mask.filter(ImageFilter.GaussianBlur(6))
m = np.asarray(mask, dtype=np.float32) / 255.0
# grading weight sits just INSIDE the silhouette so no un-darkened sky rim (glow) shows around it
m_in = np.asarray(mask_hard.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(3)),
                  dtype=np.float32) / 255.0

# ---------- 2. black & white grade ----------
gray = ImageOps.grayscale(img)
gray = ImageOps.autocontrast(gray, cutoff=0.5)
g = np.asarray(gray, dtype=np.float32) / 255.0
g = np.clip((g - 0.5) * 1.18 + 0.5, 0, 1)          # contrast
g = g ** 1.08                                       # deepen shadows
# background slightly darker so the person pops and code reads
# lift the person's SHADOWS only; highlights (cheeks, under the eyes) are protected
lifted = g + 0.42 * g * (1 - g) ** 2           # shadow/midtone lift, ~0 change near white
lifted = np.minimum(lifted, np.maximum(g, 0.9)) # never push anything past 90% white
g = g * (1 - m_in) + lifted * m_in
g = g * (m_in + (1 - m_in) * 0.62)
# vignette
yy, xx = np.mgrid[0:H, 0:W]
d = np.sqrt(((xx - W * 0.55) / W) ** 2 + ((yy - H * 0.55) / H) ** 2)
vig = np.clip(1.15 - d * 0.9, 0.35, 1)
g *= vig * (1 - m_in) + np.maximum(vig, 0.92) * m_in   # keep the vignette off the person
# grain
g = np.clip(g + np.random.normal(0, 0.018, g.shape), 0, 1)
base = np.stack([g, g, g], -1) * 255.0

# ---------- 3. code layer ----------
FONT_PX = 20
font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", FONT_PX)
fontb = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", FONT_PX)
GLYPHS = list("01{}[]<>/=+*;:#$&|abcdefxyz") + [chr(c) for c in range(0x30A0, 0x30FF)]
try:
    jfont = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", FONT_PX)
except OSError:
    jfont = font
    GLYPHS = [c for c in GLYPHS if ord(c) < 128]

# edge strength of background -> mountain ridges drawn in code
edges = ImageOps.grayscale(img).filter(ImageFilter.GaussianBlur(2)).filter(ImageFilter.FIND_EDGES)
edges = ImageOps.autocontrast(edges.filter(ImageFilter.GaussianBlur(3)), cutoff=2)
e = np.asarray(edges, dtype=np.float32) / 255.0
lum = np.asarray(ImageOps.grayscale(img), dtype=np.float32) / 255.0

code = Image.new("RGBA", (W, H), (0, 0, 0, 0))
cd = ImageDraw.Draw(code)
cw, ch = int(FONT_PX * 0.62), FONT_PX

def glyph():
    c = random.choice(GLYPHS)
    return c, (jfont if ord(c) > 127 else font)

# (a) mountain code: dense grid, alpha from ridge edges + highlights
for y in range(0, H, ch):
    for x in range(0, W, cw):
        if m[min(y + ch // 2, H - 1), min(x + cw // 2, W - 1)] > 0.05:
            continue
        ev = e[y:y + ch, x:x + cw].mean()
        lv = lum[y:y + ch, x:x + cw].mean()
        mountain_zone = y > 0.36 * H
        a = ev * (1.25 if mountain_zone else 0.55) + (lv ** 3) * (0.35 if mountain_zone else 0.15)
        a = min(a, 1.0)
        if a < 0.12 or random.random() > 0.95:
            continue
        c, f = glyph()
        if a > 0.75:
            col = (255, 235, 235, int(255 * min(1, a)))
        else:
            col = (*RED, int(255 * a))
        cd.text((x, y), c, font=f, fill=col)

# (b) falling rain streams (mostly in the sky)
n_cols = W // cw
for col_i in range(n_cols):
    if random.random() > 0.42:
        continue
    x = col_i * cw
    length = random.randint(8, 34)
    head = random.randint(0, int(H * 0.95))
    for k in range(length):
        y = head - k * ch
        if y < 0:
            break
        if m[min(y + ch // 2, H - 1), min(x + cw // 2, W - 1)] > 0.05:
            continue
        t = 1 - k / length
        c, f = glyph()
        if k == 0:
            cd.text((x, y), c, font=fontb if f is font else f, fill=(255, 245, 245, 255))
        else:
            cd.text((x, y), c, font=f, fill=(*RED, int(210 * t ** 1.6)))

# glow for the code
glow = code.filter(ImageFilter.GaussianBlur(5))
code_np = np.asarray(code, dtype=np.float32) / 255.0
glow_np = np.asarray(glow, dtype=np.float32) / 255.0

def over(dst, layer, strength=1.0):
    a = layer[..., 3:4] * strength * (1 - m[..., None])
    return dst * (1 - a) + layer[..., :3] * 255.0 * a

def screen(dst, layer, strength=1.0):
    a = layer[..., 3:4] * strength * (1 - m[..., None])
    l = layer[..., :3] * 255.0 * a
    return 255 - (255 - dst) * (255 - l) / 255.0

out = screen(base, glow_np, 1.6)
out = over(out, code_np, 0.92)

# ---------- 4. red rim light around the person ----------
edge_band = np.asarray(mask_hard.filter(ImageFilter.GaussianBlur(7)), np.float32) / 255.0
rim = np.clip(edge_band - m, 0, 1) * 1.3
rim = np.clip(rim, 0, 1)[..., None]
out = 255 - (255 - out) * (255 - np.array(RED) * rim) / 255.0

out = np.clip(out, 0, 255).astype(np.uint8)
final = Image.fromarray(out)
final.save(OUT / "portrait_edit.jpg", quality=92)

# ---------- 5. layers for Blender ----------
person = final.copy().convert("RGBA")
person.putalpha(mask_hard.filter(ImageFilter.GaussianBlur(1.5)))
person.save(OUT / "person_layer.png")

# background plate: push-pull fill of the (dilated) person hole
def push_pull(rgb, w):
    """rgb HxWx3 float, w HxW float (1 = known). Returns filled rgb."""
    if min(w.shape) <= 2:
        tot = w.sum()
        mean = (rgb * w[..., None]).sum((0, 1)) / max(tot, 1e-6)
        return np.where(w[..., None] > 0, rgb, mean)
    h, wd = w.shape
    h2, w2 = (h + 1) // 2, (wd + 1) // 2
    pw = np.zeros((h2 * 2, w2 * 2)); pw[:h, :wd] = w
    pc = np.zeros((h2 * 2, w2 * 2, 3)); pc[:h, :wd] = rgb * w[..., None]
    ws = pw.reshape(h2, 2, w2, 2).sum((1, 3))
    cs = pc.reshape(h2, 2, w2, 2, 3).sum((1, 3))
    small = cs / np.maximum(ws, 1e-6)[..., None]
    small = push_pull(small, np.clip(ws, 0, 1))
    up = np.asarray(Image.fromarray(np.clip(small, 0, 255).astype(np.uint8)).resize((wd, h), Image.BILINEAR), np.float32)
    return rgb * w[..., None] + up * (1 - w[..., None])

hole = mask_hard.filter(ImageFilter.MaxFilter(25))
known = 1 - np.asarray(hole, np.float32) / 255.0
known = (known > 0.99).astype(np.float32)
filled = push_pull(np.asarray(final, np.float32), known)
# darken the filled area a bit so any edge that peeks out reads as shadow
filled = filled * (known[..., None] + (1 - known[..., None]) * 0.7)
bg = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8))
bg.save(OUT / "bg_layer.jpg", quality=90)

# depth: sky far (0), mountains mid, person near (1)
depth = np.clip((yy / H - 0.2) * 0.6, 0, 0.45) + lum * 0.1
depth = depth * (1 - m) + (0.85 + lum * 0.15) * m
Image.fromarray((np.clip(depth, 0, 1) * 255).astype(np.uint8)).filter(
    ImageFilter.GaussianBlur(4)).save(OUT / "depth.png")

# web-size previews
final.resize((W // 2, H // 2), Image.LANCZOS).save(OUT / "portrait_preview.jpg", quality=85)
print("done", OUT)
