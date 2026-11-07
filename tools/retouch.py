"""Portrait retouch (local, no upload): skin smoothing with texture kept,
face dodge, clarity on the glasses, overall crisp sharpening.

usage: python retouch.py <src.png> <out.png> [<before_after.jpg>]
"""
import sys

import cv2
import numpy as np

src, out = sys.argv[1], sys.argv[2]
img = cv2.imread(src, cv2.IMREAD_COLOR)
H, W = img.shape[:2]
S = W / 1500.0  # regions traced on a 1500-wide preview


def ellipse_mask(cx, cy, rx, ry, feather):
    m = np.zeros((H, W), np.float32)
    cv2.ellipse(m, (int(cx * S), int(cy * S)), (int(rx * S), int(ry * S)), 0, 0, 360, 1.0, -1)
    k = int(feather * S) | 1
    return cv2.GaussianBlur(m, (k, k), 0)


def rect_mask(x0, y0, x1, y1, feather):
    m = np.zeros((H, W), np.float32)
    cv2.rectangle(m, (int(x0 * S), int(y0 * S)), (int(x1 * S), int(y1 * S)), 1.0, -1)
    k = int(feather * S) | 1
    return cv2.GaussianBlur(m, (k, k), 0)


face = ellipse_mask(822, 1135, 172, 158, 61)          # cheeks, jaw, forehead under the cap
glasses = ellipse_mask(905, 1035, 118, 82, 45)        # lenses only, soft edge
lips = ellipse_mask(880, 1178, 52, 26, 15)
skin = np.clip(face - glasses * 1.2 - lips * 0.6, 0, 1)

f = img.astype(np.float32)

# 1. skin smoothing (frequency-separation style: smooth the base, keep fine texture)
smooth = cv2.bilateralFilter(img, d=0, sigmaColor=38, sigmaSpace=7).astype(np.float32)
low = cv2.GaussianBlur(f, (0, 0), 2.2)
texture = f - low                                    # pores/grain
retouched = smooth + texture * 0.55                  # keep 55% texture -> natural, not plastic
f = f * (1 - skin[..., None] * 0.6) + retouched * (skin[..., None] * 0.6)

# 2. even tone + gentle dodge on the face
# even tone: lift only the darker skin values, leave highlights alone
lift = f + 0.18 * f * (1 - f / 255.0) ** 2
f = f * (1 - face[..., None] * 0.6) + lift * (face[..., None] * 0.6)

# 3. clarity on the glasses (local contrast)
lab = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2LAB)
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
l2 = clahe.apply(lab[..., 0])
lab_c = lab.copy(); lab_c[..., 0] = l2
clar = cv2.cvtColor(lab_c, cv2.COLOR_LAB2BGR).astype(np.float32)
f = f * (1 - glasses[..., None] * 0.6) + clar * (glasses[..., None] * 0.6)

# 4. crisp overall (unsharp mask)
blur = cv2.GaussianBlur(f, (0, 0), 1.4)
f = np.clip(f + (f - blur) * 0.4, 0, 255)

res = f.astype(np.uint8)
cv2.imwrite(out, res)

if len(sys.argv) > 3:  # before/after crop of the face
    x0, y0, x1, y1 = [int(v * S) for v in (560, 760, 1180, 1340)]
    ba = np.hstack([img[y0:y1, x0:x1], np.full((y1 - y0, 12, 3), 0, np.uint8), res[y0:y1, x0:x1]])
    cv2.imwrite(sys.argv[3], ba, [cv2.IMWRITE_JPEG_QUALITY, 90])
print("retouched ->", out)
