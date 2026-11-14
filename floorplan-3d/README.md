# Ground floor in 3D

A 3D model of the ground-floor plan (maisonette + apartment), built in Blender
from the listing drawing, rendered with Cycles, and viewable in the browser.

```
blender/textures.py     procedural floor textures (oak, Maltese tile, terrazzo, …) -> web/tex/
blender/build_scene.py  builds the flat in Blender from the traced plan -> flat.blend, web/flat.glb, web/scene.json
blender/render.py       Cycles renders of 7 viewpoints -> web/renders/
web/index.html          scroll-to-build tour, orbit and walk-through viewer (three.js)
```

## Rebuild

Blender's Python module works without a Blender install:

```sh
python3 -m venv .venv && .venv/bin/pip install bpy==5.2.4 pillow
.venv/bin/python blender/textures.py web/tex
.venv/bin/python blender/build_scene.py
.venv/bin/python blender/render.py            # SAMPLES=32 RES_PCT=50 for a quick preview
```

Or with a Blender install: `blender -b -P blender/build_scene.py`.

Then serve `web/` with any static server (`python3 -m http.server -d web`) and open it.

## Accuracy

Room outlines were traced from the plan image at roughly 60 px per metre, so
dimensions are approximate (±10 cm). Wall thicknesses (300 mm party walls,
120 mm partitions), the 2.8 m ceiling height, furniture and finishes are
assumptions, not taken from the drawing.
