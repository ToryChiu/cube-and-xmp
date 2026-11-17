import unittest

import numpy as np
import torch

from photo_edit import HUES, fit_photo, render_photo


class PhotoEditTests(unittest.TestCase):
    def setUp(self):
        self.source = np.array([[[.85, .2, .12], [.2, .5, .8], [.5, .5, .5]]], dtype=np.float32)
        self.residual = torch.full((3, 2, 2, 2), .1)

    def test_strength_zero_keeps_original_but_preserves_manual_adjustments(self):
        untouched = np.asarray(render_photo(self.source, self.residual, {"strength": 0}))
        expected = np.rint(self.source * 255).astype(np.uint8)
        np.testing.assert_array_equal(untouched, expected)
        adjusted = np.asarray(render_photo(self.source, self.residual, {"strength": 0, "exposure": 1}))
        self.assertTrue(np.all(adjusted > expected))

    def test_full_strength_uses_reference_fit(self):
        reference = np.ones_like(self.source) * [.85, .6, .3]
        fitted = fit_photo(self.source, reference.astype(np.float32))
        self.assertNotEqual(float(fitted.abs().max()), 0)
        original = np.asarray(render_photo(self.source, fitted, {"strength": 0}))
        matched = np.asarray(render_photo(self.source, fitted, {"strength": 100}))
        self.assertFalse(np.array_equal(original, matched))

    def test_red_hsl_does_not_change_blue_or_neutral(self):
        edits = [[0, 0, 0] for _ in HUES]
        edits[0] = [40, 0, 0]
        original = np.asarray(render_photo(self.source, None, {"strength": 0}))
        output = np.asarray(render_photo(self.source, None, {"strength": 0, "hsl": edits}))
        self.assertFalse(np.array_equal(original[0, 0], output[0, 0]))
        np.testing.assert_array_equal(original[0, 1:], output[0, 1:])
