"""One bounded 640px camera experiment; validation selection, no test access."""
import argparse
import csv
import datetime
import gc
import json
import os
from pathlib import Path
import time

from . import CLASSES
from .dataset import validate, training_yaml, digest
from .train_balanced import atomic_json, promotion_gate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('base', 'data', 'out'):
        p.add_argument('--' + key, required=True, type=Path)
    p.add_argument('--resume', action='store_true')
    a = p.parse_args()
    root = a.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    import psutil
    lock = root / 'training-lock.json'
    if lock.exists():
        old = json.loads(lock.read_text())
        if psutil.pid_exists(old['pid']) and abs(psutil.Process(old['pid']).create_time() - old['created_at_s']) < 1:
            raise RuntimeError('Run is already active')
    status_file = root / 'status.json'
    previous = json.loads(status_file.read_text()) if status_file.exists() else {}
    if previous and not a.resume:
        raise RuntimeError('Existing run; inspect before resuming')
    if previous.get('review_complete') or previous.get('phase') in ('artifacts_ready', 'retained_baseline'):
        raise RuntimeError('Completed run must not be repeated')
    recipe = dict(imgsz=640, batch=8, epochs=6, optimizer='AdamW', lr0=.00008,
                  cls_pw=.5, seed=143, patience=6, cos_lr=True, close_mosaic=2,
                  mosaic=.15, scale=.4, hsv_s=.45, hsv_v=.3, fliplr=.5, flipud=0.,
                  degrees=5., mixup=0., workers=0, cache=False, deterministic=True,
                  save_period=-1, amp=True)
    epoch = previous.get('epoch', 0)
    started = previous.get('started_at_ms', int(time.time() * 1000))
    current = previous.get('failed_phase', previous.get('phase', 'preflight'))
    resume_phase = current
    def state(phase, **fields):
        nonlocal current
        current = phase
        value = dict(phase=phase, run_id=root.name, dataset_id=a.data.name,
                     data=str(a.data.resolve()), pid=os.getpid(), epoch=epoch,
                     total_epochs=6, started_at_ms=started, recipe=recipe,
                     updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), **fields)
        atomic_json(status_file, value)
        print('WARIRAK_STATUS ' + json.dumps(value), flush=True)
    atomic_json(lock, dict(pid=os.getpid(), created_at_s=psutil.Process().create_time()))
    try:
        os.environ['YOLO_CONFIG_DIR'] = str(root / 'runtime-config')
        os.environ['OMP_NUM_THREADS'] = '4'
        os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'
        audit = validate(a.data)
        atomic_json(root / 'dataset-audit.json', audit)
        if not audit['valid']:
            raise ValueError('Dataset integrity audit failed')
        protocol = dict(schema='warirak.camera-training-protocol.v1', frozen_before_training=True,
                        base_weights_sha256=digest(a.base), dataset_manifest_sha256=digest(a.data/'manifest.json'),
                        recipe=recipe, baseline_imgsz=800, candidate_imgsz=640, rect=False,
                        selection_split='val', min_macro_gain=.003, max_class_drop=.02,
                        validation_previously_exposed=True, test_previously_exposed=True,
                        test_used_for_selection=False, test_opened_this_run=False, field_validated=False,
                        hypothesis='Adapt the existing public-data detector to 640px camera inference. Promote only if it also exceeds the current 800px validation baseline; speed is not assumed or used to excuse lost accuracy.',
                        data_sources=['https://github.com/pedropro/TACO',
                                      'https://huggingface.co/datasets/OliviaWuYJ/sc-floatwaste',
                                      'https://huggingface.co/datasets/roboticslaburjc/ExtendedTACO-reviewed'])
        frozen = root / 'protocol.json'
        if frozen.exists() and json.loads(frozen.read_text()) != protocol:
            raise ValueError('Frozen protocol changed')
        atomic_json(frozen, protocol)
        import torch, cv2
        from ultralytics import YOLO, settings
        from .evaluate import model_classes
        from .calibration import choose_thresholds, fixed_precision_recall
        torch.set_num_threads(4)
        cv2.setNumThreads(1)
        settings.update({k: False for k in ['sync','hub','wandb','mlflow','tensorboard','comet','clearml','neptune','raytune'] if k in settings})
        if not torch.cuda.is_available():
            raise RuntimeError('Local CUDA unavailable')
        config = training_yaml(a.data, root/'data.yaml')
        def evaluate(weights, size, name, device=0):
            model = YOLO(str(weights), task='detect')
            if model_classes(model) != CLASSES:
                raise ValueError('Incorrect model classes')
            m = model.val(data=str(config), split='val', imgsz=size, rect=False,
                          batch=4 if device == 0 else 1, device=device, workers=0, plots=False,
                          project=str(root), name=name, exist_ok=True, verbose=False)
            calibration = choose_thresholds(m)
            result = dict(map50=float(m.box.map50), map50_95=float(m.box.map),
                          classes={CLASSES[int(k)]: float(m.box.ap[i]) for i,k in enumerate(m.box.ap_class_index)},
                          calibration=calibration, operating_points=fixed_precision_recall(m, calibration))
            del model, m
            gc.collect()
            torch.cuda.empty_cache()
            return result
        base_file = root/'baseline-validation.json'
        if base_file.exists():
            baseline = json.loads(base_file.read_text())
        else:
            state('baseline_validation')
            baseline = evaluate(a.base, 800, 'baseline-validation')
            atomic_json(base_file, baseline)
        last = root/'refinement/weights/last.pt'
        best = root/'refinement/weights/best.pt'
        if resume_phase not in ('validation_selection', 'ncnn_export', 'ncnn_check'):
            if a.resume and (root/'refinement').exists() and not last.exists():
                raise RuntimeError('Interrupted training has no checkpoint; inspect before restarting')
            model = YOLO(str(last if a.resume and last.exists() else a.base), task='detect')
            def progress(trainer):
                nonlocal epoch
                epoch = min(trainer.epoch + 1, recipe['epochs'])
                state('training', metrics={k: float(v) for k,v in trainer.metrics.items() if isinstance(v,(int,float))})
            model.add_callback('on_fit_epoch_end', progress)
            state('training')
            if a.resume and last.exists():
                model.train(resume=True)
            else:
                model.train(data=str(config), device=0, project=str(root), name='refinement',
                            exist_ok=False, plots=True, verbose=False, **recipe)
            del model
            gc.collect()
            torch.cuda.empty_cache()
        with (root/'refinement/results.csv').open(encoding='utf-8') as history:
            epoch = int(float(list(csv.DictReader(history))[-1]['epoch']))
        state('validation_selection')
        candidate = evaluate(best, 640, 'candidate-validation')
        atomic_json(root/'candidate-validation.json', candidate)
        promoted = promotion_gate(baseline, candidate)
        selection = dict(baseline_map50_95=baseline['map50_95'], candidate_map50_95=candidate['map50_95'],
                         baseline_classes=baseline['classes'], candidate_classes=candidate['classes'],
                         promote=promoted, selection_split='val', test_used_for_selection=False)
        atomic_json(root/'selection.json', selection)
        atomic_json(root/'confidence-calibration.json', candidate['calibration'])
        if not promoted:
            state('retained_baseline', metrics=candidate, reason='Did not pass the frozen validation gate; public-v4 remains deployed')
            return
        state('ncnn_export')
        detector = YOLO(str(best), task='detect')
        exported = Path(detector.export(format='ncnn', imgsz=640, batch=1, device='cpu'))
        del detector
        state('ncnn_check')
        ncnn = evaluate(exported, 640, 'ncnn-validation', 'cpu')
        atomic_json(root/'export-validation.json', ncnn)
        if abs(ncnn['map50_95'] - candidate['map50_95']) > .02:
            raise RuntimeError('NCNN validation parity failed')
        state('artifacts_ready', metrics=candidate, ncnn_path=str(exported), needs_review=True)
    except Exception as error:
        state('needs_repair', failed_phase=current, error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
