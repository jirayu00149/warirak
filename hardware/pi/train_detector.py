"""Fine-tune Warirak's two-class detector on a Raspberry Pi CPU."""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from datetime import datetime, timezone
from uuid import uuid4


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "dataset")
    parser.add_argument("--weights", type=Path, default=ROOT / "weights/public-v4.pt")
    parser.add_argument("--out", type=Path, default=ROOT / "runs")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch", type=int, choices=(1, 2, 4), default=1)
    parser.add_argument("--check", action="store_true", help="Validate data and model before training")
    args = parser.parse_args()
    if not 1 <= args.epochs <= 20:
        parser.error("--epochs must be 1–20")
    try:
        return train(args)
    except KeyboardInterrupt:
        print("Training interrupted. Check the run directory for saved checkpoints.", file=sys.stderr)
        return 130
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        print(f"Training error: {error}", file=sys.stderr)
        return 1


def train(args):
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")
    os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / "runtime-config"))
    from warirak_ai import CLASSES
    from warirak_ai.dataset import digest, validate
    from warirak_ai.evaluate import model_classes
    import yaml
    import torch
    import cv2
    from ultralytics import YOLO, settings

    if not args.weights.is_file() or args.weights.suffix.lower() != ".pt":
        raise ValueError("A local PyTorch .pt file is required for training")
    report = validate(args.data)
    if not report["valid"]:
        raise ValueError("\n".join(report["errors"][:10]))
    torch.set_num_threads(2)
    cv2.setNumThreads(1)
    settings.update({key: False for key in (
        "sync", "hub", "wandb", "mlflow", "tensorboard", "comet", "clearml", "neptune", "raytune"
    ) if key in settings})
    model = YOLO(str(args.weights.resolve()), task="detect")
    if model_classes(model) != CLASSES:
        raise ValueError("Base weights must detect plastic_bottle and bottle_cap in that order")
    print(f"Data and model OK. Image counts: {report['counts']}. Training device: CPU.", flush=True)
    if args.check:
        return 0

    if sys.platform != "linux":
        raise RuntimeError("Run training on the Raspberry Pi. Use --check on Windows.")
    project = args.out.resolve()
    project.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(project).free < 1024**3:
        raise RuntimeError("At least 1 GiB of free space is needed for the training run")

    import fcntl

    with (project / ".training.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("A training process is already using this run directory") from error
        return fit(model, args, project, CLASSES, report, yaml, digest, YOLO)


def fit(model, args, project, classes, report, yaml, digest, yolo):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = project / (stamp + "-" + uuid4().hex[:6])
    run.mkdir()
    config = run / "data.yaml"
    config.write_text(yaml.safe_dump({
        "path": str(args.data.resolve()), "train": "images/train", "val": "images/val",
        "names": dict(enumerate(classes)),
    }), encoding="utf-8")
    options = dict(data=str(config), imgsz=320, batch=args.batch, device="cpu", workers=0,
                   rect=False, plots=False, verbose=False)
    training = dict(epochs=args.epochs, seed=42, deterministic=True, cache=False, amp=False,
                    optimizer="AdamW", lr0=0.00008, warmup_epochs=0, mosaic=0,
                    close_mosaic=0, flipud=0, exist_ok=False)
    (run / "protocol.json").write_text(json.dumps({
        "dataset_manifest_sha256": digest(args.data / "manifest.json"),
        "base_weights_sha256": digest(args.weights),
        "counts": report["counts"], "options": options, "training": training,
        "validation_previously_exposed": True, "test_used": False, "field_validated": False,
    }, indent=2), encoding="utf-8")
    print("Run directory:", run, flush=True)
    baseline = model.val(split="val", project=str(run), name="baseline", **options)
    model.train(project=str(run), name="fine-tune", **options, **training)
    best = Path(model.trainer.best)
    if not best.is_file():
        raise RuntimeError("Training ended without best.pt")
    candidate = yolo(str(best), task="detect")
    measured = candidate.val(split="val", project=str(run), name="candidate", **options)
    comparison = {
        "metric": "mAP50-95",
        "split": "previously used public validation subset",
        "base": float(baseline.box.map),
        "candidate": float(measured.box.map),
        "base_by_class": {classes[int(i)]: float(ap)
                          for i, ap in zip(baseline.box.ap_class_index, baseline.box.ap)},
        "candidate_by_class": {classes[int(i)]: float(ap)
                               for i, ap in zip(measured.box.ap_class_index, measured.box.ap)},
        "candidate_weights": str(best),
    }
    (run / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    print(json.dumps(comparison, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
