"""Package a small, split-preserving public dataset for Pi CPU training."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BASE = "Warirak_Pi_Training"
QUOTAS = {"train": (42, 42, 12), "val": (10, 10, 4), "test": (6, 6, 4)}


def select_images(images):
    rows = []
    groups = {}
    for split, quotas in QUOTAS.items():
        used = set()
        per_group = Counter()
        ranked = sorted(
            (item for item in images if item["split"] == split),
            key=lambda item: hashlib.sha256(f"pi-cpu-v1:{item['id']}".encode()).hexdigest(),
        )
        # Caps are concentrated in two groups per held-out split.
        group_limit = 1 if split == "train" else 5
        for kind in (1, 2, 0):
            selected = 0
            for item in ranked:
                group = item["session_id"]
                class_ids = {box["class_id"] for box in item["boxes"]}
                fits = (not class_ids) if kind == 2 else (kind in class_ids)
                if (not fits or item["id"] in used or per_group[group] >= group_limit
                        or groups.get(group, split) != split):
                    continue
                groups[group] = split
                per_group[group] += 1
                used.add(item["id"])
                rows.append(item)
                selected += 1
                if selected == quotas[kind]:
                    break
            if selected != quotas[kind]:
                if kind != 2 or selected == 0:
                    raise ValueError(f"Insufficient distinct groups in {split} for category {kind}")
    return rows, groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "output" / (BASE + ".zip"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "ai"))
    from warirak_ai.dataset import digest, safe_path, validate

    source = args.data.resolve()
    original = json.loads((source / "manifest.json").read_text(encoding="utf-8-sig"))
    rows, groups = select_images(original["images"])
    manifest = {**original, "images": rows, "group_splits": groups}
    manifest["provenance"] = {**original["provenance"], "pi_subset": {
        "selection": "deterministic pi-cpu-v1 rank; original splits; up to one training and five held-out images per capture group",
        "parent_manifest_sha256": digest(source / "manifest.json"),
        "counts": dict(Counter(item["split"] for item in rows)),
        "validation_previously_exposed": True, "test_used": False,
    }}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    files = {
        "train_detector.py": ROOT / "hardware/pi/train_detector.py",
        "README_TH.md": ROOT / "hardware/pi/TRAIN_DETECTOR_TH.md",
        "LICENSE": ROOT / "LICENSE",
        "MODEL_CARD_PUBLIC_V4_TH.md": ROOT / "frontend/assets/models/MODEL_CARD_PUBLIC_V4_TH.md",
        "weights/public-v4.pt": ROOT / "frontend/assets/models/warirak-yolo26n-public-v4.pt",
        "dataset/data.yaml": source / "data.yaml",
    }
    for name in ("__init__.py", "dataset.py", "evaluate.py", "calibration.py"):
        files["warirak_ai/" + name] = ROOT / "ai/warirak_ai" / name
    with TemporaryDirectory(dir=args.out.parent, prefix="pi-train-") as temporary:
        staged = Path(temporary) / args.out.name
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            for target, path in files.items():
                archive.write(path, BASE + "/" + target)
            for item in rows:
                image = safe_path(source, item["file"])
                label = f"labels/{item['split']}/{image.stem}.txt"
                archive.write(image, BASE + "/dataset/" + item["file"])
                archive.write(safe_path(source, label), BASE + "/dataset/" + label)
            archive.writestr(BASE + "/dataset/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(staged) as archive:
            archive.extractall(temporary)
        report = validate(Path(temporary) / BASE / "dataset")
        if not report["valid"]:
            raise ValueError("\n".join(report["errors"][:10]))
        staged.replace(args.out)
    print(json.dumps(report, indent=2))
    print(args.out, args.out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
