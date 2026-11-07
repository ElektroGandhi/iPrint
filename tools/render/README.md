# How the pictures are made

Every image in the README can be rebuilt from this repository. None of them is a product photo.

| Image | Made by |
|---|---|
| `print-*.png` | `samples.py`: the integration's real code, from text to the exact bits, turned back into a picture |
| `hero.png`, `closeup.png`, `printing.gif` | `render.py`: path-traced with [Mitsuba 3](https://www.mitsuba-renderer.org/) from the OpenSCAD model |
| `logo.svg` | by hand |

The printer in the renders is [`docs/model/t02-style-printer.scad`](../../docs/model/t02-style-printer.scad), an
illustration in the style of the T02. It is not a measured copy, so please do not design parts to fit it.

## Rebuild

```
python3 -m venv venv && venv/bin/pip install mitsuba trimesh scipy networkx pillow numpy
mkdir -p tools/render/build/stl
for part in body lid button led platen; do
  openscad -D "part=\"$part\"" -o "tools/render/build/stl/$part.stl" docs/model/t02-style-printer.scad
done
venv/bin/python tools/render/samples.py
venv/bin/python tools/render/render.py hero
venv/bin/python tools/render/render.py closeup
venv/bin/python tools/render/render.py animation
sh tools/render/make_gif.sh
```

`render.py` uses Mitsuba's `cuda_ad_rgb` variant, so it needs an NVIDIA graphics card. On an RTX 4070 Super a still takes
under a minute, and all 36 animation frames about one minute.
