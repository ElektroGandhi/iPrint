#!/usr/bin/env python3
"""Path-traced renders of the printer with Mitsuba 3. The paper's texture is the real output of tools/render/samples.py.

    pip install mitsuba trimesh pillow numpy
    openscad -D 'part="body"' -o tools/render/build/stl/body.stl docs/model/t02-style-printer.scad   # and lid, button, led, platen
    python3 tools/render/samples.py
    python3 tools/render/render.py hero
"""
import argparse
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont

import mitsuba as mi

mi.set_variant("cuda_ad_rgb")
import drjit as dr  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "tools/render/build"
OUT = ROOT / "docs/images"
H, SLIT_Y, PAPER_W = 36.0, 14.0, 53.0
DOTS_PER_MM = 8
ACCENT = [0.012, 0.19, 0.20]      # deep teal, linear RGB


def part(name: str) -> Path:
    """STL -> PLY: curves shade smooth, hard edges stay hard. Averaging across the slit's edges would turn it black."""
    target = BUILD / f"{name}.ply"
    mesh = trimesh.load_mesh(BUILD / "stl" / f"{name}.stl")
    mesh.merge_vertices()
    mesh = trimesh.graph.smooth_shade(mesh, angle=math.radians(35))
    mesh.vertex_normals  # noqa: B018  (computed lazily, needed by the export)
    target.write_bytes(trimesh.exchange.ply.export_ply(mesh, vertex_normal=True))
    return target


def paper_texture() -> tuple[Path, float]:
    """Dots from the real renderer on paper colour, with the margins of a 53 mm roll. Returns the length in mm."""
    dots = Image.open(BUILD / "receipt_dots.png").convert("L")
    side = round((PAPER_W * DOTS_PER_MM - dots.width) / 2)
    top, tail = 3 * DOTS_PER_MM, 7 * DOTS_PER_MM
    canvas = Image.new("L", (dots.width + 2 * side, dots.height + top + tail), 255)
    canvas.paste(dots, (side, top))
    scale = 4
    big = canvas.resize((canvas.width * scale, canvas.height * scale), Image.Resampling.NEAREST)
    arr = np.asarray(big, dtype=np.float32) / 255.0
    paper, ink = np.array([0.96, 0.945, 0.90]), np.array([0.05, 0.05, 0.06])
    rgb = (ink + (paper - ink) * arr[..., None]) * 255
    target = BUILD / "paper.png"
    Image.fromarray(rgb.astype(np.uint8)).save(target)
    return target, canvas.height / DOTS_PER_MM


def name_decal() -> Path:
    """The name on the lid, as an opacity mask in the integration's own font."""
    image = Image.new("L", (680, 220), 0)
    font = ImageFont.truetype(str(ROOT / "custom_components/iprint/fonts/DejaVuSans.ttf"), 170)
    ImageDraw.Draw(image).text((340, 110), "iPrint", font=font, fill=255, anchor="mm", stroke_width=3, stroke_fill=255)
    target = BUILD / "name.png"
    image.transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(target)
    return target


def paper_mesh(length: float, shown: float = 1.0) -> Path:
    """A strip rising out of the slit. `shown` is how much has been printed: the far end of the strip comes out first."""
    n, visible = 80, length * shown
    points = [np.array([SLIT_Y + 0.8, H - 3.0])]
    step = (visible + 3.0) / n
    for i in range(n):
        s = i / n
        lean = math.radians(7 + 26 * s * s * s - 12 * math.sin(s * math.pi))   # away from the viewer, then a soft curl
        points.append(points[-1] + step * np.array([math.sin(lean), math.cos(lean)]))
    lines = []
    for i, (y, z) in enumerate(points):
        along = 1 - visible / length + (i / n) * visible / length   # v = 1 is the first dot printed, the far end
        for x, u in ((-PAPER_W / 2, 0.0), (PAPER_W / 2, 1.0)):
            lines.append(f"v {x:.3f} {y:.3f} {z:.3f}\nvt {u:.4f} {along:.5f}")
    for i in range(n):
        a, b, c, d = 2 * i + 1, 2 * i + 2, 2 * i + 3, 2 * i + 4
        lines.append(f"f {a}/{a} {b}/{b} {d}/{d}\nf {a}/{a} {d}/{d} {c}/{c}")
    target = BUILD / f"paper_{shown:.3f}.obj"
    target.write_text("\n".join(lines))
    return target


