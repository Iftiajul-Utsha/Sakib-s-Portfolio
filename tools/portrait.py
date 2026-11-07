"""Portrait pipeline v2 — everything from the ORIGINAL photo.

  1. precise person mask (hand-traced outline refined with GrabCut)
  2. professional retouch: frequency separation (keeps pores, evens blotches), under-eye
     cleanup, dodge & burn contouring for facial structure, lens clarity, fine sharpening
  3. black & white editorial grade (person stays natural; background darker)
  4. red code etched into the mountains + falling code in the sky + thin red rim
  5. web outputs: portrait_edit.jpg/.webp, person_layer.png/.webp, portrait_preview.jpg,
     person_mask.png, review crops

usage: python portrait.py <original.png> [review_dir] [--no-retouch]
       --no-retouch: the source is already retouched; only grade + code are applied
"""
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
RETOUCH = "--no-retouch" not in sys.argv
SRC = Path(ARGS[0])
REVIEW = Path(ARGS[1]) if len(ARGS) > 1 else None
OUT = Path(__file__).resolve().parent.parent / "assets"
random.seed(7)
np.random.seed(7)
RED = np.array([225, 6, 0], np.float32)

# ------------------------------------------------------------------ tuning (review loop)
SMOOTH_BAND = 0.5        # how much of the 2-7px "blotch" band is removed on skin
EVEN_TONE = 0.35         # low-frequency evening on skin
UNDER_EYE = 0.55         # under-eye shadow fill
CONTOUR = 1.0            # strength of dodge & burn sculpting
SHADOW_LIFT = 0.18       # person shadow lift (highlights protected)
CLARITY = 0.14           # local contrast on the person (depth, punch)
SHARPEN = 0.35
BG_DARKEN = 0.62

src = cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE).astype(np.float32)
H, W = src.shape
S = W / 1500.0           # outline below was traced on a 1500-wide preview


