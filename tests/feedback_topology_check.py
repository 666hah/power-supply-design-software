"""Check that the desktop power, feedback and control circuits share physical nets."""
import json
from itertools import combinations
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from matplotlib.figure import Figure
from matplotlib.lines import Line2D

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cot_settings import active as cot_active, configuration as cot_configuration
from design_engine.specification import load_spec
from example_catalog import PUBLIC_QR, example_feedback_defaults
from feedback_controller_diagram import draw_controller_block
from feedback_topology import COMMAND_INK, GATE_INK, SENSE_INK, draw_compensation_view, draw_feedback_stage
from power_stage import compute_operating_point
from topology_diagram import draw_psr_network, draw_topology


DEFAULT_STATE = dict(topo='opamp3', dir='fwd', type2=False, vars={})


def example(name):
    raw = json.loads((ROOT / 'examples' / name).read_text(encoding='utf-8'))
    config = example_feedback_defaults(raw)
    return load_spec(config), config.get('__comp', DEFAULT_STATE)


class FeedbackTopologyChecks(unittest.TestCase):
    def render(self, p, state, op=None):
        if op is None:
            op = compute_operating_point(p)
        ax, hits, power = Figure().subplots(), {}, {}
        rows = {row['ref']: row for row in draw_topology(
            ax, p, op, interactive=True, hits=hits, control_ports=True, control_anchors=power)}
        with patch('feedback_topology.draw_compensation_view', wraps=draw_compensation_view) as comp, \
                patch('feedback_controller_diagram.draw_controller_block', wraps=draw_controller_block) as ctrl, \
                patch('topology_diagram.draw_psr_network', wraps=draw_psr_network) as psr:
            areas = draw_feedback_stage(ax, p, op, state, hits, rows, power)
        chip = ctrl.call_args.kwargs['ports']
        self.assertLess(areas['controller'][1], areas['compensation'][0])
        self.assertLess(areas['compensation'][2], areas['controller'][3])
        self.assertEqual({name for name in power if name.startswith('VG_') and not name.endswith('_escape')},
                         set(chip['gates']))
        for gate, pin in chip['gates'].items():
            end = power[f'{gate}_escape'][0]
            self.assert_joined(ax, pin, end, GATE_INK)
            self.assert_joined(ax, end, power[gate])
        gate_lines = [item for item in ax.lines if item.get_color() == GATE_INK]
        self.assertEqual(len(gate_lines), len(chip['gates']))
        if cot_active(p):
            self.assert_separate_gate_routes(gate_lines)
        if psr.called:
            net = psr.call_args.kwargs['anchors']
            self.assert_joined(ax, net['FB_AUX'], chip['input'], SENSE_INK)
            comp_line = self.assert_joined(ax, net['COMP'], chip['psr_comp'], COMMAND_INK)
            sense_line = self.assert_joined(ax, net['SENSE'], chip['sensors']['SENSE'], SENSE_INK)
            self.assert_distinct_lanes(comp_line, sense_line)
            source = power.get('CS_RAW_escape', (power['CS_RAW'],))[0]
            self.assert_joined(ax, source, net['CS_RAW'], SENSE_INK)
        else:
            sense = 'V_SENSE−' if p['topology'] == 'BUCK-BOOST' else 'V_SENSE'
            source = power[f'{sense}_escape'][0]
            self.assert_joined(ax, power[sense], source)
            if comp.called:
                net = comp.call_args.kwargs['ports']
                self.assert_joined(ax, source, net['sense'], SENSE_INK)
                self.assert_joined(ax, net['output'], chip['input'], COMMAND_INK)
            else:
                self.assertTrue(cot_active(p))
                tap, = (tuple(item.get_xydata()[-1]) for item in ax.lines
                        if item.get_color() == SENSE_INK and tuple(item.get_xydata()[0]) == source)
                through, = (tuple(item.get_xydata()[-1]) for item in ax.lines
                            if item.get_color() == SENSE_INK and tuple(item.get_xydata()[0]) == tap)
                self.assert_joined(ax, through, chip['input'], COMMAND_INK)
        labels = {key: {label.get_text() for label in ax.texts
                        if left <= label.get_position()[0] <= right and bottom <= label.get_position()[1] <= top}
                  for key, (left, right, bottom, top) in areas.items()}
        self.assertEqual(set(hits), set(rows))
        self.assertTrue(all(artist.axes is ax for artists in hits.values() for artist in artists))
        self.assertFalse(ax.images)
        self.assertFalse(ax.child_axes)
        return labels, hits, power

    def assert_joined(self, axis, start, end, ink=None):
        if start == end:
            return
        for line in axis.lines:
            coordinates = line.get_xydata()
            if len(coordinates) < 2 or ink is not None and line.get_color() != ink:
                continue
            if {tuple(coordinates[0]), tuple(coordinates[-1])} == {start, end}:
                return line
        self.fail(f'Missing conductor from {start} to {end} ({ink})')

    @staticmethod
    def vertical_spans(line):
        points = line.get_xydata() if line is not None else ()
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 == x1 and y0 != y1:
                yield x0, min(y0, y1), max(y0, y1)

    def assert_distinct_lanes(self, first, second):
        for x, low, high in self.vertical_spans(first):
            for other_x, other_low, other_high in self.vertical_spans(second):
                self.assertFalse(x == other_x and max(low, other_low) < min(high, other_high),
                                 'PSR COMP and SENSE share the same drawn conductor')

    def assert_separate_gate_routes(self, gate_lines):
        routes = []
        for line in gate_lines:
            points = line.get_xydata()
            segments = []
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                self.assertTrue(x0 == x1 or y0 == y1)
                if x0 != x1 or y0 != y1:
                    segments.append((min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)))
            routes.append(segments)
        for first, second in combinations(routes, 2):
            for x0, x1, y0, y1 in first:
                for xx0, xx1, yy0, yy1 in second:
                    self.assertFalse(max(x0, xx0) <= min(x1, xx1) and max(y0, yy0) <= min(y1, yy1),
                                     'COT gate routes touch or cross')

    def assert_labels(self, labels, *expected):
        self.assertFalse(set(expected) - labels, f'Missing labels: {set(expected) - labels}')

    def test_fixed_pwm_qr_active_clamp_and_both_llc_controllers(self):
        cases = (
            ('24W_BUCK_VM_TPS40200.json', (), ('PWM 比较器', '振荡器'), 1),
            ('24W_BUCK_PCM_LTC3864.json', ('CS_RAW', 'CS_RETURN'), ('峰流比较器',), 1),
            ('24W_BOOST_PCM_LM5022.json', ('CS_RAW', 'CS_RETURN'), ('峰流比较器',), 1),
            ('40W_CCM_3OUT_FLYBACK.json', ('CS_RAW', 'CS_RETURN'), ('峰流比较器',), 1),
            ('33W_3OUT_ACF_MP6005_COMPACT.json', ('CS_RAW', 'CS_RETURN'), ('互锁／死区',), 2),
            (PUBLIC_QR, ('CS_RAW', 'CS_RETURN', 'ZCD_RAW+', 'ZCD_RAW−'), ('ZCD 谷底触发', '电流采样／消隐'), 1),
            ('300W_LLC_HALF_HHC.json', ('V_CR+', 'V_CR−', 'I_LR'), ('换相比较', 'Cr 采样／斜坡'), 2),
            ('300W_LLC_FULL_VCO.json', ('I_LR',), ('VCO 限频', '互锁／死区'), 4),
        )
        for name, sense, logic, switches in cases:
            with self.subTest(example=name):
                p, state = example(name)
                labels, _, _ = self.render(p, state)
                self.assertEqual(set(labels), {'power', 'compensation', 'controller', 'feedback_loop'})
                gates = [f'VG_Q{switch}' for switch in range(1, switches + 1)]
                self.assert_labels(labels['power'], 'V_SENSE', *sense, *gates)
                self.assert_labels(labels['controller'], *logic, *sense, '栅极驱动', 'COMP')
                command = 'V_OPTO' if p['topology'] not in ('BUCK', 'BOOST') else 'COMP'
                self.assert_labels(labels['compensation'], 'V_SENSE', command)
                if command == 'V_OPTO':
                    self.assert_labels(labels['compensation'], 'PGND', 'SGND', 'TL431')
                else:
                    self.assertNotIn('SGND', labels['compensation'])

    def test_psr_keeps_its_feedback_and_compensation_in_the_primary_domain(self):
        p, state = example('MP6005_PSR_FLYBACK.json')
        op = compute_operating_point(p)
        for region in ('PWM', 'PFM-estimate'):
            with self.subTest(region=region):
                labels, hits, _ = self.render(p, state, dict(op, regulation_region=region))
                self.assertEqual(set(labels), {'power', 'compensation', 'controller', 'feedback_loop'})
                self.assert_labels(labels['power'], 'VG_Q1', 'CS_RAW')
                self.assert_labels(labels['compensation'], 'FB_AUX', 'SENSE', 'COMP')
                self.assert_labels(labels['controller'], 'FB', 'SENSE', 'GATE', 'COMP')
                self.assertEqual('PFM 轻载降频' in labels['controller'], region == 'PFM-estimate')
                self.assertTrue({'U_PSR', 'R_COMP', 'C_COMP', 'C_POLE'} <= set(hits))
                self.assertNotIn('V_OPTO', labels['controller'])

    def test_cot_sensor_and_gate_nets_keep_their_phase_numbers(self):
        p, state = example('96W_BUCK_COT_4PH.json')
        for phase_count in (p['buck_phases'], 16):
            with self.subTest(phases=phase_count):
                original_rows = p['cot_config']['phase_parameters']
                phase_parameters = original_rows + [{} for _ in range(phase_count-len(original_rows))]
                configured = dict(p, buck_phases=phase_count,
                                  cot_config=dict(p['cot_config'], phase_parameters=phase_parameters))
                labels, _, _ = self.render(configured, state)
                self.assertEqual(set(labels), {'power', 'compensation', 'controller', 'feedback_loop'})
                for phase in range(1, phase_count + 1):
                    pins = (f'VG_Q1_P{phase}', f'VS_Q1_P{phase}',
                            f'VG_Q2_P{phase}', f'VS_Q2_P{phase}', f'IS_P{phase}')
                    self.assert_labels(labels['power'], *pins, 'VIN_BUS', 'V_SENSE')
                    self.assert_labels(labels['controller'], f'GH{phase}', f'GL{phase}')
                self.assert_labels(labels['controller'], 'FB', '电压误差 PI', '相位轮转')
                if cot_configuration(configured)['model'] == 'current_feedback':
                    self.assert_labels(labels['controller'], '总电流反馈')
                self.assertNotIn('COMP', labels['controller'])

    def test_inverting_output_keeps_signed_sense_node_and_ground(self):
        p, state = example('24W_BUCK_VM_TPS40200.json')
        p['topology'] = 'BUCK-BOOST'
        labels, _, _ = self.render(p, state)
        self.assert_labels(labels['power'], 'V_SENSE−', 'PGND')
        self.assert_labels(labels['compensation'], 'V_SENSE−', 'V_FB_MAG', 'PGND', 'COMP')
        self.assert_labels(labels['controller'], 'COMP')

    def test_ssr_voltage_pickoff_is_on_selected_capacitor_rail_before_blocking_diode(self):
        p, state = example('40W_CCM_3OUT_FLYBACK.json')
        p.update(feedback_output=2, coupling_config=dict(enabled=False))
        p['outputs'][1]['d_out_enable'] = True
        _, hits, power = self.render(p, state)
        diode_x, rail_y = min((x, y) for item in hits['D_B2'] if isinstance(item, Line2D)
                              for x, y in item.get_xydata())
        sense_x, sense_y = power['V_SENSE']
        self.assertLess(sense_x, diode_x)
        self.assertAlmostEqual(sense_y, rail_y)


if __name__ == '__main__':
    unittest.main()
