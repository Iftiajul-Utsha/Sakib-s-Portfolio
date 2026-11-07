"""Human hand vs robot hand, modelled in Blender and sampled into lit point clouds.

LEFT : a muscular male arm (metaball anatomy: forearm muscle groups, wrist bone,
       thenar pad, knuckles, tapered 3-segment fingers, nails, raised veins), pointing.
RIGHT: a robot arm (cylindrical forearm, segment rings, hydraulic pistons, armoured palm
       plate with a core, hinged finger links, joint caps), reaching.
Both arms run past the screen edges.

Run:  blender --background --factory-startup --python build_hands.py -- <assets_dir>
Out:  <assets_dir>/hands.bin   little endian:
        uint32 count
        count x { int16 x,y,z (*3000) ; int8 nx,ny,nz (*127) ; uint8 flags (side<<4 | kind) }
      side: 0 human, 1 robot.  kind: 0 skin/plate, 1 vein/nail/detail, 2 panel, 3 glowing joint/core
      coordinates already converted to three.js (Y up, Z toward camera)
      <assets_dir>/hands.blend
"""
import bisect
import math
import random
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ASSETS = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
random.seed(21)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
coll = scene.collection

HUMAN_POINTS = 34000
ROBOT_POINTS = 30000
MB_R = 1.55        # metaball radius multiplier (surface sits inside the influence radius)
ARM_END = -7.4     # forearms run well past the screen edge

# Convention while modelling: hand points +X from the wrist at the origin, fingers spread
# in the XZ plane, the back of the hand faces -Y (toward the camera).


# ============================================================ helpers
def mb_capsule(mb, a, b, r, stiff=2.2):
    a, b = Vector(a), Vector(b)
    d = b - a
    e = mb.elements.new(type="CAPSULE")
    e.co = (a + b) / 2
    e.radius = r * MB_R
    e.size_x = max(d.length / 2, 1e-4)
    e.rotation = Vector((1, 0, 0)).rotation_difference(d.normalized())
    e.stiffness = stiff


def mb_chain(mb, pts, radii, stiff=2.2):
    for i in range(len(pts) - 1):
        mb_capsule(mb, pts[i], pts[i + 1], radii[min(i, len(radii) - 1)], stiff)


def mb_ellipsoid(mb, co, size, r, stiff=2.0):
    e = mb.elements.new(type="ELLIPSOID")
    e.co = co
    e.radius = r * MB_R
    e.size_x, e.size_y, e.size_z = size
    e.stiffness = stiff


def mb_ball(mb, co, r, stiff=2.0):
    e = mb.elements.new(type="BALL")
    e.co = co
    e.radius = r * MB_R
    e.stiffness = stiff


def lerp3(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def align_x_to(ob, a, b):
    """place object at the midpoint of a-b with its local X along a->b"""
    a, b = Vector(a), Vector(b)
    d = b - a
    ob.location = (a + b) / 2
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((1, 0, 0)).rotation_difference(d.normalized())


def apply_all(ob):
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    for m in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def rbox(name, a, b, width, thick, bevel=0.03, kind=0):
    """rounded box from a to b (length along a->b), width along Z-ish, thickness along Y"""
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cube_add(size=1)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = ((b - a).length, thick, width)
    bpy.ops.object.transform_apply(scale=True)
    m = ob.modifiers.new("Bevel", "BEVEL")
    m.width = bevel
    m.segments = 4
    align_x_to(ob, a, b)
    apply_all(ob)
    ob["kind"] = kind
    return ob


def cylinder_y(name, co, r, depth, kind=0, verts=40):
    """cylinder whose axis runs along Y (toward the camera): hinge pins, cores"""
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=co,
                                        rotation=(math.radians(90), 0, 0))
    ob = bpy.context.active_object
    ob.name = name
    m = ob.modifiers.new("Bevel", "BEVEL")
    m.width = min(r, depth) * 0.25
    m.segments = 3
    apply_all(ob)
    ob["kind"] = kind
    return ob