def ell(cx, cy, rx, ry, ang=0, feather=25):
    m = np.zeros((H, W), np.float32)
    cv2.ellipse(m, (int(cx), int(cy)), (int(rx), int(ry)), ang, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(m, (0, 0), feather)


# ================================================================== 1. person mask
poly = [
    (0, 2000), (0, 1640), (60, 1560), (130, 1470), (200, 1420), (300, 1360),
    (390, 1300), (460, 1290), (540, 1220), (560, 1180), (600, 1150), (590, 1060),
    (600, 960), (620, 900), (640, 840), (690, 790), (760, 772), (840, 778),
    (920, 798), (970, 840), (990, 880), (1080, 898), (1150, 928), (1162, 962),
    (1162, 990), (1150, 1010), (1100, 1016), (1012, 1012), (1010, 1060), (1000, 1125), (960, 1145),
    (950, 1200), (920, 1250), (875, 1275), (885, 1305), (900, 1335),
    (1000, 1368), (1050, 1400), (1100, 1460), (1150, 1530), (1200, 1595),
    (1232, 1640), (1245, 1800), (1262, 1900), (1290, 2000),
]
poly = np.array([(x * S, y * S) for x, y in poly], np.int32)
poly[:, 1] = np.clip(poly[:, 1], 0, H - 1)
rough = np.zeros((H, W), np.uint8)
cv2.fillPoly(rough, [poly], 1)

# GrabCut at half resolution: sure-fg inside, probable around the traced edge, sure-bg far outside
hs = 2
small = cv2.resize(src, (W // hs, H // hs), interpolation=cv2.INTER_AREA).astype(np.uint8)
small3 = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
rs = cv2.resize(rough, (W // hs, H // hs), interpolation=cv2.INTER_NEAREST)
k = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))
gc = np.full(rs.shape, cv2.GC_BGD, np.uint8)
gc[cv2.dilate(rs, k(31)) > 0] = cv2.GC_PR_BGD
gc[rs > 0] = cv2.GC_PR_FGD
gc[cv2.erode(rs, k(31)) > 0] = cv2.GC_FGD
bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
cv2.grabCut(small3, gc, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
ms = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
ms = cv2.morphologyEx(ms, cv2.MORPH_OPEN, k(5))
ms = cv2.morphologyEx(ms, cv2.MORPH_CLOSE, k(9))
n, lab, st, _ = cv2.connectedComponentsWithStats(ms)
big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
ms = np.where(lab == big, 255, 0).astype(np.uint8)
mask = cv2.resize(ms, (W, H), interpolation=cv2.INTER_LINEAR)
# GrabCut may only refine a thin band at the traced edge: it can never eat into the cap or body
mask = np.maximum(mask, cv2.erode(rough, k(31)) * 255)
mask = cv2.GaussianBlur(mask, (0, 0), 1.2)
mhard = (mask > 127).astype(np.float32)
m_soft = cv2.GaussianBlur(mhard, (0, 0), 1.5)                  # alpha for the cut-out
m_in = cv2.GaussianBlur(cv2.erode(mhard, k(9)), (0, 0), 3)     # grading weight, just inside
cv2.imwrite(str(OUT / "person_mask.png"), (mhard * 255).astype(np.uint8))

# ================================================================== 2. retouch (on the original)
f = src.copy()
if not RETOUCH:
    SMOOTH_BAND = EVEN_TONE = UNDER_EYE = CONTOUR = 0.0
    SHARPEN = 0.15
face = ell(840, 1160, 180, 168, feather=30) * mhard
lenses = ell(945, 1065, 112, 98, feather=10)
lips = ell(905, 1195, 52, 22, feather=8)
ear = ell(655, 1035, 40, 80, feather=12)
skin = np.clip(face - lenses * 1.3 - lips * 0.8, 0, 1)

# 2a. frequency separation: fine detail (pores) kept, the blotch band reduced, base evened
g1 = cv2.GaussianBlur(f, (0, 0), 1.2)
g7 = cv2.GaussianBlur(f, (0, 0), 7.0)
g25 = cv2.GaussianBlur(f, (0, 0), 25.0)
fine = f - g1
band = g1 - g7
base = g7 + (g25 - g7) * EVEN_TONE * skin
f = base + band * (1 - SMOOTH_BAND * skin) + fine

# 2b. under-eye: fill the darker values toward the surrounding cheek level
under = np.clip(ell(845, 1118, 70, 34, ang=-8, feather=14) - lenses, 0, 1)
ref = cv2.GaussianBlur(f, (0, 0), 18)
f = f + np.clip(ref - f, 0, None) * UNDER_EYE * under

# 2c. dodge & burn sculpting (light defines structure; no warping)
def tone(region, amt):
    global f
    f = f * (1 + amt * CONTOUR * region)

tone(ell(795, 1185, 88, 30, ang=24, feather=18) * skin, -0.08)    # under the cheekbone
tone(ell(690, 1150, 30, 85, ang=-8, feather=16) * mhard, -0.06)   # side of the face toward the ear
tone(ell(820, 1268, 120, 26, ang=28, feather=16) * mhard, -0.06)  # jawline shadow
tone(ell(800, 1092, 70, 22, ang=12, feather=14) * skin, +0.07)    # cheekbone highlight
tone(ell(958, 1118, 20, 30, feather=8) * mhard, +0.05)            # nose bridge / tip
tone(ell(930, 1262, 32, 18, feather=10) * mhard, +0.05)           # chin highlight
tone(ell(900, 1172, 26, 9, feather=5) * mhard, +0.03)             # cupid's bow

# 2d. lens clarity
lens8 = np.clip(f, 0, 255).astype(np.uint8)
clar = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(lens8).astype(np.float32)
LENS = 0.55 if RETOUCH else 0.0
f = f * (1 - lenses * LENS) + clar * lenses * LENS

# 2e. local contrast for depth, then crisp detail (not on smoothed skin)
f = f + (f - cv2.GaussianBlur(f, (0, 0), 22)) * (CLARITY if RETOUCH else 0.06) * mhard * (1 - skin * 0.5)
blur = cv2.GaussianBlur(f, (0, 0), 1.3)
f = f + (f - blur) * SHARPEN * mhard * (1 - skin * 0.6)
f = np.clip(f, 0, 255)
cv2.imwrite(str(OUT / "source_retouched.png"), f.astype(np.uint8))

# ================================================================== 2b. widen to a 2:1 full-screen canvas
#   The background (person removed + filled) is mirrored outward from each edge, so the join is
#   seamless, then it softens and darkens with distance (depth of field) so the eye stays on him.
WIDE_W = 4096
W0 = W
PAD = max((WIDE_W - W) // 2, 0)
src0 = src.copy()
if PAD:
    def push_pull(img, w):
        if min(w.shape) <= 2:
            return np.where(w > 0, img, (img * w).sum() / max(w.sum(), 1e-6))
        h, wd = w.shape
        h2, w2 = (h + 1) // 2, (wd + 1) // 2
        pw = np.zeros((h2 * 2, w2 * 2)); pw[:h, :wd] = w
        pc = np.zeros((h2 * 2, w2 * 2)); pc[:h, :wd] = img * w
        ws = pw.reshape(h2, 2, w2, 2).sum((1, 3))
        cs = pc.reshape(h2, 2, w2, 2).sum((1, 3))
        sm = push_pull(cs / np.maximum(ws, 1e-6), np.clip(ws, 0, 1))
        up = cv2.resize(sm.astype(np.float32), (wd, h), interpolation=cv2.INTER_LINEAR)
        return img * w + up * (1 - w)

    known = 1.0 - (cv2.dilate(mhard, k(41)) > 0).astype(np.float32)
    bgonly = push_pull(f.astype(np.float64), known).astype(np.float32)
    # soft tonal backdrop from the photo's own edge tones (no copied shapes, no streaks)
    rowtone = cv2.GaussianBlur(bgonly, (0, 0), sigmaX=70, sigmaY=48)
    ext = cv2.copyMakeBorder(rowtone, 0, 0, PAD, PAD, cv2.BORDER_REPLICATE)
    Wn = ext.shape[1]
    xs_ = np.arange(Wn, dtype=np.float32)
    dx = np.maximum(np.maximum(PAD - xs_, xs_ - (PAD + W - 1)), 0)[None, :]
    t = np.clip(dx / 1100.0, 0, 1)
    ext = cv2.GaussianBlur(ext, (0, 0), sigmaX=30, sigmaY=22)
    ext = ext * (1 - 0.42 * t) + np.random.normal(0, 3.0, ext.shape) * np.clip(t * 3, 0, 1)
    # the photo's background fades into the backdrop over its last 240px; the person never fades
    xi = np.arange(W, dtype=np.float32)
    din = np.minimum(xi, W - 1 - xi)[None, :]
    wp = np.clip(din / 340.0, 0, 1) ** 1.5
    wp = np.maximum(wp, cv2.GaussianBlur(cv2.dilate(mhard, k(25)), (0, 0), 6) * np.clip(din / 110.0, 0, 1))
    f = f * wp + ext[:, PAD:PAD + W] * (1 - wp)
    ext[:, PAD:PAD + W] = f                       # the real photo, untouched, in the centre
    f = ext
    src = f.copy()          # code layer reads the extended scene (no mirrored ghost shapes)
    padm = lambda a: np.pad(a, ((0, 0), (PAD, PAD)))
    mhard, m_soft, m_in, skin = padm(mhard), padm(m_soft), padm(m_in), padm(skin)
    W = Wn

# ================================================================== 3. grade
g = f / 255.0
lo, hi = np.percentile(g, 0.4), np.percentile(g, 99.6)
g = np.clip((g - lo) / (hi - lo), 0, 1)
g = np.clip((g - 0.5) * 1.12 + 0.5, 0, 1)                    # contrast
g = g ** 1.06
lifted = g + SHADOW_LIFT * g * (1 - g) ** 2                   # shadows up, highlights protected
lifted = np.minimum(lifted, np.maximum(g, 0.9))
g = g * (1 - m_in) + lifted * m_in
g = g * (m_in + (1 - m_in) * BG_DARKEN)
yy, xx = np.mgrid[0:H, 0:W]
d = np.sqrt(((xx - (PAD + W0 * 0.55)) / W0) ** 2 + ((yy - H * 0.55) / H) ** 2) * (0.85 if PAD else 1.0)
vig = np.clip(1.15 - d * 0.9, 0.35, 1)
g *= vig * (1 - m_in) + np.maximum(vig, 0.93) * m_in
g = np.clip(g + np.random.normal(0, 0.012, g.shape) * (1 - skin * 0.5), 0, 1)
out = np.repeat(g[..., None], 3, -1) * 255.0

# ================================================================== 4. code
FONT_PX = 20
font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", FONT_PX)
fontb = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", FONT_PX)
GLYPHS = list("01{}[]<>/=+*;:#$&|abcdefxyz") + [chr(c) for c in range(0x30A0, 0x30FF)]
try:
    jfont = ImageFont.truetype("C:/Windows/Fonts/msgothic.ttc", FONT_PX)
except OSError:
    jfont = font
    GLYPHS = [c for c in GLYPHS if ord(c) < 128]
src_img = Image.fromarray(src.astype(np.uint8))
edges = src_img.filter(ImageFilter.GaussianBlur(2)).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(3))
e = np.asarray(edges, np.float32); e = np.clip(e / max(np.percentile(e, 98), 1), 0, 1)
lum = src / 255.0
keep_out = cv2.dilate(mhard, k(25))                              # code never touches the person

code = Image.new("RGBA", (W, H), (0, 0, 0, 0))
cd = ImageDraw.Draw(code)
cw, ch = int(FONT_PX * 0.62), FONT_PX


def glyph():
    c = random.choice(GLYPHS)
    return c, (jfont if ord(c) > 127 else font)


for y in range(0, H, ch):
    for x in range(0, W, cw):
        if keep_out[min(y + ch // 2, H - 1), min(x + cw // 2, W - 1)] > 0:
            continue
        ev = e[y:y + ch, x:x + cw].mean()
        lv = lum[y:y + ch, x:x + cw].mean()
        mz = y > 0.36 * H
        a = min(ev * (1.25 if mz else 0.55) + (lv ** 3) * (0.35 if mz else 0.15), 1.0)
        if a < 0.12 or random.random() > 0.95:
            continue
        c, fnt = glyph()
        cd.text((x, y), c, font=fnt, fill=(255, 235, 235, int(255 * a)) if a > 0.75 else (225, 6, 0, int(255 * a)))
for col_i in range(W // cw):
    if random.random() > 0.42:
        continue
    x = col_i * cw
    length = random.randint(8, 34)
    head = random.randint(0, int(H * 0.95))
    for kk in range(length):
        y = head - kk * ch
        if y < 0:
            break
        if keep_out[min(y + ch // 2, H - 1), min(x + cw // 2, W - 1)] > 0:
            continue
        c, fnt = glyph()
        if kk == 0:
            cd.text((x, y), c, font=fontb if fnt is font else fnt, fill=(255, 245, 245, 255))
        else:
            cd.text((x, y), c, font=fnt, fill=(225, 6, 0, int(210 * (1 - kk / length) ** 1.6)))
code_np = np.asarray(code, np.float32) / 255.0
glow_np = np.asarray(code.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255.0
bgw = (1 - m_soft)[..., None]
lg = glow_np[..., :3] * 255 * glow_np[..., 3:4] * 1.6 * bgw
out = 255 - (255 - out) * (255 - lg) / 255
a = code_np[..., 3:4] * 0.92 * bgw
out = out * (1 - a) + code_np[..., :3] * 255 * a

# thin red rim just outside the silhouette
rim = np.clip(cv2.GaussianBlur(mhard, (0, 0), 3.5) - mhard, 0, 1) * 1.6
rim = np.clip(rim, 0, 1)[..., None]
out = 255 - (255 - out) * (255 - RED * rim) / 255
out = np.clip(out, 0, 255).astype(np.uint8)

# ================================================================== 5. outputs
final = Image.fromarray(out)
final.save(OUT / "portrait_edit.jpg", quality=93)
final.save(OUT / "portrait_edit.webp", quality=78, method=6)
final.crop((PAD, 0, PAD + W0, H)).resize((768, 1024), Image.LANCZOS).save(OUT / "portrait_preview.jpg", quality=86)
person = final.convert("RGBA")
person.putalpha(Image.fromarray((m_soft * 255).astype(np.uint8)))
person.save(OUT / "person_layer.png")
person.save(OUT / "person_layer.webp", quality=90, method=6)

if REVIEW:
    REVIEW.mkdir(parents=True, exist_ok=True)
    final.resize((W // 4, H // 4), Image.LANCZOS).save(REVIEW / "r_full.jpg", quality=88)
    orig = Image.fromarray(src0.astype(np.uint8)).convert("RGB")
    fc = (600, 900, 1100, 1360)
    pair = Image.new("RGB", (1012, 460)); pair.paste(orig.crop(fc), (0, 0)); pair.paste(final.crop((PAD + 600, 900, PAD + 1100, 1360)), (512, 0))
    pair.save(REVIEW / "r_face.jpg", quality=92)
    final.crop((PAD - 500, 600, PAD + 400, 1300)).save(REVIEW / "r_capedge.jpg", quality=90)
    final.crop((PAD + W0 - 500, 300, PAD + W0 + 500, 1300)).save(REVIEW / "r_body.jpg", quality=88)
print("done")
