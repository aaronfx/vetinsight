"""Package an evaluated APCData detector as a TorchScript file plus integrity metadata for the backend."""
import argparse, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import torch
import detector as d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--evaluation", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--model-id", default="apcdata-frcnn-v1")
    args = ap.parse_args()
    run = pathlib.Path(args.run)
    settings = json.loads((run / "run.json").read_text())["args"]
    ev = json.loads(pathlib.Path(args.evaluation).read_text())
    checkpoint = run / "best.pt"
    if d.sha256(checkpoint) != ev["checkpoint_sha256"]:
        raise SystemExit("Evaluation was not produced from this checkpoint.")
    model = d.build_model(settings["min_size"], settings["max_size"], pretrained=False)
    model.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    model.eval()
    scripted = torch.jit.script(model)
    # The packaged file must reproduce the evaluated eager model on a real held-out image.
    ds = d.CocoDetection(pathlib.Path(run).parents[1] / "derived" / "v1" / "test.json")
    x, _ = ds[0]
    with torch.inference_mode():
        eager = model([x])[0]
        packed = scripted([x])[1][0]
    assert eager["boxes"].shape == packed["boxes"].shape, (eager["boxes"].shape, packed["boxes"].shape)
    assert torch.allclose(eager["boxes"], packed["boxes"], atol=1e-3) and torch.allclose(eager["scores"], packed["scores"], atol=1e-4)
    out = pathlib.Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    scripted.save(str(out / "cytology.pt"))
    c, k = ev["cell_detection"], ev["classification"]["per_class"]
    per = ", ".join(f"{n} {v['AP50']:.2f} (n={v['test_boxes']})" for n, v in k.items())
    limitation = (
        f"Experimental cell detector and Bethesda-class labeller trained on APCData: human cervical Pap smear fields "
        f"(CC BY 4.0), not veterinary data. Held-out test ({ev['images']} images): cell-finding AP50 {c['AP50']:.3f}; "
        f"per-class AP50 {per}. Labels for abnormal classes are unreliable and rare classes (HSIL, SCC) have too few "
        f"test boxes for a meaningful score. Splits are grouped by smear id parsed from file names; patient independence "
        f"is unverified. Scores are uncalibrated. Stain, scale and preparation differences will reduce performance. "
        f"Suggestions require qualified human review and are never diagnoses.")
    meta = dict(id=args.model_id, task="cytology", categories=d.CLASSES, sha256=d.sha256(out / "cytology.pt"),
                checkpoint_sha256=ev["checkpoint_sha256"], dataset_sha256=ev["dataset_sha256"], limitation=limitation,
                evaluation=dict(split=ev["split"], images=ev["images"], cell_detection_AP50=c["AP50"], cell_detection_AP50_95=c["AP50_95"],
                                classification_per_class_AP50={n: v["AP50"] for n, v in k.items()}),
                training=dict(source="https://data.mendeley.com/datasets/ytd568rh3p", licence="CC BY 4.0", settings=settings))
    (out / "cytology.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(dict(sha256=meta["sha256"], bytes=(out / "cytology.pt").stat().st_size), indent=2))


if __name__ == "__main__":
    main()
