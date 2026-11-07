"""Robot hand + human hand photo (tools/ref/robot_human.png) -> letter point cloud.

The two arms are cut from the plain wall, then filled with characters whose brightness follows
the photo's own lighting (metal highlights, muscle shading). Edges inside each arm (robot joints,
pistons, plates; knuckles, muscle lines) get an extra run of characters so the detail is crisp.

usage: python hands_from_photo.py [preview.png]
out:   assets/hands_art.bin  (same format the site already reads)
         uint32 count, float32 lightX, float32 lightY
         count x { int16 x,y,z (*3000) ; uint8 tone ; uint8 flags (side<<4 | kind) }
         side 0 = left arm (ROBOT), 1 = right arm (human)
         kind 0 = body, 1 = silhouette, 2 = inner detail edge
"""
import struct
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "ref" / "robot_human.png"
OUT = ROOT / "assets" / "hands_art.bin"
rng = np.random.default_rng(7)

UP = 3
bgr = cv2.imread(str(SRC), cv2.IMREAD_COLOR)
bgr = cv2.resize(bgr, None, fx=UP, fy=UP, interpolation=cv2.INTER_CUBIC)
H, W = bgr.shape[:2]
lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

# ---- cut the arms from the wall: difference from a smooth estimate of the wall
# the wall is near-uniform: estimate it from the image border, with a gentle top->bottom gradient
border = np.concatenate([bgr[:40].reshape(-1, 3), bgr[-40:].reshape(-1, 3)])
top_c = np.median(bgr[:40].reshape(-1, 3), 0)
bot_c = np.median(bgr[-40:].reshape(-1, 3), 0)
ramp = np.linspace(0, 1, H)[:, None, None]
wall = np.clip(top_c * (1 - ramp) + bot_c * ramp, 0, 255).astype(np.uint8) * np.ones((1, W, 1), np.uint8)
wall_lab = cv2.cvtColor(wall, cv2.COLOR_BGR2LAB).astype(np.float32)
diff = np.sqrt(((lab - wall_lab) * np.array([0.7, 1.6, 1.6])) ** 2).sum(-1) if False else \
    np.sqrt(0.5 * (lab[..., 0] - wall_lab[..., 0]) ** 2 + 2.5 * (lab[..., 1] - wall_lab[..., 1]) ** 2 + 2.5 * (lab[..., 2] - wall_lab[..., 2]) ** 2)
# skin is close to the wall in brightness but clearly more saturated / redder
hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
wall_hsv = cv2.cvtColor(wall, cv2.COLOR_BGR2HSV).astype(np.float32)
sat_up = hsv[..., 1] - wall_hsv[..., 1]
redder = lab[..., 1] - wall_lab[..., 1]
# thresholds adapt to how much the wall itself varies (measured on the top/bottom bands)
band = np.zeros((H, W), bool); band[:int(H * 0.22)] = True; band[int(H * 0.8):] = True
def thr(a, extra):
    return np.percentile(a[band], 99.7) + extra
t_diff, t_sat, t_red = thr(diff, 6), thr(sat_up, 8), thr(redder, 3)
print("thresholds diff %.1f sat %.1f red %.1f" % (t_diff, t_sat, t_red))
mask = ((diff > t_diff) | (sat_up > t_sat) | (redder > t_red)).astype(np.uint8)
# wall cracks are thin: an opening removes them, the arms survive
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
# fill holes
ff = mask.copy() * 255
cv2.floodFill(ff, np.zeros((H + 2, W + 2), np.uint8), (0, 0), 128)
mask = ((ff != 128)).astype(np.uint8)
# ---- robot fingers: thin polished chrome is the same brightness as the wall, so the colour cut
#      loses it. Trace each finger (bones, joints, claw tips) from the photo, in source px.
ROBOT_FINGERS = [
    # (chain of points, widths per segment)                       index -> pinky
    ([(440, 268), (474, 277), (488, 288), (506, 300)], [6.0, 4.2, 3.0]),
    ([(442, 281), (477, 302), (492, 306), (497, 326)], [5.6, 4.0, 2.8]),
    ([(435, 289), (470, 302), (479, 321), (481, 342)], [5.6, 4.0, 2.8]),
    ([(426, 294), (441, 318), (436, 334), (433, 350)], [5.6, 4.0, 2.8]),
]
FINGER_JOINTS = [(488, 288), (490, 290), (492, 306), (479, 321), (442, 318), (436, 334), (476, 277)]
fingers = np.zeros((H, W), np.uint8)
for chain, widths in ROBOT_FINGERS:
    for (a, b), w in zip(zip(chain, chain[1:]), widths):
        cv2.line(fingers, (a[0] * UP, a[1] * UP), (b[0] * UP, b[1] * UP), 1, int(w * 1.25 * UP))
    tip = chain[-1]
    cv2.circle(fingers, (tip[0] * UP, tip[1] * UP), int(1.6 * UP), 1, -1)
for jx, jy in FINGER_JOINTS:
    cv2.circle(fingers, (jx * UP, jy * UP), int(3.6 * UP), 1, -1)
# the polished top plate of the hand (bright highlight, same tone as the wall)
top_plate = np.array([(354, 245), (412, 247), (440, 253), (444, 260), (435, 263), (355, 253)], np.int32) * UP
cv2.fillPoly(fingers, [top_plate], 1)
mask = np.maximum(mask, fingers)

