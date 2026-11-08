"""Classical nucleus marking inside a detected cell box (NumPy + Pillow only, no extra dependencies).

For one cell box the cell body is separated from the slide background by colour distance, then the nucleus is the
darkest compact region inside that body. When the body cannot be separated (crowded, very large or very pale cells)
the nucleus alone is searched for in the middle of the box and no N:C ratio is given. Outputs are heuristic image
measurements for human review: not a trained model, not validated against nucleus outlines, never diagnoses.
"""
from collections import deque

import numpy as np
from PIL import Image, ImageFilter

MAX_WORK = 170          # longest side of the working crop, in pixels
MIN_CONTRAST = 15.0     # nucleus must be at least this much darker (0-255) than the surrounding cell/box
BRIGHT_FRACTION = 0.35  # the brightest fraction of the image is treated as slide background


def _label(mask):
    h, w = mask.shape
    labels = np.zeros((h, w), np.int32)
    count = 0
    for y0, x0 in zip(*(a.tolist() for a in np.nonzero(mask))):
        if labels[y0, x0]:
            continue
        count += 1
        labels[y0, x0] = count
        queue = deque([(y0, x0)])
        while queue:
            y, x = queue.popleft()
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = count
                    queue.append((ny, nx))
    return labels, count


def _dilate(mask):
    p = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):
            out |= p[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def _erode(mask):
    return ~_dilate(~mask)


def _fill_holes(mask):
    labels, count = _label(~mask)
    if not count:
        return mask
    border = set(labels[0, :].tolist()) | set(labels[-1, :].tolist()) | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    return mask | np.isin(labels, [i for i in range(1, count + 1) if i not in border])


def _otsu(values):
    hist, edges = np.histogram(values, bins=64, range=(0, 255))
    p = hist / max(hist.sum(), 1)
    omega, mu = np.cumsum(p), np.cumsum(p * np.arange(64))
    between = (mu[-1] * omega - mu) ** 2 / np.maximum(omega * (1 - omega), 1e-9)
    return float(edges[int(np.argmax(between[:-1])) + 1])


def slide_background(image):
    """Median colour and noise of the brightest part of the image (the empty slide), computed once per image."""
    small = np.asarray(image.resize((256, 192), Image.BILINEAR), np.float32).reshape(-1, 3)
    luminance = small @ np.array([0.299, 0.587, 0.114], np.float32)
    bright = small[luminance >= np.quantile(luminance, 1 - BRIGHT_FRACTION)]
    colour = np.median(bright, axis=0)
    return colour, float(np.median(np.linalg.norm(bright - colour, axis=1)))


def _find_nucleus(luminance, region, max_fraction):
    """Darkest compact component inside region. Returns (mask, contrast) or (None, reason)."""
    values = luminance[region]
    if len(values) < 30:
        return None, 'region_too_small'
    threshold = _otsu(values)
    dark, light = region & (luminance <= threshold), region & (luminance > threshold)
    if not dark.any() or not light.any():
        return None, 'no_split'
    contrast = float(luminance[light].mean() - luminance[dark].mean())
    if contrast < MIN_CONTRAST:
        return None, 'low_contrast'
    labels, count = _label(_dilate(_erode(dark)))
    if not count:
        return None, 'no_dark_region'
    sizes = np.bincount(labels.ravel())[1:]
    cy, cx = (np.array(region.shape) - 1) / 2.0
    best, best_distance = None, None
    for index in np.nonzero(sizes >= 0.5 * sizes.max())[0] + 1:  # similar-sized candidates: prefer the most central
        ys, xs = np.nonzero(labels == index)
        distance = (ys.mean() - cy) ** 2 + (xs.mean() - cx) ** 2
        if best_distance is None or distance < best_distance:
            best, best_distance = int(index), distance
    nucleus = _fill_holes(labels == best)
    area = int(nucleus.sum())
    if area < 6 or not 0.004 <= area / region.sum() <= max_fraction:
        return None, 'nucleus_size'
    return nucleus, contrast


def mark_nucleus(image, box, background=None):
    """Return nucleus measurements for one cell box in pixel coordinates, or None when no clear nucleus is found.

    image: RGB PIL image. box: (x1, y1, x2, y2) in pixels. background: optional slide_background(image) result.
    """
    return analyse(image, box, background)[0]


def analyse(image, box, background=None):
    """Like mark_nucleus but returns (result, reason); reason names the step that gave up when result is None."""
    width, height = image.size
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    bw, bh = x2 - x1, y2 - y1
    if bw < 24 or bh < 24:
        return None, 'box_too_small'
    colour, noise = background if background is not None else slide_background(image)
    scale = max(1, int(np.ceil(max(bw, bh) / MAX_WORK)))
    sw, sh = max(8, bw // scale), max(8, bh // scale)
    small = image.crop((x1, y1, x2, y2)).resize((sw, sh), Image.BILINEAR).filter(ImageFilter.GaussianBlur(1.0))
    rgb = np.asarray(small, np.float32)
    distance = np.linalg.norm(rgb - colour, axis=2)
    luminance = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    central = np.zeros((sh, sw), bool)
    central[sh // 6: sh - sh // 6, sw // 6: sw - sw // 6] = True

    nucleus, detail, cell_area = None, None, None
    body = _fill_holes(_erode(_dilate(_dilate(distance > max(10.0, 4.0 * noise + 5.0)))))
    labels, count = _label(body)
    middle = labels[central]
    middle = middle[middle > 0]
    if count and len(middle):
        body = labels == int(np.bincount(middle).argmax())
        if body.sum() >= 0.08 * sw * sh:
            nucleus, detail = _find_nucleus(luminance, body, 0.6)
            if nucleus is not None:
                cell_area = int(body.sum())
    if nucleus is None:  # body not separable: look for the nucleus alone in the middle of the box
        nucleus, detail = _find_nucleus(luminance, central, 0.35)
        if nucleus is None:
            return None, detail
    ys, xs = np.nonzero(nucleus)
    area = int(nucleus.sum()) * scale * scale
    cell = cell_area * scale * scale if cell_area else None
    cytoplasm = cell - area if cell else None
    return dict(
        cx=x1 + (float(xs.mean()) + 0.5) * bw / sw, cy=y1 + (float(ys.mean()) + 0.5) * bh / sh,
        x=x1 + float(xs.min()) * bw / sw, y=y1 + float(ys.min()) * bh / sh,
        width=float(xs.max() - xs.min() + 1) * bw / sw, height=float(ys.max() - ys.min() + 1) * bh / sh,
        nucleus_area=area, cell_area=cell, nc_ratio=(area / cytoplasm) if cytoplasm and cytoplasm > 0 else None,
        contrast=detail), ('ok' if cell else 'ok_nucleus_only')
