"""Convert APCData YOLO labels to COCO with smear-grouped train/validation/test splits.

Fields from the same smear share an accession id in the file name (e.g. C314-19). All fields of one
accession are kept in the same split. Files whose id cannot be read get their own group, so ungrouped
files cannot be proven independent; that limitation is recorded in the manifest.
"""
import argparse, collections, hashlib, json, pathlib, random, re
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "extracted" / "APCData cervical cytology cells" / "APCData_YOLO"
CLASSES = ["NILM", "ASC-US", "ASC-H", "LSIL", "HSIL", "SCC"]  # YOLO order in classes.txt
ACCESSION = re.compile(r"([A-Z]{0,2})-?(\d{2,6})-(\d{2})(?=-|_|$)")
RATIOS = {"train": 0.70, "validation": 0.15, "test": 0.15}


def group_of(name):
    body = re.sub(r"_jpg\.rf\.[0-9a-f]+\.jpg$", "", name)
    body = re.sub(r"^\d+-", "", body)
    body = re.sub(r"--\d+-?$", "", body)
    m = ACCESSION.search(body)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}-{m.group(3)}"


def sha256(path):
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "derived" / "v1"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; use a new output directory")
    out.mkdir(parents=True)

    class_file = [l.strip() for l in (SRC / "classes.txt").read_text().splitlines() if l.strip()]
    assert [c.replace("-", "") for c in CLASSES] == [c.replace("-", "") for c in class_file], class_file

    records = []
    for img in sorted((SRC / "images").glob("*.jpg")):
        with Image.open(img) as im:
            width, height = im.size
        boxes = []
        for line in (SRC / "labels" / f"{img.stem}.txt").read_text().splitlines():
            if not line.strip():
                continue
            c, xc, yc, w, h = line.replace(",", " ").split()
            c, xc, yc, w, h = int(c), float(xc), float(yc), float(w), float(h)
            x1, y1 = max(0.0, (xc - w / 2) * width), max(0.0, (yc - h / 2) * height)
            x2, y2 = min(float(width), (xc + w / 2) * width), min(float(height), (yc + h / 2) * height)
            if x2 - x1 >= 2 and y2 - y1 >= 2:
                boxes.append((c, round(x1, 2), round(y1, 2), round(x2 - x1, 2), round(y2 - y1, 2)))
        gid = group_of(img.name)
        records.append(dict(path=img, width=width, height=height, boxes=boxes, group=gid or f"ungrouped:{img.stem[:4]}"))

    groups = collections.defaultdict(list)
    for r in records:
        groups[r["group"]].append(r)
    totals = collections.Counter(b[0] for r in records for b in r["boxes"])
    target = {s: {c: totals[c] * RATIOS[s] for c in totals} for s in RATIOS}
    got = {s: collections.Counter() for s in RATIOS}
    rng = random.Random(args.seed)
    order = list(groups)
    rng.shuffle(order)
    rarity = lambda g: -sum(1.0 / totals[b[0]] for r in groups[g] for b in r["boxes"])
    order.sort(key=rarity)  # place groups rich in rare classes first
    assign = {}
    for g in order:
        gc = collections.Counter(b[0] for r in groups[g] for b in r["boxes"])
        def cost(s):
            return sum(((got[s][c] + n) - target[s][c]) / max(target[s][c], 1) for c, n in gc.items()) + 0.01 * sum(got[s].values()) / max(RATIOS[s], 1e-9) / 1000
        s = min(RATIOS, key=cost)
        assign[g] = s
        got[s].update(gc)

    manifest = dict(source="https://data.mendeley.com/datasets/ytd568rh3p (CC BY 4.0)", seed=args.seed,
                    categories=CLASSES, splits={}, ungrouped_images=sum(1 for r in records if r["group"].startswith("ungrouped")),
                    limitation=("Splits are grouped by smear accession parsed from file names. Images whose id could not be read "
                                "are treated as separate groups and may share a patient with another image. Patient identity is not "
                                "provided by the dataset, so patient-independent evaluation is not claimed."))
    for s in RATIOS:
        images, anns = [], []
        for r in sorted((r for g, rs in groups.items() if assign[g] == s for r in rs), key=lambda r: r["path"].name):
            iid = len(images) + 1
            images.append(dict(id=iid, file_name=str(r["path"].relative_to(HERE)).replace("\\", "/"), width=r["width"], height=r["height"], group=r["group"]))
            for c, x, y, w, h in r["boxes"]:
                anns.append(dict(id=len(anns) + 1, image_id=iid, category_id=c + 1, bbox=[x, y, w, h], area=round(w * h, 2), iscrowd=0))
        coco = dict(images=images, annotations=anns, categories=[dict(id=i + 1, name=n) for i, n in enumerate(CLASSES)])
        path = out / f"{s}.json"
        path.write_text(json.dumps(coco))
        cc = collections.Counter(a["category_id"] for a in anns)
        manifest["splits"][s] = dict(images=len(images), boxes=len(anns), groups=sum(1 for g in groups if assign[g] == s),
                                     boxes_per_class={CLASSES[k - 1]: v for k, v in sorted(cc.items())}, sha256=sha256(path))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
