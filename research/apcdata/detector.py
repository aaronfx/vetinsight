"""Faster R-CNN (MobileNetV3-FPN, COCO-pretrained) cell detector for APCData. CPU friendly.

Commands: train, evaluate. Metrics use pycocotools. Two views are reported:
  * per-class AP50 over the six Bethesda classes (detection + classification), and
  * class-agnostic "cell of interest" AP50 (detection only) after class-agnostic NMS.
"""
import argparse, hashlib, json, os, pathlib, platform, random, time
HERE = pathlib.Path(__file__).resolve().parent
os.environ.setdefault("TORCH_HOME", str(HERE.parent / "phem" / "runs" / "model-cache"))  # reuse cached COCO weights
import numpy as np
import torch, torchvision
from PIL import Image
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval
from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn, FasterRCNN_MobileNet_V3_Large_FPN_Weights
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.ops import nms
from torchvision.transforms.functional import pil_to_tensor

CLASSES = ["NILM", "ASC-US", "ASC-H", "LSIL", "HSIL", "SCC"]


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def build_model(min_size=800, max_size=1066, pretrained=True):
    weights = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1 if pretrained else None
    m = fasterrcnn_mobilenet_v3_large_fpn(weights=weights, min_size=min_size, max_size=max_size,
                                          box_score_thresh=0.05, box_detections_per_img=100)
    m.roi_heads.box_predictor = FastRCNNPredictor(m.roi_heads.box_predictor.cls_score.in_features, len(CLASSES) + 1)
    return m


class CocoDetection(torch.utils.data.Dataset):
    def __init__(self, json_path, train=False):
        self.root = HERE
        self.data = json.loads(pathlib.Path(json_path).read_text())
        self.images = self.data["images"]
        self.by_image = {}
        for a in self.data["annotations"]:
            self.by_image.setdefault(a["image_id"], []).append(a)
        self.train = train

    def __len__(self):
        return len(self.images)

    def __getitem__(self, i):
        info = self.images[i]
        img = Image.open(self.root / info["file_name"]).convert("RGB")
        anns = self.by_image.get(info["id"], [])
        boxes = torch.tensor([[a["bbox"][0], a["bbox"][1], a["bbox"][0] + a["bbox"][2], a["bbox"][1] + a["bbox"][3]] for a in anns], dtype=torch.float32).reshape(-1, 4)
        labels = torch.tensor([a["category_id"] for a in anns], dtype=torch.int64)
        x = pil_to_tensor(img).float() / 255
        if self.train:
            w = x.shape[2]; h = x.shape[1]
            if random.random() < 0.5:
                x = x.flip(2); boxes[:, [0, 2]] = w - boxes[:, [2, 0]]
            if random.random() < 0.5:
                x = x.flip(1); boxes[:, [1, 3]] = h - boxes[:, [3, 1]]
            x = ((x - 0.5) * random.uniform(0.85, 1.15) + 0.5 + random.uniform(-0.06, 0.06)).clamp(0, 1)
        return x, dict(boxes=boxes, labels=labels, image_id=info["id"])


def collate(batch):
    return tuple(zip(*batch))


@torch.inference_mode()
def predict_dataset(model, dataset, limit=None):
    model.eval()
    results = []
    n = len(dataset) if limit is None else min(limit, len(dataset))
    for i in range(n):
        x, t = dataset[i]
        out = model([x])[0]
        results.append((t["image_id"], out["boxes"].cpu(), out["scores"].cpu(), out["labels"].cpu()))
    return results


def to_coco(results, agnostic):
    det = []
    for image_id, boxes, scores, labels in results:
        if agnostic and len(boxes):
            keep = nms(boxes, scores, 0.5)
            boxes, scores, labels = boxes[keep], scores[keep], labels[keep]
        for b, s, l in zip(boxes.tolist(), scores.tolist(), labels.tolist()):
            det.append(dict(image_id=image_id, category_id=1 if agnostic else l, bbox=[b[0], b[1], b[2] - b[0], b[3] - b[1]], score=s))
    return det


def coco_eval(gt_path, det, agnostic, image_ids):
    gt = COCO(str(gt_path))
    if agnostic:
        for a in gt.dataset["annotations"]:
            a["category_id"] = 1
        gt.dataset["categories"] = [dict(id=1, name="cell")]
        gt.createIndex()
    if not det:
        return dict(AP50=0.0, AP50_95=0.0, AR100=0.0, per_class={})
    dt = gt.loadRes(det)
    ev = COCOeval(gt, dt, "bbox")
    ev.params.imgIds = image_ids
    ev.evaluate(); ev.accumulate(); ev.summarize()
    s = ev.stats
    per = {}
    if not agnostic:
        prec = ev.eval["precision"]  # T x R x K x A x M
        for k, cid in enumerate(ev.params.catIds):
            p = prec[0, :, k, 0, 2]
            n = len(gt.getAnnIds(catIds=[cid], imgIds=image_ids))
            per[CLASSES[cid - 1]] = dict(AP50=float(p[p > -1].mean()) if (p > -1).any() else None, test_boxes=n)
    return dict(AP50=float(s[1]), AP50_95=float(s[0]), AR100=float(s[8]), per_class=per)