def cylinder_between(name, a, b, r, kind=0, verts=48, bevel=0.0):
    a, b = Vector(a), Vector(b)
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=(b - a).length)
    ob = bpy.context.active_object
    ob.name = name
    # default cylinder axis is Z: rotate Z onto a->b
    ob.location = (a + b) / 2
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference((b - a).normalized())
    if bevel:
        m = ob.modifiers.new("Bevel", "BEVEL")
        m.width = bevel
        m.segments = 3
    apply_all(ob)
    ob["kind"] = kind
    return ob


def torus_on_axis(name, co, major, minor, kind=0):
    """ring around the forearm axis (X)"""
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, location=co,
                                     rotation=(0, math.radians(90), 0),
                                     major_segments=64, minor_segments=12)
    ob = bpy.context.active_object
    ob.name = name
    apply_all(ob)
    ob["kind"] = kind
    return ob


def sphere(name, co, r, scale=(1, 1, 1), kind=0):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=co, segments=32, ring_count=16)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    apply_all(ob)
    ob["kind"] = kind
    return ob


# ============================================================ HUMAN (pointing)
H_FINGERS = [
    # MCP knuckle -> PIP -> DIP -> tip   ; radii per segment
    ("index",  [(0.88, 0, 0.25), (1.30, 0, 0.256), (1.58, 0, 0.246), (1.80, 0, 0.226)], [0.088, 0.079, 0.07]),
    ("middle", [(0.90, 0, 0.085), (1.35, 0, 0.06), (1.57, 0, -0.10), (1.53, 0, -0.27)], [0.091, 0.082, 0.072]),
    ("ring",   [(0.88, 0, -0.075), (1.28, 0, -0.12), (1.46, 0, -0.28), (1.40, 0, -0.42)], [0.086, 0.077, 0.068]),
    ("pinky",  [(0.82, 0, -0.22), (1.12, 0, -0.29), (1.27, 0, -0.41), (1.21, 0, -0.51)], [0.072, 0.065, 0.058]),
]
H_THUMB = [(0.2, 0.0, 0.22), (0.5, -0.03, 0.42), (0.79, -0.04, 0.51), (0.99, -0.03, 0.51)]


def forearm_profile(x):
    """radius of a muscular forearm along x (x<0), belly near the elbow"""
    t = min(max(-x / 4.6, 0), 1)
    return 0.2 + 0.15 * math.sin(t * math.pi * 0.62) + 0.02 * t


