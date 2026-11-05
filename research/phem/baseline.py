"""Offline Faster R-CNN baseline. Synthetic QA never establishes veterinary accuracy."""
import argparse
import json
import math
from pathlib import Path
import platform
import random
import time
from urllib.parse import urlsplit

import torch
import torchvision
from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn, FasterRCNN_MobileNet_V3_Large_FPN_Weights
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor

from baseline_data import CATEGORIES, CocoDataset, generate, read_dataset, validate_splits
from evaluate import metrics
from pipeline import ROOT, digest, write_json
from readiness import check

MARKER = 'SYNTHETIC_SOFTWARE_CHECK_NOT_VETERINARY_PERFORMANCE'


def config(path):
    value = json.loads(Path(path).read_text())
    expected = {'seed', 'epochs', 'batch_size', 'learning_rate', 'weight_decay', 'min_size', 'max_size',
                'freeze_backbone', 'pretrained', 'device', 'threads', 'proposal_limit'}
    if set(value) != expected:
        raise ValueError('Configuration has missing or unsupported fields.')
    for key in ('seed', 'epochs', 'batch_size', 'min_size', 'max_size', 'threads', 'proposal_limit'):
        if type(value[key]) is not int or value[key] < (0 if key == 'seed' else 1):
            raise ValueError('Invalid integer setting: ' + key)
    for key in ('learning_rate', 'weight_decay'):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or value[key] < 0:
            raise ValueError('Invalid numeric setting: ' + key)
    if value['learning_rate'] == 0 or value['min_size'] > value['max_size'] or value['device'] not in ('cpu', 'cuda'):
        raise ValueError('Invalid learning rate, image size or device.')
    if any(type(value[key]) is not bool for key in ('freeze_backbone', 'pretrained')):
        raise ValueError('Pretrained/freeze flags must be booleans.')
    return value


def seed_all(value, threads):
    random.seed(value)
    torch.manual_seed(value)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)


def build_model(settings, initialize=False, num_classes=6, anchor_sizes=None):
    torch.hub.set_dir(str(ROOT / 'runs/model-cache'))
    weights = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1 if initialize and settings['pretrained'] else None
    model = fasterrcnn_mobilenet_v3_large_fpn(weights=weights, weights_backbone=None,
        min_size=settings['min_size'], max_size=settings['max_size'],
        rpn_pre_nms_top_n_train=settings['proposal_limit'], rpn_pre_nms_top_n_test=settings['proposal_limit'],
        rpn_post_nms_top_n_train=settings['proposal_limit'], rpn_post_nms_top_n_test=settings['proposal_limit'],
        box_detections_per_img=100, box_score_thresh=0.0,
        rpn_score_thresh=settings.get('rpn_score_thresh', 0.05))
    if settings['pretrained'] and not initialize:
        # Torchvision chooses FrozenBatchNorm for pretrained backbones. Restore
        # that architecture without downloading initialization weights at inference.
        from torchvision.ops.misc import FrozenBatchNorm2d
        def frozen_norms(module):
            for name, child in list(module.named_children()):
                if isinstance(child, torch.nn.BatchNorm2d):
                    setattr(module, name, FrozenBatchNorm2d(child.num_features))
                else:
                    frozen_norms(child)
        frozen_norms(model.backbone)
    features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(features, num_classes)
    if anchor_sizes is not None:
        from torchvision.models.detection.anchor_utils import AnchorGenerator
        levels = len(model.rpn.anchor_generator.sizes)
        ratios = model.rpn.anchor_generator.aspect_ratios
        if len(anchor_sizes) != len(model.rpn.anchor_generator.sizes[0]) or any(type(size) is not int or size <= 0 for size in anchor_sizes):
            raise ValueError('Custom scales must preserve the pretrained RPN anchor count.')
        model.rpn.anchor_generator = AnchorGenerator(tuple(tuple(anchor_sizes) for _ in range(levels)), ratios)
    if settings['freeze_backbone']:
        for parameter in model.backbone.parameters():
            parameter.requires_grad = False
    return model


