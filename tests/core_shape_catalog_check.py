"""Mechanical reference coverage, provenance and dimension semantics."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core_shape_catalog import get_core_shape, list_core_shapes, catalog_metadata
from magnetics import CORE_SHAPES


class CoreShapeCatalogCheck(unittest.TestCase):
    def test_covers_each_builtin_exactly_once(self):
        expected = {name for family in CORE_SHAPES.values() for name in family}
        records = list_core_shapes()
        self.assertEqual(len(records), len(expected))
        self.assertEqual({r['model'] for r in records}, expected)
        for r in records:
            self.assertEqual(r['family'], next(f for f, values in CORE_SHAPES.items() if r['model'] in values))
            self.assertTrue(r['dimension_mapping'])
            self.assertTrue(r['reference_model'])
            self.assertTrue(r['notes'])
            self.assertNotIn('Ae', r['dimensions_mm'])
            self.assertNotIn('Ve', r['dimensions_mm'])
            if r['status'] != 'designation_nominal':
                self.assertTrue(r['source_url'].startswith('https://'), r['model'])
                self.assertTrue(r['source_page'])

    def test_windows_and_posts_are_physically_ordered(self):
        for r in list_core_shapes():
            d = r['dimensions_mm']
            with self.subTest(model=r['model']):
                self.assertGreater(d['width'], 0)
                self.assertGreater(d['depth'], 0)
                if r['template'] == 'toroid':
                    self.assertGreater(d['outer_diameter'], d['inner_diameter'])
                    self.assertGreater(d['inner_diameter'], 0)
                    self.assertGreater(d['height'], 0)
                else:
                    self.assertGreater(d['half_height'], d['window_height'])
                    self.assertGreater(d['window_height'], 0)
                    self.assertGreater(d['width'], d['window_outer_width'])
                    if r['template'] != 'u':
                        self.assertGreater(d['window_outer_width'], d['center_width'])
                    self.assertGreaterEqual(d['depth'], d['center_depth'])
                    if 'hole_diameter' in d:
                        self.assertLess(d['hole_diameter'], d['center_diameter'])

    def test_full_vs_half_height_and_mixed_reference_sources(self):
        pq = get_core_shape('PQ32-30')['dimensions_mm']
        self.assertAlmostEqual(pq['half_height'] * 2, 30.35)
        self.assertAlmostEqual(pq['window_height'] * 2, 21.3)
        self.assertAlmostEqual(pq['center_diameter'], 13.45)
        ei = get_core_shape('EI25')['dimensions_mm']
        self.assertAlmostEqual(ei['half_height'] + ei['i_height'], 18.25)
        self.assertAlmostEqual(ei['window_height'], 12.35)
        self.assertAlmostEqual(get_core_shape('EFD15')['dimensions_mm']['center_depth'], 2.4)
        self.assertAlmostEqual(get_core_shape('EFD30')['dimensions_mm']['center_depth'], 4.9)
        self.assertAlmostEqual(get_core_shape('PQ32-25')['dimensions_mm']['width'], 32)
        self.assertEqual(get_core_shape('PQ32-25')['manufacturer'], 'DMEGC 东磁')
        self.assertEqual(get_core_shape('ER28')['reference_model'], 'PC47EER28-Z')
        self.assertEqual(get_core_shape('PT22')['status'], 'reference_variant')
        self.assertEqual(get_core_shape('T58x37x20')['status'], 'designation_nominal')

    def test_copy_isolation_and_unknown_model(self):
        first = get_core_shape(' pq32-30 ')
        first['dimensions_mm']['width'] = 999
        first['notes'].append('test')
        self.assertEqual(get_core_shape('PQ32-30')['dimensions_mm']['width'], 32)
        all_rows = list_core_shapes()
        all_rows.clear()
        self.assertEqual(len(list_core_shapes()), 67)
        self.assertIsNone(get_core_shape('PQ32-99'))
        self.assertIsNone(get_core_shape(None))
        self.assertEqual(catalog_metadata()['units'], 'mm')

    def test_pq_waisted_plan_and_window_contours(self):
        """An octagonal envelope can pass bounds tests but fail this section."""
        def contains(poly, x, y):
            inside = False
            for a, b in zip(poly, poly[1:] + poly[:1]):
                if ((a[1] > y) != (b[1] > y)
                        and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]):
                    inside = not inside
            return inside

        pq = get_core_shape('PQ32-30')
        shape = pq['shape_profile']
        self.assertFalse(contains(shape['yoke_xy_mm'], 0, 10))
        self.assertTrue(contains(shape['yoke_xy_mm'], 15, 10))
        self.assertTrue(contains(shape['yoke_xy_mm'], 0, 6))
        self.assertFalse(any(contains(p, 13, 0) for p in shape['returns_xy_mm']))
        self.assertTrue(any(contains(p, 15, 0) for p in shape['returns_xy_mm']))
        for row in list_core_shapes():
            if row['family'] != 'PQ':
                continue
            with self.subTest(model=row['model']):
                profile = row['shape_profile']
                self.assertEqual(len(profile['returns_xy_mm']), 2)
                points = profile['yoke_xy_mm']
                self.assertAlmostEqual(max(p[0] for p in points)-min(p[0] for p in points),row['dimensions_mm']['width'],places=5)
                self.assertAlmostEqual(max(p[1] for p in points)-min(p[1] for p in points),row['dimensions_mm']['depth'],places=5)
                self.assertIn('manufacturer_orthographic',row['shape_evidence']['kind'])
                self.assertIn('limits',row['shape_evidence'])
        self.assertEqual(pq['shape_evidence']['source_page'],21)
        self.assertEqual(get_core_shape('PQ26-20')['shape_evidence']['source_page'],12)


if __name__ == '__main__':
    unittest.main()
