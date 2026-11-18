"""Manufacturer-view regression checks beyond the outer bounding box."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core_shape_catalog import get_core_shape


def inside(poly, x, y):
    yes = False
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if ((a[1] > y) != (b[1] > y)
                and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]):
            yes = not yes
    return yes


class ManufacturerOutlineTests(unittest.TestCase):
    def test_rm_waist_and_three_distinct_figures(self):
        for name, waist, figure in [('RM6',8,3),('RM8',10.8,2),('RM10',13.25,2),
                                    ('RM12',16,2),('RM14',18.7,1)]:
            r = get_core_shape(name)
            p = r['shape_profile']
            d = r['dimensions_mm']
            self.assertIn(f'Fig.{figure}', p['source_method'])
            self.assertAlmostEqual(r['drawing_dimensions_mm']['I'],waist)
            self.assertLess(d['depth'],d['width'])
            self.assertFalse(inside(p['yoke_xy_mm'],0,waist/2+.1))
            self.assertTrue(inside(p['yoke_xy_mm'],0,waist/2-.1))
            self.assertFalse(any(inside(v,0,0) for v in p['returns_xy_mm']))
            self.assertEqual(len(p['returns_xy_mm']),2)

    def test_ep_round_rear_cavity_is_open_only_at_front(self):
        for name in ['EP7','EP10','EP13']:
            r = get_core_shape(name)
            p = r['shape_profile']
            lo = min(v[1] for v in p['yoke_xy_mm'])
            hi = max(v[1] for v in p['yoke_xy_mm'])
            self.assertGreater(-lo,hi)
            self.assertEqual(len(p['returns_xy_mm']),1)
            self.assertTrue(inside(p['returns_xy_mm'][0],0,lo+.05))
            self.assertFalse(inside(p['returns_xy_mm'][0],0,hi-.05))
            self.assertFalse(inside(p['returns_xy_mm'][0],0,0))

    def test_efd_centre_bottom_offset_follows_each_individual_view(self):
        # A shared flush-to-edge rectangle would have zero offsets and pass
        # the old envelope tests, but would fail all four source dimensions.
        for name,inset in [('EFD15',-.2),('EFD20',.17),('EFD25',.6),('EFD30',.75)]:
            r=get_core_shape(name);d=r['dimensions_mm'];p=r['shape_profile']
            self.assertEqual(r['manufacturer'],'TDK Electronics')
            centre_bottom=max(y for _,y in p['center_xy_mm'])+p['center_offset_xy_mm'][1]
            self.assertAlmostEqual(d['body_depth']/2-centre_bottom,inset,places=5)
            self.assertFalse(inside(p['yoke_xy_mm'],0,-d['body_depth']/2+.05))
            self.assertGreater(len(p['center_xy_mm']),4)
            self.assertEqual(len(p['returns_xy_mm']),2)

    def test_eer_pole_faces_are_curved_in_each_individual_drawing(self):
        for name,page in [('ER28',35),('EER28L',37),('ER35',39),('EER40',41)]:
            r=get_core_shape(name);d=r['dimensions_mm'];p=r['shape_profile']
            self.assertEqual(r['shape_evidence']['source_page'],page)
            pole=p['returns_xy_mm'][0]
            e=d['window_outer_width']/2
            self.assertTrue(inside(pole,-e-.05,0))
            self.assertFalse(inside(pole,-e+.05,0))
            # Near the side edge the curved pole extends toward the centre.
            self.assertTrue(inside(pole,-e+.05,d['depth']*.43))


if __name__=='__main__':
    unittest.main()