# keep the two big pieces (the arms)
n, lab_, stats, _ = cv2.connectedComponentsWithStats(mask)
order = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])[:6]
keep = [i for i in order if stats[i, cv2.CC_STAT_AREA] > 0.004 * H * W]
mask = np.isin(lab_, keep).astype(np.uint8)
print("components kept", len(keep), [int(stats[i, cv2.CC_STAT_AREA]) for i in keep])

# ---- split robot / human at the emptiest column between the fingertips
mid0, mid1 = int(W * 0.4), int(W * 0.6)
colsum = mask[:, mid0:mid1].sum(0)
gap_c = int(np.argmin(colsum)) + mid0
lp = np.argwhere(mask[:, :gap_c]); rp = np.argwhere(mask[:, gap_c:])
lt = lp[np.argmax(lp[:, 1])]
rt = rp[np.argmin(rp[:, 1])]; rt = (rt[0], rt[1] + gap_c)
light = np.array([(lt[1] + rt[1]) / 2.0, (lt[0] + rt[0]) / 2.0])
print("gap col", gap_c, "robot tip", lt, "human tip", rt, "light", light)

# ---- tone: the photo's own lighting, stretched per arm
tone = np.zeros_like(gray)
for side_mask in (mask * (np.arange(W)[None, :] < gap_c), mask * (np.arange(W)[None, :] >= gap_c)):
    v = gray[side_mask > 0]
    lo, hi = np.percentile(v, 2), np.percentile(v, 99.5)
    t = np.clip((gray - lo) / (hi - lo + 1e-6), 0, 1) ** 0.9
    tone = np.where(side_mask > 0, t, tone)

# ---- inner detail edges (joints, plates, pistons, knuckles, muscle lines)
edges = cv2.Canny(cv2.GaussianBlur(gray.astype(np.uint8), (0, 0), 1.6), 28, 70)
er = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
edges = (edges > 0) & (er > 0)
sil = mask - cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))

# ---- depth: rounded bulge from the distance to the silhouette
dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
mxd = cv2.GaussianBlur(cv2.dilate(dist, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))), (0, 0), 12)
depth = np.sqrt(np.clip(dist / (mxd + 1e-3), 0, 1))

# ---- sample characters
pts = []
STEP = 4.6
ys, xs = np.mgrid[0:H:STEP, 0:W:STEP]
ys = (ys + rng.uniform(-STEP / 2, STEP / 2, ys.shape)).astype(int).clip(0, H - 1)
xs = (xs + rng.uniform(-STEP / 2, STEP / 2, xs.shape)).astype(int).clip(0, W - 1)
for y, x in zip(ys.ravel(), xs.ravel()):
    if mask[y, x] and rng.random() < 0.92:
        pts.append((x, y, float(tone[y, x]), 0))
# thin parts (robot fingers, rods): pack characters densely and keep them bright
thin = (mask > 0) & (mxd < 22) & (np.arange(W)[None, :] < gap_c)
ty, tx = np.nonzero(thin)
sel = rng.random(len(tx)) < 0.07
for y, x in zip(ty[sel], tx[sel]):
    pts.append((x, y, float(max(tone[y, x], 0.45)), 0))
fy_, fx_ = np.nonzero(fingers)
sel = rng.random(len(fx_)) < 0.045
for y, x in zip(fy_[sel], fx_[sel]):
    pts.append((x, y, float(max(tone[y, x], 0.5)), 2))
ey, ex = np.nonzero(edges)
sel = rng.random(len(ex)) < 0.3
for y, x in zip(ey[sel], ex[sel]):
    pts.append((x, y, float(max(tone[y, x], 0.55)), 2))
sy, sx = np.nonzero(sil)
sel = rng.random(len(sx)) < 0.3
for y, x in zip(sy[sel], sx[sel]):
    pts.append((x, y, 0.65, 1))
print("points", len(pts))

# ---- world units: full photo width = 10 units, the light at the origin
S = 10.0 / W
with open(OUT, "wb") as f:
    f.write(struct.pack("<Iff", len(pts), 0.0, 0.0))
    for x, y, t, kind in pts:
        side = 0 if x < gap_c else 1
        f.write(struct.pack("<3hBB",
                            int((x - light[0]) * S * 3000), int(-(y - light[1]) * S * 3000),
                            int((depth[y, x] * 0.3 + rng.normal(0, 0.01)) * 3000),
                            int(np.clip(t, 0, 1) * 255), (side << 4) | kind))
print("wrote", OUT, OUT.stat().st_size // 1024, "KB")

if len(sys.argv) > 1:
    prev = np.zeros((H, W, 3), np.uint8)
    for x, y, t, kind in pts:
        v = int(40 + 215 * t)
        prev[y, x] = (40, 40, 255) if kind == 2 and x < gap_c else ((255, 255, 255) if kind == 2 else (v, v, v))
    cv2.circle(prev, (int(light[0]), int(light[1])), 8, (0, 255, 255), 2)
    cv2.imwrite(sys.argv[1], cv2.resize(prev, None, fx=1 / UP, fy=1 / UP, interpolation=cv2.INTER_AREA))
    cv2.imwrite(sys.argv[1].replace(".png", "_mask.png"), cv2.resize(mask * 255, None, fx=1 / UP, fy=1 / UP))
