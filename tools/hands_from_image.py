"""Turn the hand drawing (tools/ref/hands_drawing.jpg) into a letter point cloud.

Every point is a character placed inside the drawn hands. Brightness follows the drawing as a
positive image (light skin bright, pencil shading dim), plus a run of characters along each
silhouette. Depth comes from the distance
to the silhouette edge (fingers/arms bulge toward the camera) so the art turns in 3D.

usage: python hands_from_image.py [preview.png]
out:   assets/hands_art.bin  little endian:
         uint32 count, float32 lightX, float32 lightY
         count x { int16 x,y,z (*3000) ; uint8 tone (0-255, brightness) ; uint8 flags (side<<4 | kind) }
         side 0 = left hand (ROBOT), 1 = right hand (human)
         kind 0 = fill (human skin / robot steel), 1 = outline, 2 = robot seam/trace/pipe, 3 = robot glowing joint
"""
import struct
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "ref" / "hands_drawing.jpg"
OUT = ROOT / "assets" / "hands_art.bin"
rng = np.random.default_rng(5)

UP = 3                     # work at 3x for smooth edges
img = cv2.imread(str(SRC), cv2.IMREAD_GRAYSCALE)
img = cv2.resize(img, None, fx=UP, fy=UP, interpolation=cv2.INTER_CUBIC)
H, W = img.shape

# ---- crop to the band that holds the hands
band = (img < 215).astype(np.uint8)
rows = np.where(band.sum(1) > W * 0.01)[0]
y0, y1 = max(rows.min() - 30, 0), min(rows.max() + 30, H)
img = img[y0:y1]
H, W = img.shape

# ---- ink: darkness, contrast-stretched (white paper -> 0, black line -> 1)
ink = np.clip((235.0 - img.astype(np.float32)) / 185.0, 0, 1)
ink = cv2.GaussianBlur(ink, (0, 0), 0.8)

# ---- silhouette: close the line drawing, then fill everything not reachable from the top/bottom paper
lines = (img < 200).astype(np.uint8) * 255
closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7 * UP, 7 * UP)))
closed = cv2.dilate(closed, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
flood = closed.copy()
ffmask = np.zeros((H + 2, W + 2), np.uint8)
for x in range(0, W, 7):                                  # seed along top and bottom edges (paper)
    for y in (0, H - 1):
        if flood[y, x] == 0:
            cv2.floodFill(flood, ffmask, (x, y), 128)
sil = (flood != 128).astype(np.uint8)
sil = cv2.morphologyEx(sil, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
# keep only big components (the two arms)
n, lab, stats, _ = cv2.connectedComponentsWithStats(sil)
keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 0.01 * H * W]
sil = np.isin(lab, keep).astype(np.uint8)

# ---- which hand: split at the gap between the fingertips (largest empty column run near centre)
cols = sil[:, int(W * 0.35):int(W * 0.65)].sum(0)
gap_c = int(np.argmin(cols)) + int(W * 0.35)
gap_rows = np.where(sil[:, max(gap_c - 40, 0):gap_c + 40].any(1))[0]

# light sits in the gap, at the height of the two closest fingertips
left_pts = np.argwhere(sil[:, :gap_c])
right_pts = np.argwhere(sil[:, gap_c:])
lt = left_pts[np.argmax(left_pts[:, 1])]                  # rightmost pixel of the left hand
rt = right_pts[np.argmin(right_pts[:, 1])]                # leftmost pixel of the right hand
light = np.array([(lt[1] + rt[1] + gap_c) / 2.0, (lt[0] + rt[0]) / 2.0])  # (x, y) in px
print("light px", light, "left tip", lt, "right tip", rt)

# ---- depth from the distance to the edge (rounded bulge)
dist = cv2.distanceTransform(sil, cv2.DIST_L2, 5)
depth = np.sqrt(np.clip(dist / (dist.max() + 1e-6), 0, 1))

edge = sil - cv2.erode(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

# ---- ROBOT: the left hand keeps the drawing's silhouette but gets a machined surface
#      kind 0 = steel plate, 1 = outline, 2 = red seam / trace / hydraulic, 3 = glowing joint
def src(x, y):                      # source-image px -> working px (after the band crop)
    return int(x * UP), int(y * UP - y0)


Lm = sil.copy()
Lm[:, gap_c:] = 0
dL = cv2.distanceTransform(Lm, cv2.DIST_L2, 5)
# limb-normalised profile u (0 at the edge, 1 on the centre line) -> brushed steel cylinder shading
mx = cv2.GaussianBlur(cv2.dilate(dL, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))), (0, 0), 12)
u = np.clip(dL / (mx + 1e-3), 0, 1)
gy = cv2.Sobel(dL, cv2.CV_32F, 0, 1, ksize=5)
upper = (gy > 0).astype(np.float32)                     # upper half of each limb catches the light
steel = 0.16 + 0.42 * u ** 0.8 + 0.42 * np.exp(-((u - 0.72) / 0.13) ** 2) * upper
steel = np.clip(steel, 0, 1)