def scene(res, spp, cam_origin, cam_target, fov, shown=1.0):
    tex, length = paper_texture()
    plastic = lambda rgb, rough=0.32: {"type": "principled", "base_color": {"type": "rgb", "value": rgb},  # noqa: E731
                                       "roughness": rough, "specular": 0.5}
    return mi.load_dict({
        "type": "scene",
        "integrator": {"type": "path", "max_depth": 8},
        "sensor": {"type": "perspective", "fov": fov,
                   "to_world": mi.ScalarTransform4f().look_at(origin=cam_origin, target=cam_target, up=[0, 0, 1]),
                   "film": {"type": "hdrfilm", "width": res[0], "height": res[1], "rfilter": {"type": "gaussian"},
                            "pixel_format": "rgb", "component_format": "float32"},
                   "sampler": {"type": "independent", "sample_count": spp}},
        "floor": {"type": "rectangle",
                  "to_world": mi.ScalarTransform4f().scale([2000, 2000, 1]),
                  "bsdf": plastic([0.46, 0.47, 0.48], 0.45)},
        "env": {"type": "constant", "radiance": {"type": "rgb", "value": [0.46, 0.47, 0.49]}},
        "key": {"type": "rectangle",
                "to_world": mi.ScalarTransform4f().look_at(origin=[-170, -190, 300], target=[0, 0, 30], up=[0, 0, 1])
                @ mi.ScalarTransform4f().scale([140, 140, 1]),
                "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [2.5, 2.4, 2.25]}}},
        "rim": {"type": "rectangle",
                "to_world": mi.ScalarTransform4f().look_at(origin=[380, -30, 340], target=[0, 0, 40], up=[0, 0, 1])
                @ mi.ScalarTransform4f().scale([70, 110, 1]),
                "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [1.5, 1.8, 2.1]}}},
        "body": {"type": "ply", "filename": str(part("body")), "bsdf": plastic(ACCENT)},
        "lid": {"type": "ply", "filename": str(part("lid")), "bsdf": plastic([0.74, 0.74, 0.72])},
        "name": {"type": "rectangle",
                 "to_world": mi.ScalarTransform4f().translate([-8, -24, H + 0.03]).scale([17, 5.5, 1]),
                 "bsdf": {"type": "mask", "opacity": {"type": "bitmap", "filename": str(name_decal()), "raw": True},
                          "nested": plastic(ACCENT, 0.4)}},
        "button": {"type": "ply", "filename": str(part("button")), "bsdf": plastic(ACCENT, 0.4)},
        "led": {"type": "ply", "filename": str(part("led")),
                "emitter": {"type": "area", "radiance": {"type": "rgb", "value": [0.4, 7.0, 3.2]}}},
        "platen": {"type": "ply", "filename": str(part("platen")), "bsdf": plastic([0.015, 0.015, 0.018], 0.6)},
        "paper": {"type": "obj", "filename": str(paper_mesh(length, shown)),
                  "bsdf": {"type": "twosided", "nested": {
                      "type": "diffuse",
                      "reflectance": {"type": "bitmap", "filename": str(tex), "filter_type": "bilinear",
                                      "wrap_mode": "clamp"}}}},
    })


def to_image(result) -> Image.Image:
    linear = np.array(result, dtype=np.float32)
    mapped = linear / (1 + 0.18 * linear) * 1.18      # gentle highlight roll-off
    srgb = np.where(mapped <= 0.0031308, 12.92 * mapped, 1.055 * np.power(np.clip(mapped, 1e-6, None), 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8))


def render(name, res, spp, origin, target, fov, shown=1.0, out=None):
    s = scene(res, spp, origin, target, fov, shown)
    # Accumulate in passes: GPU memory stays small however many samples are asked for.
    passes = max(1, spp // 64)
    total = None
    for i in range(passes):
        image = mi.render(s, spp=min(spp, 64), seed=i)
        dr.eval(image)
        total = image if total is None else total + image
        dr.eval(total)
    total = total / passes
    image = to_image(total)
    path = out or OUT / f"{name}.png"
    image.save(path, optimize=True)
    print(path, image.size)


SHOTS = {
    "hero": dict(res=(1600, 900), spp=4096, origin=[-150, -330, 135], target=[0, 0, 47], fov=30),
    "closeup": dict(res=(1200, 1200), spp=4096, origin=[-66, -190, 170], target=[0, 2, 50], fov=32),
    "preview": dict(res=(800, 450), spp=512, origin=[-150, -330, 135], target=[0, 0, 47], fov=30),
}


def animation(frames: int = 36) -> None:
    """The paper coming out, then a pause. Frames go to build/frames; tools/render/make_gif.sh joins them."""
    folder = BUILD / "frames"
    folder.mkdir(exist_ok=True)
    for i in range(frames):
        shown = min(1.0, 0.02 + (i / (frames - 1)) * 0.98)
        render("frame", (720, 405), 512, [-150, -330, 135], [0, 0, 47], 30, shown=shown,
               out=folder / f"{i:03}.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("shot", choices=[*SHOTS, "animation"])
    render_args = ap.parse_args()
    if render_args.shot == "animation":
        animation()
    else:
        render(render_args.shot, **SHOTS[render_args.shot])
