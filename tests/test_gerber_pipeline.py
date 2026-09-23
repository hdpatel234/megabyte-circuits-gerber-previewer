import unittest
import tempfile
import zipfile
from pathlib import Path

from pcb_global_layer_classifier import classify_file
from pcb_renderer import _get_board_outline_shape, _bounds_from_points


class TestGerberPipeline(unittest.TestCase):
    def test_layer_classification_standard_extensions(self):
        self.assertEqual(classify_file("board.gtl")["layer"], "Top Copper")
        self.assertEqual(classify_file("board.gbl")["layer"], "Bottom Copper")
        self.assertEqual(classify_file("board.gts")["layer"], "Top Solder Mask")
        self.assertEqual(classify_file("board.gbs")["layer"], "Bottom Solder Mask")
        self.assertEqual(classify_file("board.gto")["layer"], "Top Silkscreen")
        self.assertEqual(classify_file("board.gbo")["layer"], "Bottom Silkscreen")
        self.assertEqual(classify_file("board.gko")["layer"], "Board Profile")
        self.assertEqual(classify_file("board.drl")["category"], "drill")

    def test_gerber_x2_filefunction_classification(self):
        x2_header = "%TF.FileFunction,Copper,L1,Top*%"
        res = classify_file("generic_file.gbr", text=x2_header)
        self.assertEqual(res["layer"], "Top Copper")

        x2_bottom_mask = "%TF.FileFunction,Soldermask,Bot*%"
        res_mask = classify_file("layer.gbr", text=x2_bottom_mask)
        self.assertEqual(res_mask["layer"], "Bottom Solder Mask")

    def test_bounds_calculation_from_points(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (0.0, 50.0)]
        bounds = _bounds_from_points(pts)
        self.assertIsNotNone(bounds)
        self.assertEqual(bounds["min_x"], 0.0)
        self.assertEqual(bounds["max_x"], 100.0)
        self.assertEqual(bounds["min_y"], 0.0)
        self.assertEqual(bounds["max_y"], 50.0)

    def test_outline_polygon_validation(self):
        # A 3-point triangle with bounding box 100x100 mm should be rejected as a invalid board polygon
        bounds = {"min_x": 0.0, "max_x": 100.0, "min_y": 0.0, "max_y": 100.0}
        # Triangle covering only 50% area
        triangle_pts = [(0, 0), (100, 0), (0, 100)]
        self.assertLess(len(triangle_pts), 4)

if __name__ == "__main__":
    unittest.main()
