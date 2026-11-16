"""Render the viewpoints in ../flat.blend with Cycles.

    python render.py                  # all views
    python render.py aerial bedroom   # only some
    SAMPLES=32 python render.py ...   # quick preview

Writes ../web/renders/<view>.jpg (and a 480px thumbnail <view>-sm.jpg).
"""
import math
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "web", "renders")
sys.path.insert(0, HERE)

bpy.ops.wm.open_mainfile(filepath=os.path.join(ROOT, "flat.blend"))
import build_scene  # noqa: E402  (for VIEWS only; does not rebuild)

scn = bpy.context.scene
SAMPLES = int(os.environ.get("SAMPLES", "64"))


def setup_cycles():
    scn.render.engine = "CYCLES"
    cy = scn.cycles
    cy.device = "CPU"
    cy.samples = SAMPLES
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.015
    cy.use_denoising = True
    try:
        cy.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    cy.max_bounces = 10
    cy.diffuse_bounces = 5
    cy.glossy_bounces = 4
    cy.transmission_bounces = 8
    cy.transparent_max_bounces = 8
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.sample_clamp_indirect = 8.0
    cy.blur_glossy = 1.0
    scn.render.use_persistent_data = True
    scn.view_settings.view_transform = "AgX"
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    scn.render.image_settings.file_format = "JPEG"
    scn.render.image_settings.quality = 88
    scn.render.film_transparent = False


def thin_glass():
    """Let sunlight through window glass (no caustics needed)."""
    m = bpy.data.materials["Glass"]
    nt = m.node_tree
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Shadow Ray"], mix.inputs[0])
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def plaster_bump():
    """Subtle trowelled-plaster relief on painted walls and ceilings (render only)."""
    for name, strength in (("WallPaint", 0.08), ("Ceiling", 0.05)):
        m = bpy.data.materials[name]
        nt = m.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 18.0
        noise.inputs["Detail"].default_value = 8.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = strength
        bump.inputs["Distance"].default_value = 0.002
        nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def translucent_leaves():
    """Leaves let some light through: mix in a translucent BSDF, keep the alpha cut-out."""
    for name in ("LeafOlive", "LeafBroad"):
        m = bpy.data.materials.get(name)
        if not m:
            continue
        nt = m.node_tree
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        img = next(n for n in nt.nodes if n.type == "TEX_IMAGE")
        rnd = next(n for n in nt.nodes if n.type == "MATH")
        tl = nt.nodes.new("ShaderNodeBsdfTranslucent")
        nt.links.new(img.outputs["Color"], tl.inputs["Color"])
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.inputs[0].default_value = 0.35
        nt.links.new(bsdf.outputs[0], mix.inputs[1])
        nt.links.new(tl.outputs[0], mix.inputs[2])
        cut = nt.nodes.new("ShaderNodeMixShader")
        tr = nt.nodes.new("ShaderNodeBsdfTransparent")
        nt.links.new(rnd.outputs[0], cut.inputs[0])
        nt.links.new(tr.outputs[0], cut.inputs[1])
        nt.links.new(mix.outputs[0], cut.inputs[2])
        nt.links.new(cut.outputs[0], out.inputs["Surface"])


def set_emission(name, strength):
    m = bpy.data.materials.get(name)
    if not m:
        return
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Emission Strength"].default_value = strength


def configure(view):
    interior = view["interior"]
    for ob in bpy.data.objects:
        if ob.name.startswith("ceil_"):
            ob.hide_render = not interior
        if ob.name.startswith("streetset"):
            ob.hide_render = True
        if ob.type == "LIGHT" and ob.name.startswith(("Ceil_", "Lamp_", "Down_")):
            ob.hide_render = not interior
    set_emission("LampShade", 1.5 if interior else 0.0)
    set_emission("Bulb", 6.0 if interior else 2.0)
    scn.camera = bpy.data.objects["cam_" + view["id"]]
    res = view.get("res", (1280, 800))
    scn.render.resolution_x, scn.render.resolution_y = res
    scn.render.resolution_percentage = int(os.environ.get("RES_PCT", "100"))
    scn.view_settings.exposure = -0.2 if interior else -0.1


def main(ids):
    setup_cycles()
    thin_glass()
    plaster_bump()
    translucent_leaves()
    os.makedirs(OUT, exist_ok=True)
    for v in build_scene.VIEWS:
        if ids and v["id"] not in ids:
            continue
        configure(v)
        path = os.path.join(OUT, v["id"] + ".jpg")
        scn.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print("RENDERED", path, flush=True)
        try:
            from PIL import Image
            im = Image.open(path)
            im.thumbnail((560, 560))
            im.save(path.replace(".jpg", "-sm.jpg"), quality=82)
        except Exception as e:  # thumbnails are optional
            print("thumb failed", e)


if __name__ == "__main__":
    main(sys.argv[1:])