def infer(model, dataset, device):
    model.eval()
    predictions = []
    with torch.inference_mode():
        for image, target in dataset:
            result = model([image.to(device)])[0]
            for box, label, score in zip(result['boxes'].cpu().tolist(), result['labels'].cpu().tolist(), result['scores'].cpu().tolist()):
                x1, y1, x2, y2 = box
                if x2 > x1 and y2 > y1:
                    predictions.append({'image_id': int(target['image_id']), 'category_id': label,
                                        'bbox': [x1, y1, x2 - x1, y2 - y1], 'score': score})
    return predictions


def train(paths, settings, output, software_check=False, review=None, groups=None):
    data = validate_splits(paths, software_check, review, groups)
    if not software_check and not settings['pretrained']:
        raise ValueError('This research baseline requires declared COCO-pretrained initialization.')
    output = Path(output)
    if output.exists():
        raise ValueError('Run directory already exists; use a new immutable run directory.')
    if settings['device'] == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA requested but unavailable.')
    output.mkdir(parents=True)
    seed_all(settings['seed'], settings['threads'])
    device = torch.device(settings['device'])
    model = build_model(settings, initialize=True).to(device)
    train_set, validation = CocoDataset(paths['train'], data['train']), CocoDataset(paths['validation'], data['validation'])
    generator = torch.Generator().manual_seed(settings['seed'])
    loader = torch.utils.data.DataLoader(train_set, batch_size=settings['batch_size'], shuffle=True,
        num_workers=0, generator=generator, collate_fn=lambda batch: tuple(zip(*batch)))
    optimizer = torch.optim.SGD([p for p in model.parameters() if p.requires_grad],
                               lr=settings['learning_rate'], momentum=.9, weight_decay=settings['weight_decay'])
    kind = MARKER if software_check else 'RESEARCH_BASELINE_NOT_CLINICALLY_VALIDATED'
    provenance = {'kind': kind, 'architecture': 'fasterrcnn_mobilenet_v3_large_fpn',
                  'initialization': 'COCO_V1' if settings['pretrained'] else 'random (software QA only)',
                  'settings': settings, 'categories': CATEGORIES,
                  'dataset_hashes': {split: digest(path) for split, path in paths.items()},
                  'image_hashes': {split: {item['file_name']: item['sha256'] for item in doc['images']} for split, doc in data.items()},
                  'versions': {'python': platform.python_version(), 'torch': str(torch.__version__), 'torchvision': str(torchvision.__version__)},
                  'model_selection': 'Highest validation AP; ties keep earliest epoch. Test split is not evaluated during training.'}
    provenance['code_sha256'] = {name: digest(ROOT / name) for name in ('baseline.py', 'baseline_data.py', 'evaluate.py', 'readiness.py')}
    if settings['pretrained']:
        weight_url = FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1.url
        weight_file = Path(torch.hub.get_dir()) / 'checkpoints' / Path(urlsplit(weight_url).path).name
        provenance['initial_weights'] = {'url': weight_url, 'sha256': digest(weight_file)}
    write_json(output / 'run.json', provenance)
    initial_head = model.roi_heads.box_predictor.cls_score.weight.detach().cpu().clone()
    history, best, started, steps = [], -1.0, time.monotonic(), 0
    for epoch in range(settings['epochs']):
        model.train()
        if settings['freeze_backbone']:
            model.backbone.eval()
        losses = []
        for images, targets in loader:
            optimizer.zero_grad(set_to_none=True)
            loss_parts = model([image.to(device) for image in images],
                               [{key: value.to(device) for key, value in target.items()} for target in targets])
            loss = sum(loss_parts.values())
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite training loss; run stopped.')
            loss.backward()
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], max_norm=10, error_if_nonfinite=True)
            optimizer.step()
            steps += 1
            losses.append(float(loss.detach()))
        predictions = infer(model, validation, device)
        measured = metrics(data['validation'], predictions)
        ap = measured['metrics']['AP_IoU_050_095']
        if ap is None:
            raise ValueError('Validation data has no evaluable labels.')
        record = {'epoch': epoch + 1, 'mean_training_loss': sum(losses) / len(losses),
                  'validation_AP': ap, 'kind': kind}
        history.append(record)
        checkpoint = {'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                      'epoch': epoch + 1, 'provenance': provenance, 'torch_rng': torch.get_rng_state()}
        torch.save(checkpoint, output / 'last.pt')
        if ap > best:
            best = ap
            torch.save(checkpoint, output / 'best.pt')
        write_json(output / 'history.json', history)
        print(f'{kind}: epoch {epoch + 1}/{settings["epochs"]}, loss={record["mean_training_loss"]:.4f}', flush=True)
    result = {'kind': kind, 'epochs_completed': len(history), 'elapsed_seconds': time.monotonic() - started,
              'best_checkpoint_sha256': digest(output / 'best.pt'), 'test_evaluated': False,
              'optimizer_steps': steps,
              'classifier_weights_changed': not torch.equal(initial_head, model.roi_heads.box_predictor.cls_score.weight.detach().cpu())}
    write_json(output / 'summary.json', result)
    return result


def predict(checkpoint_path, data_path, output):
    if Path(output).exists() or Path(str(output) + '.provenance.json').exists():
        raise ValueError('Prediction output already exists; choose a fresh path.')
    # Read only locally trusted checkpoints. weights_only limits executable payloads.
    checkpoint = torch.load(checkpoint_path, map_location='cpu', weights_only=True)
    settings = checkpoint['provenance']['settings']
    seed_all(settings['seed'], settings['threads'])
    dataset = CocoDataset(data_path)
    synthetic = dataset.data.get('info', {}).get('dataset_kind') == 'SYNTHETIC_GEOMETRY_NOT_CYTOLOGY'
    if (checkpoint['provenance']['kind'] == MARKER) != synthetic:
        raise ValueError('Synthetic checkpoints cannot be applied to real cytology or vice versa.')
    model = build_model(settings)
    model.load_state_dict(checkpoint['model'], strict=True)
    result = infer(model, dataset, torch.device('cpu'))
    write_json(output, result)
    write_json(str(output) + '.provenance.json', {'kind': checkpoint['provenance']['kind'],
        'checkpoint_sha256': digest(checkpoint_path), 'dataset_sha256': digest(data_path),
        'prediction_sha256': digest(output), 'categories': CATEGORIES})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    synthetic = commands.add_parser('synthetic')
    synthetic.add_argument('--output', type=Path, required=True)
    training = commands.add_parser('train')
    training.add_argument('--data', type=Path, required=True, help='Directory with train/validation/test.json')
    training.add_argument('--config', type=Path, required=True)
    training.add_argument('--output', type=Path, required=True)
    training.add_argument('--software-check', action='store_true')
    training.add_argument('--audit', type=Path, default=ROOT / 'reports/annotation-audit.json')
    training.add_argument('--groups', type=Path, default=ROOT / 'patient-groups.csv')
    training.add_argument('--rights', type=Path, default=ROOT / 'rights-review.json')
    inference = commands.add_parser('predict')
    inference.add_argument('--checkpoint', type=Path, required=True)
    inference.add_argument('--data', type=Path, required=True)
    inference.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'synthetic':
        generate(args.output)
        print(MARKER)
    elif args.command == 'train':
        review = None
        if not args.software_check:
            review = check(json.loads(args.audit.read_text()), args.groups, json.loads(args.rights.read_text()))
            if not review['ready_for_experiment']:
                raise ValueError('Real training blocked: obtain image permission and verified patient groups first.')
        train({split: args.data / f'{split}.json' for split in ('train', 'validation', 'test')},
              config(args.config), args.output, args.software_check, review, args.groups)
    else:
        predict(args.checkpoint, args.data, args.output)


if __name__ == '__main__':
    main()
