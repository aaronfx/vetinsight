"""Validate classical nucleus marking against APCData nucleus point labels.

Ground truth is one nucleus-centre point per annotated cell (APCData_points). There are no nucleus outlines, so this
checks that the marked nucleus is in the right place, not that its area, and therefore the N:C ratio, is correct.

Modes:
  gt        run on the expert cell boxes (isolates the nucleus step)
  detector  run on detector candidates from the packaged model (full pipeline)
"""
import argparse, csv, json, pathlib, statistics, sys, time
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
from PIL import Image
from app import nuclei

POINTS = HERE / "extracted" / "APCData cervical cytology cells" / "APCData_points" / "labels" / "csv"


def points_for(file_name):
    number = pathlib.Path(file_name).name[:4]
    rows = list(csv.DictReader(open(POINTS / f"{number}.csv")))
    return [(float(r["nucleus_x"]), float(r["nucleus_y"]), r["bethesda_system"]) for r in rows]


def hit(mark, px, py, tolerance):
    if mark is None:
        return False, None
    dist = ((mark["cx"] - px) ** 2 + (mark["cy"] - py) ** 2) ** 0.5
    inside = mark["x"] - tolerance <= px <= mark["x"] + mark["width"] + tolerance and mark["y"] - tolerance <= py <= mark["y"] + mark["height"] + tolerance
    return inside, dist


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--mode", choices=["gt", "detector"], default="gt")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tolerance", type=float, default=10.0, help="pixels of slack around the marked nucleus box")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()
    data = json.loads((HERE / "derived" / "v1" / f"{args.split}.json").read_text())
    boxes = {}
    for a in data["annotations"]:
        x, y, w, h = a["bbox"]
        boxes.setdefault(a["image_id"], []).append((x, y, x + w, y + h))
    if args.mode == "detector":
        from app import analysis
    stats = dict(points=0, unmatched=0, found=0, hits=0, distances=[], seconds=0.0, ratios=[])
    backgrounds = {}
    for info in data["images"][: args.limit]:
        image = Image.open(HERE / info["file_name"]).convert("RGB")
        backgrounds[info["id"]] = nuclei.slide_background(image)
        if args.mode == "gt":
            candidates = [(b, None) for b in boxes.get(info["id"], [])]
        else:
            res = analysis.detect_cytology(str(HERE / info["file_name"]))
            W, H = res["image_width"], res["image_height"]
            candidates = [((c["x"] * W, c["y"] * H, (c["x"] + c["width"]) * W, (c["y"] + c["height"]) * H), c.get("nucleus"))
                          for c in res["candidates"] if c["score"] >= 0.5]
        for px, py, _label in points_for(info["file_name"]):
            stats["points"] += 1
            containing = [(b, n) for b, n in candidates if b[0] <= px <= b[2] and b[1] <= py <= b[3]]
            if not containing:
                stats["unmatched"] += 1
                continue
            box, precomputed = min(containing, key=lambda bn: (bn[0][2] - bn[0][0]) * (bn[0][3] - bn[0][1]))
            if args.mode == "gt":
                t = time.time(); mark = nuclei.mark_nucleus(image, box, backgrounds[info["id"]]); stats["seconds"] += time.time() - t
            else:
                mark = None
                if precomputed:
                    W, H = image.size
                    mark = dict(cx=precomputed["cx"] * W, cy=precomputed["cy"] * H, x=precomputed["x"] * W, y=precomputed["y"] * H,
                                width=precomputed["width"] * W, height=precomputed["height"] * H)
            ok, dist = hit(mark, px, py, args.tolerance)
            stats["found"] += mark is not None
            stats["hits"] += ok
            if dist is not None:
                stats["distances"].append(dist)
            if mark is not None and mark.get("nc_ratio") is not None:
                stats["ratios"].append(mark["nc_ratio"])
    matched = stats["points"] - stats["unmatched"]
    d = stats["distances"]
    report = dict(split=args.split, mode=args.mode, images=len(data["images"][: args.limit]), nucleus_points=stats["points"],
                  points_inside_a_cell_box=matched, nucleus_marked=stats["found"], marked_nucleus_contains_point=stats["hits"],
                  marked_rate=round(stats["found"] / max(matched, 1), 3), hit_rate=round(stats["hits"] / max(matched, 1), 3),
                  hit_given_marked=round(stats["hits"] / max(stats["found"], 1), 3),
                  median_centre_distance_px=round(statistics.median(d), 1) if d else None,
                  p90_centre_distance_px=round(sorted(d)[int(0.9 * len(d))], 1) if d else None,
                  nc_ratio_median=round(statistics.median(stats["ratios"]), 3) if stats["ratios"] else None,
                  tolerance_px=args.tolerance, seconds_per_cell=round(stats["seconds"] / max(matched, 1), 4) if args.mode == "gt" else None,
                  note="Checks nucleus location against centre points only. Nucleus area and N:C ratio are not validated.")
    print(json.dumps(report, indent=2))
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
