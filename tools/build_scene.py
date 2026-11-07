"""Blender scene: layered 3D portrait + floating red code glyphs.

Run:  blender --background --factory-startup --python build_scene.py -- <assets_dir>
Outputs: <assets_dir>/scene.glb, <assets_dir>/scene.blend, <assets_dir>/render.png
"""
import math
import random
import sys
from pathlib import Path

import bpy

ASSETS = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
random.seed(3)
ASPECT = 2048 / 1536  # h / w
WIDTH = 3.0
HEIGHT = WIDTH * ASPECT

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def image_material(name, img_path, alpha=False):
    img = bpy.data.images.load(str(img_path))
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    bsdf.inputs["Roughness"].default_value = 0.9
    bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)
    bsdf.inputs["Specular IOR Level"].default_value = 0.0
    # emission so the photo reads at full brightness in renders
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 1.0
    if alpha:
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        if hasattr(mat, "blend_method"):
            mat.blend_method = "HASHED"
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat, img


def displaced_plane(name, mat, disp_img, strength, z, cuts=160, mid=0.5):
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0))
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = (WIDTH, HEIGHT, 1)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=cuts)
    bpy.ops.object.mode_set(mode="OBJECT")
    ob.data.materials.append(mat)
    tex = bpy.data.textures.new(name + "_disp", type="IMAGE")
    tex.image = disp_img
    mod = ob.modifiers.new("Displace", "DISPLACE")
    mod.texture = tex
    mod.texture_coords = "UV"
    mod.strength = strength
    mod.mid_level = mid
    sm = ob.modifiers.new("Smooth", "SMOOTH")
    sm.iterations = 4
    bpy.ops.object.modifier_apply(modifier="Displace")
    bpy.ops.object.modifier_apply(modifier="Smooth")
    # stand it up facing +Y camera (Blender: -Y forward). Plane lies in XY -> rotate to XZ
    ob.rotation_euler = (math.radians(90), 0, 0)
    ob.location = (0, -z, 0)
    bpy.ops.object.transform_apply(rotation=True, location=True)
    bpy.ops.object.shade_smooth()
    return ob


depth_img = bpy.data.images.load(str(ASSETS / "depth.png"))
depth_img.colorspace_settings.name = "Non-Color"

# ---- back plate: mountains + code, gentle relief ----
bg_mat, _ = image_material("Backdrop", ASSETS / "bg_layer.jpg")
back = displaced_plane("Backdrop", bg_mat, depth_img, 0.35, z=-0.6, cuts=140, mid=0.0)
back.scale = (1.097, 1.097, 1.097)  # (6.2+0.6)/6.2: hole lines up with person from the camera
bpy.ops.object.select_all(action="DESELECT")
back.select_set(True)
bpy.context.view_layer.objects.active = back
bpy.ops.object.transform_apply(scale=True)

# ---- person: cut-out with a soft body bulge ----
p_mat, _ = image_material("Person", ASSETS / "person_layer.png", alpha=True)
person = displaced_plane("Person", p_mat, depth_img, 0.18, z=0.0, cuts=120, mid=0.85)

# ---- floating code glyphs ----
glow = bpy.data.materials.new("CodeRed")
glow.use_nodes = True
b = glow.node_tree.nodes["Principled BSDF"]
b.inputs["Base Color"].default_value = (0.78, 0.0, 0.01, 1)
b.inputs["Emission Color"].default_value = (1.0, 0.02, 0.04, 1)
b.inputs["Emission Strength"].default_value = 4.0
b.inputs["Roughness"].default_value = 0.3

white = bpy.data.materials.new("CodeWhite")
white.use_nodes = True
w = white.node_tree.nodes["Principled BSDF"]
w.inputs["Base Color"].default_value = (0.9, 0.9, 0.9, 1)
w.inputs["Emission Color"].default_value = (1, 1, 1, 1)
w.inputs["Emission Strength"].default_value = 1.5

snippets = ["</>", "{ }", "01", "=>", "&&", "fn()", "[ ]", "#", "::", "if", "1", "0",
            "const", "git push", "</>", "sudo", "λ", "++"]
