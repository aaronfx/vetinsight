"""Run separately from the legacy MIDOG 2022 importer tests."""
import unittest

from experiment import SPLITS, filter_core, checked_review
from baseline import build_model


class ExperimentTests(unittest.TestCase):
    def test_low_objectness_empty_targets_have_finite_losses(self):
        import torch
        from baseline import seed_all
        seed_all(42, 2)
        settings = {'pretrained': False, 'freeze_backbone': True, 'min_size': 128,
                    'max_size': 128, 'proposal_limit': 32, 'rpn_score_thresh': 0.0}
        model = build_model(settings, num_classes=2)
        model.train()
        model.backbone.eval()
        with torch.no_grad():
            model.rpn.head.cls_logits.weight.zero_()
            model.rpn.head.cls_logits.bias.fill_(-30)
        targets = [{'boxes': torch.empty((0, 4)), 'labels': torch.empty(0, dtype=torch.int64)}]
        losses = model([torch.zeros(3, 128, 128)], targets)
        self.assertTrue(all(torch.isfinite(value).item() for value in losses.values()))
        sum(losses.values()).backward()

    def test_context_filter_assigns_predictions_to_core_once(self):
        data = {'images': [{'id': 1, 'valid_core': [32, 32, 448, 448]}]}
        predictions = [{'image_id': 1, 'bbox': [0, 0, 50, 50]},
                       {'image_id': 1, 'bbox': [30, 30, 50, 50]},
                       {'image_id': 1, 'bbox': [470, 470, 30, 30]}]
        self.assertEqual(filter_core(predictions, data), [predictions[1]])

    def test_custom_anchors_preserve_pretrained_head_shapes(self):
        settings = {'pretrained': False, 'freeze_backbone': True, 'min_size': 512,
                    'max_size': 512, 'proposal_limit': 100}
        baseline = build_model(settings, num_classes=2)
        revised = build_model(settings, num_classes=2, anchor_sizes=[16, 24, 32, 48, 64])
        self.assertEqual(baseline.rpn.anchor_generator.num_anchors_per_location(),
                         revised.rpn.anchor_generator.num_anchors_per_location())
        self.assertEqual(revised.rpn.anchor_generator.sizes[0], (16, 24, 32, 48, 64))
        self.assertEqual(revised.roi_heads.box_predictor.cls_score.out_features, 2)
        self.assertEqual({k: tuple(v.shape) for k, v in baseline.state_dict().items()},
                         {k: tuple(v.shape) for k, v in revised.state_dict().items()})

    def test_cohort_is_disjoint_and_excludes_used_pilot_test_cases(self):
        ids = [case for cases in SPLITS.values() for case in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(set(SPLITS['test']) & {251, 252})
        review = checked_review()
        self.assertEqual(review['cases'], SPLITS)


if __name__ == '__main__':
    unittest.main()
