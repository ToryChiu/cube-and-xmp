import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import torch

from adobe_export import CRS, RDF, srgb_match_residual, write_adobe_bundle


class AdobeExportTests(unittest.TestCase):
    def test_package_keeps_manual_fields_and_uses_a_separate_srgb_cube(self):
        controls = {"strength": 70, "exposure": .4, "sharpen": 20,
                    "hsl": [[0, 0, 0]] * 5 + [[20, -60, 5]] + [[0, 0, 0]] * 2}
        residual = torch.full((3, 2, 2, 2), .1)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "adobe.zip"
            write_adobe_bundle(path, residual, controls)
            with ZipFile(path) as bundle:
                xmp = next(name for name in bundle.namelist() if name.endswith(".xmp"))
                metadata = ET.fromstring(bundle.read(xmp)).find(f".//{{{RDF}}}Description")
                self.assertEqual(metadata.get(f"{{{CRS}}}Exposure2012"), "+0.40")
                self.assertEqual(metadata.get(f"{{{CRS}}}SaturationAdjustmentBlue"), "-60")
                self.assertEqual(metadata.get(f"{{{CRS}}}Sharpness"), "20")
                cube = next(name for name in bundle.namelist() if name.endswith(".cube"))
                content = bundle.read(cube).decode().splitlines()
                self.assertIn("LUT_3D_SIZE 33", content)
                self.assertIn("# Input and output: sRGB.", content)
                self.assertEqual(sum(line[:1].isdigit() for line in content), 33 ** 3)

    def test_disabled_look_yields_identity_lut(self):
        residual = torch.full((3, 2, 2, 2), .1)
        self.assertEqual(float(srgb_match_residual(residual, 0).abs().max()), 0)
        self.assertGreater(float(srgb_match_residual(residual, 1).abs().max()), .01)