glyphs = bpy.data.collections.new("Glyphs")
scene.collection.children.link(glyphs)

# zones: in FRONT of the photo (Blender -Y = toward camera), below the name, never over the face
def pick_spot():
    # sides of the photo and beyond it (over the rain); the body and face stay clear
    side = random.choice((-1, 1))
    x = side * random.uniform(0.95, 2.2)
    z = random.uniform(-1.8, 0.1)
    return x, random.uniform(-0.95, -0.15), z

FPS, LOOP = 30, 120  # 4 second seamless loop
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, LOOP + 1
prefs = bpy.context.preferences.edit
prefs.keyframe_new_interpolation_type = "LINEAR"

for i in range(18):
    s = random.choice(snippets)
    x, y, z = pick_spot()
    bpy.ops.object.text_add(location=(x, y, z))
    t = bpy.context.active_object
    t.data.body = s
    t.data.align_x = "CENTER"
    t.data.extrude = 0.008
    t.data.bevel_depth = 0.0
    t.data.size = random.uniform(0.05, 0.11)
    rz0 = math.radians(random.uniform(-20, 20))
    t.rotation_euler = (math.radians(90), 0, rz0)
    t.data.materials.append(glow if random.random() < 0.8 else white)
    bpy.ops.object.convert(target="MESH")
    t.name = f"Glyph_{i:02d}"
    for c in t.users_collection:
        c.objects.unlink(t)
    glyphs.objects.link(t)

    # ---- keyframed loop: float, sway, depth drift; some spin like a turntable ----
    ph = random.uniform(0, 2 * math.pi)
    amp_z = random.uniform(0.04, 0.09)
    amp_x = random.uniform(0.01, 0.03)
    amp_y = random.uniform(0.02, 0.06)
    spins = False  # full spins mirror the text; wobble only
    for f in range(1, LOOP + 2, 4):
        u = 2 * math.pi * (f - 1) / LOOP
        t.location = (x + math.sin(u + ph * 0.7) * amp_x, y + math.sin(u * 1 + ph + 1.3) * amp_y, z + math.sin(u + ph) * amp_z)
        t.keyframe_insert("location", frame=f)
        rz = rz0 + (u if spins else math.sin(u + ph) * math.radians(8))
        t.rotation_euler = (math.radians(90), 0, rz)
        t.keyframe_insert("rotation_euler", frame=f)

# ---- camera + lights for the still render ----
bpy.ops.object.camera_add(location=(0, -6.2, 0.15), rotation=(math.radians(90), 0, 0))
cam = bpy.context.active_object
cam.data.lens = 50
scene.camera = cam
world = bpy.data.worlds.new("W")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
scene.world = world

scene.render.resolution_x = 1200
scene.render.resolution_y = 1600
scene.render.film_transparent = False
scene.render.engine = "CYCLES"   # EEVEE needs GPU compute this machine lacks
scene.cycles.device = "CPU"
scene.cycles.samples = 48
scene.cycles.use_denoising = True
scene.view_settings.view_transform = "Standard"

bpy.ops.wm.save_as_mainfile(filepath=str(ASSETS / "scene.blend"))

bpy.ops.object.select_all(action="DESELECT")
for ob in glyphs.objects:
    ob.select_set(True)
bpy.ops.export_scene.gltf(
    filepath=str(ASSETS / "scene.glb"),
    export_format="GLB",
    use_selection=True,          # only the animated code glyphs; the photo is drawn by the site
    export_animations=True,
    export_animation_mode="SCENE",
    export_force_sampling=True,
    export_apply=True,
    export_cameras=False,
    export_lights=False,
    export_yup=True,
    export_image_format="NONE",  # site loads WebP textures itself
)
print("GLB exported")

scene.frame_set(1)
scene.render.filepath = str(ASSETS / "render.png")
try:
    bpy.ops.render.render(write_still=True)
    print("render ok")
except Exception as exc:  # render is a nice-to-have
    print("render skipped:", exc)