def evaluate_model(model, gt_path, limit=None):
    ds = CocoDetection(gt_path)
    res = predict_dataset(model, ds, limit)
    ids = [r[0] for r in res]
    return dict(classification=coco_eval(gt_path, to_coco(res, False), False, ids),
                cell_detection=coco_eval(gt_path, to_coco(res, True), True, ids), images=len(ids))


def train(args):
    torch.set_num_threads(args.threads)
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    data = pathlib.Path(args.data)
    out = pathlib.Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; use a new run directory")
    out.mkdir(parents=True)
    train_ds = CocoDetection(data / "train.json", train=True)
    if args.limit:
        train_ds.images = train_ds.images[:args.limit]
    loader = torch.utils.data.DataLoader(train_ds, batch_size=args.batch, shuffle=True, collate_fn=collate)
    model = build_model(args.min_size, args.max_size)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.SGD(params, lr=args.lr, momentum=0.9, weight_decay=5e-4)
    total = args.epochs * len(loader)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda it: min(1.0, (it + 1) / 50) * 0.5 * (1 + np.cos(np.pi * it / total)))
    weights_file = next((pathlib.Path(os.environ["TORCH_HOME"]) / "checkpoints").glob("fasterrcnn_mobilenet_v3_large_fpn-*.pth"))
    run = dict(args=vars(args), torch=torch.__version__, torchvision=torchvision.__version__, python=platform.python_version(),
               init_weights=weights_file.name, init_sha256=sha256(weights_file),
               dataset={s: sha256(data / f"{s}.json") for s in ("train", "validation", "test")}, categories=CLASSES)
    (out / "run.json").write_text(json.dumps(run, indent=2))
    history, best = [], -1.0
    for epoch in range(1, args.epochs + 1):
        model.train(); t0 = time.time(); running = 0.0
        for it, (xs, ts) in enumerate(loader):
            ts = [{k: v for k, v in t.items() if k != "image_id"} for t in ts]
            loss = sum(model(list(xs), ts).values())
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_(params, 10.0); opt.step(); sched.step()
            running += float(loss)
            if it % 20 == 0:
                print(f"epoch {epoch} it {it}/{len(loader)} loss {float(loss):.3f} {time.time()-t0:.0f}s", flush=True)
        metrics = evaluate_model(model, data / "validation.json", args.limit_eval)
        score = metrics["cell_detection"]["AP50"]
        history.append(dict(epoch=epoch, train_loss=running / len(loader), val_cell_AP50=score,
                            val_class_AP50={k: v["AP50"] for k, v in metrics["classification"]["per_class"].items()}, seconds=round(time.time() - t0)))
        (out / "history.json").write_text(json.dumps(history, indent=2))
        torch.save(model.state_dict(), out / "last.pt")
        if score > best:
            best = score; torch.save(model.state_dict(), out / "best.pt")
            (out / "best-epoch.json").write_text(json.dumps(dict(epoch=epoch, validation=metrics), indent=2))
        print(f"== epoch {epoch} val cell AP50 {score:.4f} (best {best:.4f}) {time.time()-t0:.0f}s", flush=True)


def evaluate(args):
    torch.set_num_threads(args.threads)
    model = build_model(args.min_size, args.max_size, pretrained=False)
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=True))
    metrics = evaluate_model(model, pathlib.Path(args.data) / f"{args.split}.json", args.limit_eval)
    metrics.update(split=args.split, checkpoint_sha256=sha256(args.checkpoint),
                   dataset_sha256=sha256(pathlib.Path(args.data) / f"{args.split}.json"))
    pathlib.Path(args.output).write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("train", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--data", default=str(HERE / "derived" / "v1"))
        p.add_argument("--threads", type=int, default=10)
        p.add_argument("--min-size", type=int, default=800)
        p.add_argument("--max-size", type=int, default=1066)
        p.add_argument("--limit-eval", type=int, default=None)
    t = sub.choices["train"]
    t.add_argument("--out", required=True); t.add_argument("--epochs", type=int, default=15)
    t.add_argument("--batch", type=int, default=2); t.add_argument("--lr", type=float, default=0.01)
    t.add_argument("--seed", type=int, default=42); t.add_argument("--limit", type=int, default=None)
    e = sub.choices["evaluate"]
    e.add_argument("--checkpoint", required=True); e.add_argument("--split", default="test", choices=["validation", "test"])
    e.add_argument("--output", required=True)
    args = ap.parse_args()
    train(args) if args.cmd == "train" else evaluate(args)


if __name__ == "__main__":
    main()
