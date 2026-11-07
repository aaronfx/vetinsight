"""Generate a synthetic Pap-style microscope field for testing the app. NOT real data.

The picture is drawn procedurally (no real cells, no patient data). It is only a plumbing test for upload,
analysis, overlay and review. Detector behaviour on it says nothing about clinical accuracy. Planted cell
positions are written to a .truth.json file so results can be compared with known positions.
"""
import argparse, json, math, pathlib, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 2048, 1532


def blob(rng, cx, cy, r, wobble=0.12, n=28):
    phase = [rng.uniform(0, 2 * math.pi) for _ in range(3)]
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        k = 1 + wobble * (math.sin(2 * a + phase[0]) * 0.6 + math.sin(3 * a + phase[1]) * 0.3 + math.sin(5 * a + phase[2]) * 0.1)
        pts.append((cx + r * k * math.cos(a), cy + r * k * math.sin(a) * rng.uniform(0.85, 1.0)))
    return pts


def background(rng):
    base = np.zeros((H, W, 3), np.float32) + np.array([206, 219, 225], np.float32)
    low = np.random.default_rng(rng.randrange(1 << 30)).normal(0, 1, (H // 96 + 2, W // 96 + 2)).astype(np.float32)
    low = np.asarray(Image.fromarray(low).resize((W, H), Image.BICUBIC))
    return Image.fromarray(np.clip(base + low[..., None] * 4.0, 0, 255).astype(np.uint8))


def paste_shape(img, pts, color, alpha, outline=None):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=int(255 * alpha))
    mask = mask.filter(ImageFilter.GaussianBlur(2.2))
    img.paste(Image.new("RGB", img.size, color), mask=mask)
    if outline:
        ring = Image.new("L", img.size, 0)
        ImageDraw.Draw(ring).line(pts + [pts[0]], fill=110, width=4)
        img.paste(Image.new("RGB", img.size, outline), mask=ring.filter(ImageFilter.GaussianBlur(1.6)))


def nucleus(img, rng, cx, cy, r, color, texture=True):
    pts = blob(rng, cx, cy, r, wobble=0.10, n=20)
    paste_shape(img, pts, color, 0.95, outline=tuple(max(c - 30, 0) for c in color))
    if texture:
        d = ImageDraw.Draw(img)
        for _ in range(int(r * 1.2)):
            a, rr = rng.uniform(0, 2 * math.pi), r * math.sqrt(rng.random()) * 0.8
            x, y = cx + rr * math.cos(a), cy + rr * math.sin(a)
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=tuple(max(c - 35, 0) for c in color))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent / "synthetic" / "synthetic-field-01.jpg"))
    ap.add_argument("--normal", type=int, default=9)
    ap.add_argument("--abnormal", type=int, default=2)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    img = background(rng)
    cytoplasm = [(236, 201, 172), (176, 217, 206), (240, 226, 188)]
    placed, truth = [], []

    def place(r, tries=400):
        for _ in range(tries):
            cx, cy = rng.uniform(r + 20, W - r - 20), rng.uniform(r + 20, H - r - 20)
            if all(math.hypot(cx - px, cy - py) > 1.05 * (r + pr) for px, py, pr in placed):
                placed.append((cx, cy, r)); return cx, cy
        return None

    for kind, count in (("normal", args.normal), ("abnormal", args.abnormal)):
        for _ in range(count):
            r = rng.uniform(95, 135) if kind == "normal" else rng.uniform(62, 82)
            spot = place(r)
            if not spot:
                continue
            cx, cy = spot
            color = rng.choice(cytoplasm)
            paste_shape(img, blob(rng, cx, cy, r), color, 0.82, outline=tuple(int(c * 0.72) for c in color))
            if kind == "normal":
                nucleus(img, rng, cx + rng.uniform(-10, 10), cy + rng.uniform(-10, 10), rng.uniform(13, 19), (104, 72, 104))
            else:  # large, dark, irregular nucleus (high nuclear-to-cytoplasm ratio)
                nucleus(img, rng, cx + rng.uniform(-6, 6), cy + rng.uniform(-6, 6), rng.uniform(32, 42), (66, 44, 84))
            truth.append(dict(kind=kind, x=round(cx - r), y=round(cy - r), width=round(2 * r), height=round(2 * r)))
    d = ImageDraw.Draw(img)
    for _ in range(rng.randint(4, 7)):  # small inflammatory cells in clusters
        cx, cy = rng.uniform(40, W - 40), rng.uniform(40, H - 40)
        if any(math.hypot(cx - px, cy - py) < pr * 0.9 for px, py, pr in placed):
            continue
        for _ in range(rng.randint(1, 4)):
            x, y, r = cx + rng.uniform(-22, 22), cy + rng.uniform(-22, 22), rng.uniform(9, 13)
            d.ellipse([x - r, y - r, x + r, y + r], fill=(52, 66, 96), outline=(36, 44, 70), width=2)
    for _ in range(40):  # debris specks
        x, y, r = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(1.5, 4)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(120, 130, 140))
    img = img.filter(ImageFilter.GaussianBlur(1.1))
    arr = np.asarray(img).astype(np.float32) + np.random.default_rng(args.seed).normal(0, 2.4, (H, W, 3))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(out, quality=92)
    out.with_suffix(".truth.json").write_text(json.dumps(dict(
        note="SYNTHETIC test image. Boxes are the planted cell extents. Not real data.", seed=args.seed,
        image=dict(width=W, height=H), cells=truth), indent=2))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB) with {len(truth)} planted cells")


if __name__ == "__main__":
    main()