def build_human():
    mb = bpy.data.metaballs.new("HumanMB")
    mb.resolution = 0.016
    mb.render_resolution = 0.016
    mb.threshold = 0.6

    # forearm: tapered core
    xs = [0.08, -0.5, -1.1, -1.8, -2.6, -3.4, -4.3, -5.3, -6.4, ARM_END]
    pts = [(x, 0, x * 0.06) for x in xs]
    for i in range(len(pts) - 1):
        r = (forearm_profile(xs[i]) + forearm_profile(xs[i + 1])) / 2 * 0.86
        mb_capsule(mb, pts[i], pts[i + 1], r)
    # muscle groups: brachioradialis (top) + flexors (bottom), bellies toward the elbow
    mb_capsule(mb, (-1.4, -0.02, 0.02), (-4.4, -0.03, -0.12), 0.2)
    mb_ellipsoid(mb, (-3.7, -0.05, 0.02), (2.0, 0.85, 0.85), 0.24)
    mb_capsule(mb, (-1.6, 0.02, -0.17), (-4.6, 0.02, -0.42), 0.19)
    mb_ellipsoid(mb, (-3.9, 0.0, -0.33), (2.2, 0.9, 0.8), 0.23)
    # extensor ridge facing the camera
    mb_capsule(mb, (-1.0, -0.12, -0.04), (-3.8, -0.17, -0.2), 0.12)
    # wrist + ulna head
    mb_capsule(mb, (-0.15, 0, -0.01), (0.22, 0, 0.01), 0.19)
    mb_ball(mb, (-0.08, -0.06, -0.16), 0.075)
    # palm: back of hand + thenar (thumb muscle) + hypothenar
    mb_ellipsoid(mb, (0.45, 0, 0.02), (1.0, 0.3, 0.82), 0.42)
    mb_ellipsoid(mb, (0.75, 0, 0.02), (0.6, 0.29, 1.0), 0.33)
    mb_ellipsoid(mb, (0.33, 0.03, 0.27), (1.15, 0.6, 0.75), 0.2)
    mb_ellipsoid(mb, (0.5, 0.02, -0.2), (1.3, 0.5, 0.55), 0.16)
    # fingers with slightly thinner joints (creases) and knuckle bumps on the back
    for name, chain, radii in H_FINGERS:
        for i in range(3):
            a, b = chain[i], chain[i + 1]
            mb_capsule(mb, lerp3(a, b, 0.06), lerp3(a, b, 0.94), radii[i])
            # soft pad on the palm side of each segment
            mid = lerp3(a, b, 0.5)
            mb_ball(mb, (mid[0], mid[1] + radii[i] * 0.35, mid[2]), radii[i] * 0.55)
        mb_ball(mb, (chain[0][0] + 0.02, chain[0][1] - 0.075, chain[0][2]), 0.062)   # MCP knuckle
        mb_ball(mb, (chain[1][0], chain[1][1] - 0.045, chain[1][2]), 0.045)          # PIP knuckle
    for i in range(3):
        a, b = H_THUMB[i], H_THUMB[i + 1]
        mb_capsule(mb, a, b, [0.12, 0.098, 0.086][i])

    arm = bpy.data.objects.new("HumanArm", mb)
    coll.objects.link(arm)
    arm["kind"] = 0
    parts = [arm]

    # raised veins: thin tubes riding the surface on the camera side
    def vein(name, path, r=0.017):
        cu = bpy.data.curves.new(name, "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = r
        cu.bevel_resolution = 3
        sp = cu.splines.new("BEZIER")
        sp.bezier_points.add(len(path) - 1)
        for bp, p in zip(sp.bezier_points, path):
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = "AUTO"
        ob = bpy.data.objects.new(name, cu)
        coll.objects.link(ob)
        ob["kind"] = 1
        parts.append(ob)

    def on_skin(x, z_off=0.0, lift=0.0):
        r = forearm_profile(x) * 0.86 * 0.62 + 0.11 + lift
        return (x, -r, x * 0.06 + z_off)

    vein("Vein1", [on_skin(x, 0.03) for x in (-0.25, -0.9, -1.7, -2.6, -3.6, -4.8, -6.0)])
    vein("Vein2", [on_skin(x, -0.11) for x in (-0.4, -1.2, -2.0, -2.7)] + [on_skin(-3.2, -0.02)], r=0.014)
    vein("Vein3", [(0.05, -0.135, -0.02), (0.32, -0.15, 0.04), (0.58, -0.145, 0.14), (0.8, -0.12, 0.21)], r=0.012)
    vein("Vein4", [(0.1, -0.135, -0.06), (0.42, -0.15, -0.06), (0.7, -0.14, -0.1)], r=0.011)

    # fingernails: build at the origin, orient along the last phalanx, then move into place
    def nail(name, a, b, r, size):
        a, b = Vector(a), Vector(b)
        d = (b - a).normalized()
        c = b - d * 0.07
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 0), segments=32, ring_count=16)
        ob = bpy.context.active_object
        ob.name = name
        ob.scale = size
        ob.rotation_mode = "QUATERNION"
        ob.rotation_quaternion = Vector((1, 0, 0)).rotation_difference(d)
        ob.location = (c.x, c.y - r * 0.62, c.z)
        apply_all(ob)
        ob["kind"] = 1
        parts.append(ob)

    for name, chain, radii in H_FINGERS:
        nail(f"Nail_{name}", chain[2], chain[3], radii[2], (0.06, 0.018, 0.048))
    nail("Nail_thumb", H_THUMB[2], H_THUMB[3], 0.1, (0.065, 0.02, 0.05))
    return parts


# ============================================================ ROBOT (reaching)
R_FINGERS = [
    ("index",  [(0.92, 0, 0.26), (1.40, 0, 0.245), (1.74, 0, 0.215), (1.98, 0, 0.18)], 0.15),
    ("middle", [(0.95, 0, 0.09), (1.40, 0, 0.03), (1.69, 0, -0.08), (1.85, 0, -0.2)], 0.155),
    ("ring",   [(0.92, 0, -0.08), (1.32, 0, -0.15), (1.57, 0, -0.27), (1.67, 0, -0.39)], 0.145),
    ("pinky",  [(0.85, 0, -0.23), (1.16, 0, -0.31), (1.36, 0, -0.42), (1.43, 0, -0.52)], 0.12),
]
R_THUMB = [(0.24, 0, 0.26), (0.55, -0.03, 0.42), (0.84, -0.03, 0.46), (1.03, -0.02, 0.42)]