seam = np.zeros_like(Lm)
node = np.zeros_like(Lm)
wrist_x = src(126, 0)[0]
# 1. inset plate border on every limb
seam[(np.abs(dL - 7) < 1.1) & (mx > 16)] = 1
# 2. the drawing's thin crease lines (not its broad shading) become segment seams between plates
blackhat = cv2.morphologyEx(img, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
crease = (blackhat > 34).astype(np.uint8)
crease = cv2.morphologyEx(crease, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
seam[(crease > 0) & (dL > 9)] = 1
# 3. forearm: segment rings + two hydraulic lines + bolts
cols_top = np.full(W, -1); cols_bot = np.full(W, -1)
for x in range(0, wrist_x):
    ys_ = np.nonzero(Lm[:, x])[0]
    if len(ys_):
        cols_top[x], cols_bot[x] = ys_.min(), ys_.max()
for x in range(0, wrist_x):
    if cols_top[x] < 0:
        continue
    t, b = cols_top[x], cols_bot[x]
    if x % 78 < 4 and x > 20:                                   # segment ring
        seam[t:b, x] = 1
    for f in (0.3, 0.38, 0.62, 0.7):                            # hydraulic pipes (pairs)
        yy = int(t + (b - t) * f)
        seam[yy - 1:yy + 2, x] = 1
    if x % 78 == 39:                                            # bolts between the rings
        for f in (0.18, 0.5, 0.82):
            cv2.circle(node, (x, int(t + (b - t) * f)), 5, 1, 2)
# 4. circuit traces across the back of the hand, each ending in a node
rr = np.random.default_rng(9)
hx0, hx1 = src(150, 0)[0], src(250, 0)[0]
for _ in range(22):
    for _try in range(40):
        x, y = int(rr.uniform(hx0, hx1)), int(rr.uniform(0, H))
        if Lm[y, x] and dL[y, x] > 14:
            break
    else:
        continue
    pts_ = [(x, y)]
    for _seg in range(rr.integers(2, 5)):
        if _seg % 2 == 0:
            x = int(np.clip(x + rr.choice([-1, 1]) * rr.uniform(25, 80), hx0, hx1))
        else:
            y = int(y + rr.choice([-1, 1]) * rr.uniform(15, 45))
        pts_.append((x, y))
    for a, b in zip(pts_, pts_[1:]):
        cv2.line(seam, a, b, 1, 2)
    cv2.circle(node, pts_[-1], 4, 1, -1)
    cv2.circle(node, pts_[0], 3, 1, 1)
# 5. glowing joint rings: wrist, knuckles (MCP), middle joints (PIP), end joints (DIP)
JOINTS = [((130, 556), 15, True)]
JOINTS += [((x, y), 7, False) for x, y in [(262, 572), (251, 589), (239, 602), (226, 614)]]
JOINTS += [((x, y), 6, False) for x, y in [(300, 602), (283, 627), (268, 633), (244, 641)]]
JOINTS += [((x, y), 5, False) for x, y in [(322, 620), (301, 650), (286, 651), (246, 657)]]
for (jx, jy), r, big in JOINTS:
    c = src(jx, jy)
    rad = int(r * UP)
    cv2.circle(node, c, rad, 1, 3)
    cv2.circle(node, c, max(rad // 3, 3), 1, -1)
    if big:
        cv2.circle(node, c, rad + 9, 1, 2)
        for k in range(8):                                       # bearing teeth
            ang = k * np.pi / 4
            cv2.circle(node, (int(c[0] + np.cos(ang) * (rad - 8)), int(c[1] + np.sin(ang) * (rad - 8))), 3, 1, -1)
seam &= Lm
node &= Lm
seam[node > 0] = 0

# ---- sample characters
STEP = 5.0                   # grid spacing in working px (~1.7 source px)
pts = []
ys, xs = np.mgrid[0:H:STEP, 0:W:STEP]
ys = (ys + rng.uniform(-STEP / 2, STEP / 2, ys.shape)).astype(int).clip(0, H - 1)
xs = (xs + rng.uniform(-STEP / 2, STEP / 2, xs.shape)).astype(int).clip(0, W - 1)
for y, x in zip(ys.ravel(), xs.ravel()):
    if not sil[y, x]:
        continue
    if rng.random() > 0.9:
        continue
    if x < gap_c:                                          # robot: steel plate (seams added below)
        if seam[y, x] or node[y, x]:
            continue
        pts.append((x, y, float(steel[y, x]), 0))
        continue
    k = ink[y, x]
    # human: positive image, light skin = bright characters, pencil shading = dimmer ones
    tone = max(0.06, (1.0 - k) ** 1.35)
    pts.append((x, y, tone, 0))
# crisp silhouette rim so each hand separates from the dark page
ey, ex = np.nonzero(edge)
sel = rng.random(len(ex)) < 0.33
for y, x in zip(ey[sel], ex[sel]):
    pts.append((x, y, 0.7, 1))
# robot details: every seam/trace and joint gets its own crisp run of characters
sy, sx = np.nonzero(seam)
sel = rng.random(len(sx)) < 0.42
for y, x in zip(sy[sel], sx[sel]):
    pts.append((x, y, 1.0, 2))
ny_, nx_ = np.nonzero(node)
sel = rng.random(len(nx_)) < 0.6
for y, x in zip(ny_[sel], nx_[sel]):
    pts.append((x, y, 1.0, 3))
print("points", len(pts))

# ---- to world units: full image width = 9.6 units, light at the origin
S = 9.6 / W
with open(OUT, "wb") as f:
    f.write(struct.pack("<Iff", len(pts), 0.0, 0.0))
    for x, y, k, kind in pts:
        wx = (x - light[0]) * S
        wy = -(y - light[1]) * S
        wz = depth[y, x] * 0.32 + rng.normal(0, 0.012)
        side = 0 if x < gap_c else 1
        f.write(struct.pack("<3hBB", int(wx * 3000), int(wy * 3000), int(wz * 3000),
                            int(min(k, 1) * 255), (side << 4) | kind))
print("wrote", OUT, OUT.stat().st_size // 1024, "KB")

if len(sys.argv) > 1:   # preview of what will be drawn in letters
    prev = np.zeros((H, W, 3), np.uint8)
    for x, y, k, kind in pts:
        v = int(60 + 195 * k)
        if kind == 2:
            prev[y, x] = (30, 30, 255)
        elif kind == 3:
            prev[y, x] = (150, 200, 255)
        else:
            prev[y, x] = (v, v, v)
    cv2.circle(prev, (int(light[0]), int(light[1])), 6, (0, 255, 255), 1)
    cv2.imwrite(sys.argv[1], cv2.resize(prev, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
    cv2.imwrite(sys.argv[1].replace(".png", "_mask.png"), cv2.resize(sil * 255, None, fx=0.5, fy=0.5))
