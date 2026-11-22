"""Complete desktop topology geometry and stable component hit identities."""
import copy
import json
from pathlib import Path
import unittest

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
from matplotlib.text import Text
from design_engine.specification import load_spec
from power_stage import DEFAULT_PARAMS, TOPOLOGIES
from topology_diagram import CAPACITOR_PITCH, draw_topology


ROOT = Path(__file__).resolve().parents[1]


def capacitors(count):
    return [dict(C=100e-6, ESR=.02, ESL=1e-9) for _ in range(count)]


def example(name):
    return load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))


class InteractiveGeometryChecks(unittest.TestCase):
    def draw(self, parameters):
        ax = Figure().subplots()
        hits = {'stale': []}
        before = copy.deepcopy(parameters)
        rows = draw_topology(ax, parameters, interactive=True, hits=hits)
        self.assertEqual(parameters, before)
        self.assertEqual(set(hits), {row['ref'] for row in rows})
        self.assertFalse(ax.child_axes)
        self.assertTrue(all(artist.axes is ax for parts in hits.values() for artist in parts))
        return ax, hits

    def assert_bank(self, ax, hits, refs):
        positions = []
        for ref in refs:
            label = next(artist for artist in hits[ref]
                         if isinstance(artist, Text) and artist.get_text() == ref)
            self.assertGreater(len(hits[ref]), 1)
            positions.append(label.get_position()[0])
        self.assertGreater(ax.get_xlim()[1], positions[-1])
        for left, right in zip(positions, positions[1:]):
            self.assertAlmostEqual(right-left, CAPACITOR_PITCH)

    def test_each_single_output_topology_draws_every_capacitor_with_pickable_geometry(self):
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                p = dict(DEFAULT_PARAMS, topology=topology, outputs=[], Kc=1.,
                         input_capacitors=capacitors(8), output_capacitors=capacitors(12))
                ax, hits = self.draw(p)
                for prefix, count in [('C_IN',8),('C_O',12)]:
                    self.assert_bank(ax, hits, [prefix+str(i) for i in range(1,count+1)])
                self.assertNotIn('…', [text.get_text() for text in ax.texts])

    def test_each_output_bank_has_its_own_numerical_identity_beyond_letter_z(self):
        from capacitor_banks import output_ref
        for name in ('40W_CCM_3OUT_FLYBACK.json','33W_3OUT_ACF_MP6005_COMPACT.json'):
            with self.subTest(name=name):
                p = example(name)
                p['coupling_config']['enabled'] = False
                for rail, count in zip(p['outputs'], (4,9,30)):
                    rail['output_capacitors'] = capacitors(count)
                ax, hits = self.draw(p)
                for rail, count in enumerate((4,9,30), 1):
                    self.assert_bank(ax, hits, [output_ref(rail,i,True) for i in range(1,count+1)])
                self.assertNotIn('…', [text.get_text() for text in ax.texts])

    def test_cot_preserves_shared_rows_but_represents_every_phase(self):
        p = example('96W_BUCK_COT_4PH.json')
        p.update(buck_phases=16, Rs=.01)
        ax, hits = self.draw(p)
        labels = {text.get_text() for text in ax.texts}
        self.assertTrue({f'相 {index}' for index in range(1,17)} <= labels)
        self.assertFalse(any('中间' in text for text in labels))
        for ref in ('Q1','Q2','L1','R_S1'):
            designators = [item for item in hits[ref] if isinstance(item,Text) and item.get_text()==ref]
            self.assertEqual(len(designators), 16)

    def test_psr_auxiliary_network_is_pickable_in_main_coordinates(self):
        p = example('40W_CCM_3OUT_FLYBACK.json')
        p['feedback_mode'] = 'PSR-MP6005'
        p['coupling_config']['enabled'] = False
        ax, hits = self.draw(p)
        for ref in ('N_A','R_FBH','R_FBL','R_REG','U_PSR','R_COMP','C_COMP','C_POLE'):
            self.assertGreater(len(hits[ref]), 1)
            self.assertTrue(any(isinstance(item,Text) and item.get_text().startswith(ref) for item in hits[ref]))
        draw_topology(ax,p)
        self.assertEqual(len(ax.child_axes), 1)

    def test_flyback_rcd_diode_connects_drain_to_separate_clamp_junction(self):
        def coordinates(artist):
            return tuple(tuple(round(value, 8) for value in point) for point in artist.get_xydata())

        def vertical_pins(artists):
            leads = [sorted(coordinates(item), key=lambda point:point[1]) for item in artists
                     if isinstance(item, Line2D) and len(item.get_xydata()) == 2]
            lower, upper = sorted((segment for segment in leads if segment[0][0] == segment[1][0]),
                                  key=lambda segment:segment[0][1])
            return lower[0], upper[1]

        for name in ('40W_CCM_FLYBACK.json', '40W_CCM_3OUT_FLYBACK.json',
                     '90W_QR_L6565_300V.json', '90W_QR_L6565_252_442V_REFERENCE.json'):
            for interactive in (False, True):
                with self.subTest(name=name, interactive=interactive):
                    p = example(name)
                    p['Kc'] = max(1.5, p['Kc'])
                    p['input_capacitors'] = capacitors(4)
                    ax, hits = Figure().subplots(), {}
                    draw_topology(ax, p, interactive=interactive, hits=hits)
                    diode = hits['D_SN1']
                    anode, cathode = vertical_pins(diode)
                    triangle = next(item.get_xy() for item in diode if isinstance(item, Polygon))
                    self.assertGreater(triangle[2, 1], triangle[0, 1])
                    wires = [coordinates(line) for line in ax.lines if len(line.get_xydata()) == 2]

                    def has_wire(a, b):
                        return (a, b) in wires or (b, a) in wires

                    drain = max((point for item in hits['Q1'] if isinstance(item, Line2D)
                                 for point in coordinates(item)), key=lambda point:point[1])
                    pin_labels = {item.get_text():item.get_position() for item in hits['Q1'] if isinstance(item, Text)}
                    drain_junction = drain[0], anode[1]
                    self.assertGreater(anode[1], pin_labels['G'][1])
                    self.assertGreater(anode[1] - pin_labels['D'][1], .5)
                    self.assertLess(anode[0], drain[0])
                    self.assertTrue(has_wire(anode, drain_junction))
                    self.assertTrue(any(a[0] == b[0] == drain[0] and min(a[1], b[1]) <= drain[1]
                                        <= anode[1] <= max(a[1], b[1]) for a, b in wires))

                    r_bottom, r_top = vertical_pins(hits['R_SN1'])
                    c_bottom, c_top = vertical_pins(hits['C_SN1'])
                    clamp = next((a, b) for a, b in wires if a[0] == r_bottom[0] and b[0] == c_bottom[0]
                                 and a[1] == b[1] and cathode[1] < a[1] < r_bottom[1])
                    clamp_y = clamp[0][1]
                    self.assertTrue(has_wire(cathode, (cathode[0], clamp_y)))
                    self.assertTrue(has_wire(r_bottom, clamp[0]))
                    self.assertTrue(has_wire(c_bottom, clamp[1]))
                    # Both top leads join the same positive rail feeding the primary.
                    result = ((a, b) for a, b in wires if a[1] == b[1] and a[1] > r_top[1]
                              and a[0] < r_top[0] < c_top[0] < b[0])
                    self.assertTrue(any(has_wire(r_top, (r_top[0], a[1]))
                                        and has_wire(c_top, (c_top[0], a[1])) for a, _ in result))


if __name__ == '__main__':
    unittest.main()