def build_robot():
    parts = []
    # forearm: main tube, armour sleeve, segment rings, pistons
    parts.append(cylinder_between("R_Forearm", (ARM_END, 0, ARM_END * 0.05), (-0.42, 0, -0.02), 0.2, kind=0, bevel=0.0))
    parts.append(cylinder_between("R_Sleeve", (-5.4, 0, -0.27), (-1.6, 0, -0.08), 0.27, kind=2, bevel=0.03))
    for i, x in enumerate([-6.6, -5.8, -1.45, -1.15, -0.75]):
        parts.append(torus_on_axis(f"R_Ring{i}", (x, 0, x * 0.05), 0.215 if x > -1.6 else 0.205, 0.022,
                                   kind=3 if i == 4 else 2))
    for x0 in (-5.2, -3.6, -2.0):
        parts.append(torus_on_axis(f"R_SleeveRing{x0}", (x0 + 0.1, 0, (x0 + 0.1) * 0.05), 0.285, 0.018, kind=2))
    # hydraulic pistons along the top and bottom
    for zoff, yoff in ((0.25, -0.1), (-0.26, -0.08)):
        parts.append(cylinder_between(f"R_PistonBody{zoff}", (-4.2, yoff, -0.21 + zoff), (-1.9, yoff, -0.1 + zoff), 0.05, kind=2))
        parts.append(cylinder_between(f"R_PistonRod{zoff}", (-1.9, yoff, -0.1 + zoff), (-0.25, yoff, -0.02 + zoff * 0.7), 0.024, kind=1))
    # wrist: glowing joint sphere + collar
    parts.append(sphere("R_Wrist", (-0.2, 0, -0.01), 0.19, kind=3))
    parts.append(torus_on_axis("R_WristCollar", (-0.36, 0, -0.02), 0.2, 0.03, kind=2))
    # palm: armoured block + back plate + core
    parts.append(rbox("R_Palm", (0.04, 0, 0.02), (0.86, 0, 0.0), 0.68, 0.2, bevel=0.06, kind=0))
    parts.append(rbox("R_BackPlate", (0.16, -0.11, 0.02), (0.78, -0.11, 0.0), 0.48, 0.035, bevel=0.012, kind=2))
    parts.append(cylinder_y("R_Core", (0.44, -0.135, 0.02), 0.085, 0.025, kind=3))
    # knuckle bar
    parts.append(cylinder_between("R_KnuckleBar", (0.86, -0.02, -0.3), (0.86, -0.02, 0.33), 0.06, kind=2))
    # fingers: rounded links + hinge pins + tip caps
    for name, chain, w in R_FINGERS:
        for i in range(3):
            a, b = Vector(chain[i]), Vector(chain[i + 1])
            d = (b - a).normalized()
            ww = w * (1 - i * 0.12)
            parts.append(rbox(f"R_{name}_{i}", a + d * 0.07, b - d * 0.05, ww * 0.95, 0.13 - i * 0.012,
                              bevel=0.018, kind=0))
            parts.append(cylinder_y(f"R_{name}_hinge{i}", chain[i], ww * 0.42, 0.16 - i * 0.01, kind=3 if i == 0 else 2))
        tip = Vector(chain[3])
        parts.append(sphere(f"R_{name}_tip", tuple(tip), w * 0.42, kind=1))
    for i in range(3):
        a, b = Vector(R_THUMB[i]), Vector(R_THUMB[i + 1])
        d = (b - a).normalized()
        parts.append(rbox(f"R_thumb_{i}", a + d * 0.06, b - d * 0.04, 0.16 - i * 0.015, 0.13, bevel=0.02, kind=0))
        parts.append(cylinder_y(f"R_thumb_hinge{i}", R_THUMB[i], 0.055, 0.15, kind=2))
    parts.append(sphere("R_thumb_tip", R_THUMB[3], 0.04, kind=1))
    return [p for p in parts if p is not None]


