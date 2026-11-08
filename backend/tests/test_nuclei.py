import unittest

from PIL import Image, ImageDraw

from app import nuclei


def drawn_cell(cell_radius=100, nucleus_radius=20, centre=(300, 260)):
    image = Image.new('RGB', (600, 520), (206, 219, 225))
    draw = ImageDraw.Draw(image)
    cx, cy = centre
    draw.ellipse([cx - cell_radius, cy - cell_radius, cx + cell_radius, cy + cell_radius], fill=(236, 201, 172))
    draw.ellipse([cx - nucleus_radius, cy - nucleus_radius, cx + nucleus_radius, cy + nucleus_radius], fill=(80, 55, 95))
    return image, (cx - cell_radius, cy - cell_radius, cx + cell_radius, cy + cell_radius)


class NucleiTests(unittest.TestCase):
    def test_marks_nucleus_position_and_ratio_on_a_drawn_cell(self):
        image, box = drawn_cell()
        mark = nuclei.mark_nucleus(image, box)
        self.assertIsNotNone(mark)
        self.assertLess(abs(mark['cx'] - 300), 4)
        self.assertLess(abs(mark['cy'] - 260), 4)
        true_ratio = 20 ** 2 / (100 ** 2 - 20 ** 2)  # nucleus area / cytoplasm area
        self.assertIsNotNone(mark['nc_ratio'])
        self.assertAlmostEqual(mark['nc_ratio'], true_ratio, delta=true_ratio * 0.5)

    def test_larger_nucleus_gives_larger_ratio(self):
        small = nuclei.mark_nucleus(*drawn_cell(nucleus_radius=15))
        large = nuclei.mark_nucleus(*drawn_cell(nucleus_radius=40))
        self.assertGreater(large['nc_ratio'], small['nc_ratio'])

    def test_returns_none_when_there_is_no_nucleus_or_the_box_is_tiny(self):
        blank = Image.new('RGB', (300, 300), (206, 219, 225))
        self.assertIsNone(nuclei.mark_nucleus(blank, (50, 50, 250, 250)))
        image, _ = drawn_cell()
        self.assertIsNone(nuclei.mark_nucleus(image, (10, 10, 20, 20)))

    def test_box_is_clipped_to_the_image(self):
        image, box = drawn_cell(centre=(100, 100))
        mark = nuclei.mark_nucleus(image, box)  # box extends past the top-left corner
        self.assertTrue(mark is None or (0 <= mark['cx'] <= 600 and 0 <= mark['cy'] <= 520))


if __name__ == '__main__':
    unittest.main()