# ============================================================ place + sample
human_parts = build_human()
robot_parts = build_robot()

# human on the left pointing right: index tip lands just left of centre
# Both index fingertips touch the light at the origin. Each arm is rotated about its own
# fingertip so the forearm sweeps down and out toward the lower screen edge.
GAP = 0.11            # each fingertip stops this far from the centre of the light
SLOPE = -17           # degrees; negative = forearm descends away from the centre
H_TIP = Vector((1.80 + 0.066, 0, 0.226))   # index tip incl. its radius
R_TIP = Vector((1.98 + 0.063, 0, 0.18))    # index tip incl. the cap


def tip_pose(tip, target, mirror):
    M = (Matrix.Translation(target)
         @ (Matrix.Scale(-1, 4, (1, 0, 0)) if mirror else Matrix.Identity(4))
         @ Matrix.Rotation(math.radians(-10), 4, "X")       # back of the hand turns toward the camera
         @ Matrix.Rotation(math.radians(SLOPE), 4, "Y")
         @ Matrix.Translation(-tip))
    return M


M_HUMAN = tip_pose(H_TIP, Vector((-GAP, 0, 0)), mirror=False)
M_ROBOT = tip_pose(R_TIP, Vector((GAP, 0, 0)), mirror=True)

dg = bpy.context.evaluated_depsgraph_get()


def collect_tris(parts, M, smooth):
    """triangles in world space with normals + kind tags"""
    N = M.to_3x3().inverted().transposed()
    out = []
    for ob in parts:
        kind = int(ob.get("kind", 0))
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        me.transform(ob.matrix_world)  # object's own transform (identity for applied parts)
        me.calc_loop_triangles()
        V = [M @ v.co for v in me.vertices]
        VN = [(N @ v.normal).normalized() for v in me.vertices]
        for t in me.loop_triangles:
            i0, i1, i2 = t.vertices
            a, b, c = V[i0], V[i1], V[i2]
            area = ((b - a).cross(c - a)).length / 2
            if area <= 0:
                continue
            if smooth:
                ns = (VN[i0], VN[i1], VN[i2])
            else:
                fn = (N @ t.normal).normalized()
                ns = (fn, fn, fn)
            out.append((area, a, b, c, ns, kind))
    return out


def sample(tris, n, side, weight_kind=None):
    weights = [t[0] * (weight_kind.get(t[5], 1.0) if weight_kind else 1.0) for t in tris]
    total = sum(weights)
    cdf, acc = [], 0.0
    for w in weights:
        acc += w / total
        cdf.append(acc)
    pts = []
    for _ in range(n):
        _, a, b, c, ns, kind = tris[min(bisect.bisect_left(cdf, random.random()), len(tris) - 1)]
        u, v = random.random(), random.random()
        if u + v > 1:
            u, v = 1 - u, 1 - v
        w0 = 1 - u - v
        p = a * w0 + b * u + c * v
        nrm = (ns[0] * w0 + ns[1] * u + ns[2] * v).normalized()
        pts.append((p, nrm, side, kind))
    return pts


ht = collect_tris(human_parts, M_HUMAN, smooth=True)
rt = collect_tris(robot_parts, M_ROBOT, smooth=False)
print("human tris", len(ht), "robot tris", len(rt))
# details get a little extra density so they read
hp = sample(ht, HUMAN_POINTS, 0, {1: 2.2})
rp = sample(rt, ROBOT_POINTS, 1, {1: 1.6, 3: 2.0})

with open(ASSETS / "hands.bin", "wb") as f:
    allp = hp + rp
    f.write(struct.pack("<I", len(allp)))
    for p, n, side, kind in allp:
        # Blender (x, y, z) with -Y toward camera  ->  three.js (x, z, -y)
        f.write(struct.pack("<3h3bB",
                            int(round(p.x * 3000)), int(round(p.z * 3000)), int(round(-p.y * 3000)),
                            int(round(n.x * 127)), int(round(n.z * 127)), int(round(-n.y * 127)),
                            (side << 4) | kind))

bpy.ops.wm.save_as_mainfile(filepath=str(ASSETS / "hands.blend"))
print("hands exported", len(hp), len(rp))
