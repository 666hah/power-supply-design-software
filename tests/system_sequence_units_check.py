"""Actual switching-deck composition, namespacing and retained hardware checks."""
import copy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from spice_export import project_files
from system_sequence_units import compile_unit


def example(name):
    return load_spec(json.loads((ROOT / 'examples' / name).read_text('utf-8-sig')))


def runtime(p):
    return calculate_parameters(p, analysis='endpoints', include_loop=False,
                                include_cross_regulation=False).runtime_bundle()


def definitions(unit):
    text = '\n'.join(value.decode('ascii') for value in unit['libraries'].values())
    return set(re.findall(r'(?im)^\.subckt\s+(\S+)', text))


class SequenceUnitChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = {}
        cls.compiled = {}
        names = dict(
            flyback='40W_CCM_FLYBACK.json',
            buck_vm='24W_BUCK_VM_TPS40200.json',
            buck_pcm='24W_BUCK_PCM_LTC3864.json',
            boost='24W_BOOST_PCM_LM5022.json',
            qr='90W_QR_L6565_300V_TUNED.json',
            acf='33W_3OUT_ACF_MP6005.json')
        for kind, name in names.items():
            p = example(name)
            bundle = runtime(p)
            cls.inputs[kind] = (p, bundle)
            cls.compiled[kind] = compile_unit(p, 'SEQ_' + kind.upper(), bundle=bundle)

    def test_every_supported_topology_retains_switching_power_stage(self):
        expected = dict(flyback=('LP vin_bus drain', 'R_SN1 clamp vin_bus', 'LS1 sgnd rect1'),
                        buck_vm=('L1 sw cap1', 'XQ1 sw gate_pin qsource', 'BGATE gate_drive qsource'),
                        buck_pcm=('L1 sw cap1', 'RS1 vin_bus qsource'),
                        boost=('L1 vin_bus sw', 'V_D1 sw rect1 0'),
                        qr=('LP vin_bus drain', 'XZCD rect1 sgnd zcd 0'),
                        acf=('C_ACTIVE drain aclamp', 'XQA aclamp auxgate 0', 'LO3 choke3 cap3'))
        for kind, unit in self.compiled.items():
            with self.subTest(kind=kind):
                stage = unit['subckt_text']
                for card in expected[kind]:
                    self.assertIn(card, stage)
                for removed in ('VIN_SOURCE ', 'VEN ', 'VCC_SOURCE ', 'BLOAD1 '):
                    self.assertNotIn('\n' + removed, stage)
                self.assertNotRegex(stage, r'(?im)^\.(?:step|tran|save|meas|options|include|lib)\b')
                self.assertIn('V_SECONDARY_REFERENCE sgnd 0 0', stage)
                self.assertIn('XC_IN1 vin_bus 0', stage)
                self.assertIn('XD_OUT1 cap1 out1', stage)
                self.assertIn('XFBSEL cap1', stage)
                interface = unit['manifest']['sequence_unit']
                self.assertTrue(stage.startswith('* Common-return'))
                self.assertIn('.subckt ' + interface['subckt_name'] + ' input en vcc out1', stage)
                self.assertEqual(interface['common_return'], '0')
                self.assertEqual(len(unit['outputs']), unit['output_count'])
                self.assertEqual(unit['outputs'][0]['out_node'], 'out1')
                self.assertEqual(unit['probes']['inputbus'], 'vin_bus')
                self.assertIn(unit['probes']['currents']['primary'] + ' ', stage)

    def test_qr_historical_primary_voltage_source_remains_explicit(self):
        p,_=self.inputs['qr']
        p=copy.deepcopy(p);p['spice_config']['qr_zcd_winding']=0
        unit=compile_unit(p,'SEQ_QR_LEGACY',bundle=runtime(p))
        self.assertIn('XZCD drain vin_bus zcd 0',unit['subckt_text'])
        self.assertEqual(unit['manifest']['qr']['zcd_sense']['source'],
                         'legacy-primary-terminal-voltage')

    def test_local_parameters_and_supplied_snapshot_are_not_mutated(self):
        from design_engine.contracts import json_value
        p, bundle = self.inputs['flyback']
        original_p = copy.deepcopy(p)
        before = json.dumps(json_value(bundle), sort_keys=True)
        with patch('design_engine.service.calculate_parameters', side_effect=AssertionError('unneeded recalculation')):
            result = compile_unit(p, 'Owned', bundle=bundle)
        self.assertEqual(p, original_p)
        self.assertEqual(json.dumps(json_value(bundle), sort_keys=True), before)
        stage = result['subckt_text']
        self.assertGreater(stage.index('.param FSW='), stage.index('.subckt Owned_UNIT'))
        self.assertLess(stage.index('.param FSW='), stage.index('.ends Owned_UNIT'))
        self.assertIn('.model SHORT_SW ', stage)
        result['manifest']['resolved_controller']['VG'] = -999
        self.assertGreater(self.compiled['flyback']['manifest']['resolved_controller']['VG'], 0)

    def test_every_library_definition_and_cross_library_call_is_namespaced(self):
        all_defined = set()
        for unit in self.compiled.values():
            interface = unit['manifest']['sequence_unit']
            own = definitions(unit)
            self.assertFalse(all_defined & own)
            all_defined |= own
            for old, new in interface['symbols'].items():
                self.assertIn(new, own)
                for content in list(unit['libraries'].values()) + [unit['subckt_text'].encode('ascii')]:
                    text = content.decode('ascii')
                    self.assertNotRegex(text, r'(?i)(?<![A-Za-z0-9_])' + re.escape(old) + r'(?![A-Za-z0-9_])')
            for path in unit['libraries']:
                self.assertTrue(path.startswith(interface['namespace'] + '_'))
                self.assertNotIn('\\', path)
                self.assertNotIn('/', path)

    def test_fast_and_full_buck_controller_variants_coexist_without_alias_collision(self):
        p, bundle = self.inputs['buck_pcm']
        p = copy.deepcopy(p)
        p['spice_config']['short_mode'] = 1
        full = compile_unit(p, 'WithProtection', bundle=bundle)
        fast = self.compiled['buck_pcm']
        self.assertFalse(definitions(full) & definitions(fast))
        full_lib = '\n'.join(v.decode() for v in full['libraries'].values())
        self.assertIn('.subckt WithProtection_GNISO_CTRL ', full_lib)
        self.assertIn('Xsuper cs_filtered GATE EN VCC', full_lib)
        self.assertIn('scp', full['probes']['controller'])
        self.assertNotIn('scp', fast['probes']['controller'])
        self.assertEqual(fast['manifest']['sequence_unit']['thresholds']['fault_model'],
                         'cycle-limit-only-fault-output-zero')

    def test_parasitic_and_plain_library_variants_preserve_their_original_contents(self):
        p, _ = self.inputs['flyback']
        changed = copy.deepcopy(p)
        changed['parasitic_config'] = dict(mode='fast', r_cj=.3, cw_primary=40e-12,
                                          snub_r_primary=12., snub_c_primary=50e-12)
        unit = compile_unit(changed, 'WithParasitics')
        plain = self.compiled['flyback']
        changed_library = unit['libraries']['WithParasitics_GenericFlybackPWM.lib'].decode()
        plain_library = plain['libraries']['SEQ_FLYBACK_GenericFlybackPWM.lib'].decode()
        self.assertIn('Rser={RCJ}', changed_library)
        self.assertIn('Rser=0.1 m={ACT}', plain_library)
        self.assertIn('C_PAR_P vin_bus drain 4e-11', unit['subckt_text'])
        self.assertIn('C_PAR_Q1 par_Q1 sense 5e-11', unit['subckt_text'])
        self.assertFalse(definitions(unit) & definitions(plain))
        self.assertNotEqual(unit['manifest']['sequence_unit']['source_hashes']['GenericFlybackPWM.lib'],
                            plain['manifest']['sequence_unit']['source_hashes']['GenericFlybackPWM.lib'])

    def test_field_matrix_extra_capacitors_and_all_output_ports_survive(self):
        p, _ = self.inputs['qr']
        p = copy.deepcopy(p)
        p.update(outputs=[dict(name='主路', V_out=60., P_out=92., P_out_min=92., Ns=30),
                          dict(name='辅助', V_out=13., P_out=.1, P_out_min=.1, Ns=7)])
        caps = [dict(C=100e-6, ESR=.03, ESL=3e-9), dict(C=47e-6, ESR=.02, ESL=2e-9),
                dict(C=4.7e-6, ESR=.1, ESL=1e-9)]
        p['input_capacitors'] = copy.deepcopy(caps)
        for rail in p['outputs']:
            rail['output_capacitors'] = copy.deepcopy(caps)
        lp = p['L']
        self_l = [lp, lp * (30 / p['Np']) ** 2 * 1.02, lp * (7 / p['Np']) ** 2 * 1.04]
        p['coupling_config'] = dict(enabled=False, field_matrix_enabled=True,
            port_order=['P', 'OUT1', 'OUT2'], self_inductances_H=self_l,
            k=[[1., .98, .98], [.98, 1., .98], [.98, .98, 1.]])
        unit = compile_unit(p, 'Field')
        stage = unit['subckt_text']
        self.assertEqual(unit['output_count'], 2)
        self.assertIn('XC_IN3 vin_bus 0 Field_GPWR_CAP C=4.7e-06', stage)
        for i in (1, 2):
            self.assertIn(f'XC_O{i}_3 cap{i} sgnd Field_GPWR_CAP', stage)
            self.assertIn(f'LS{i} sgnd rect{i}', stage)
            self.assertIn(f'out{i}', unit['manifest']['sequence_unit']['pins'])
            self.assertNotIn(f'BLOAD{i} ', stage)
            self.assertEqual(unit['probes'][f'cap{i}'], f'cap{i}')
        self.assertIn('K_1_2 LS1 LS2 {K_1_2}', stage)
        self.assertIn(f'.param LS2={self_l[2]:.12g}', stage)
        self.assertEqual(unit['manifest']['coupling']['source'], 'field-self-and-pairwise-kij')
        self.assertEqual(unit['manifest']['coupling']['self_inductances_H'], self_l)

    def test_controller_thresholds_and_known_shutdown_boundaries_are_explicit(self):
        qr = self.compiled['qr']['manifest']['sequence_unit']
        values = self.compiled['qr']['manifest']['resolved_controller']
        self.assertEqual(qr['thresholds']['vcc_uvlo_on_v'], values['UVON'])
        self.assertEqual(qr['thresholds']['vcc_uvlo_off_v'], values['UVOFF'])
        self.assertEqual(qr['thresholds']['fault_reset'], 'vcc-below-uvlo-off')
        self.assertIsNone(qr['thresholds']['input_uvlo'])
        self.assertIn('名义 VIN', ''.join(self.compiled['buck_vm']['manifest']['sequence_unit']['limitations']))
        self.assertIn('Boost', ''.join(self.compiled['boost']['manifest']['sequence_unit']['limitations']))
        self.assertIn('BOVERLAP overlap 0', self.compiled['acf']['subckt_text'])
        self.assertEqual(self.compiled['acf']['probes']['controller']['filtered_cs'],
                         'xu_ctrl:xmain:cs_filtered')

    def test_current_voltage_monitors_read_actual_branches_without_series_rewiring(self):
        for kind, unit in self.compiled.items():
            with self.subTest(kind=kind):
                monitor = unit['manifest']['sequence_unit']['current_probes']
                self.assertEqual(monitor['scale_A_per_V'], 1.)
                self.assertEqual(monitor['representation'], 'independent-voltage-monitor')
                primary = 'L1' if kind.startswith('buck') or kind == 'boost' else 'LP'
                self.assertEqual(unit['probes']['currents']['primary'], 'SEQ_I_' + primary)
                self.assertEqual(unit['probes']['currents']['sense'], 'SEQ_I_RS1')
                self.assertIn(f'BSEQ_I_{primary} SEQ_I_{primary} 0 V=I({primary})', unit['subckt_text'])
                self.assertIn('BSEQ_I_RS1 SEQ_I_RS1 0 V=I(RS1)', unit['subckt_text'])
                self.assertEqual(unit['subckt_text'].count('BSEQ_I_RS1 '), 1)
                self.assertIn('RS1 ', unit['subckt_text'])
                self.assertNotIn('I(X', unit['subckt_text'])
                self.assertGreater(unit['manifest']['resolved_controller']['RSENSE'], 0.)

    def test_unsupported_topologies_psr_and_invalid_namespace_reject_before_calculation(self):
        p, _ = self.inputs['flyback']
        with patch('design_engine.service.calculate_parameters', side_effect=AssertionError('should not calculate')):
            for topology in ('LDO', 'BUCK-BOOST', 'UNKNOWN'):
                with self.subTest(topology=topology), self.assertRaisesRegex(ValueError, '不支持'):
                    compile_unit(dict(p, topology=topology), 'Unit')
            with self.assertRaisesRegex(ValueError, 'PSR'):
                compile_unit(dict(p, feedback_mode='PSR-MP6005'), 'Unit')
            for namespace in ('../Unit', '1Unit', 'Bad-Unit', 'U\n.include secret', 'U' * 49):
                with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                    compile_unit(p, namespace)

    def test_external_include_and_unresolved_library_calls_fail_closed(self):
        p, bundle = self.inputs['flyback']
        files = project_files(p, bundle=bundle)
        for injection in (b'.include C:\\private\\custom.lib', b'.lib custom.lib',
                          b'.include ../custom.lib'):
            bad = copy.deepcopy(files)
            bad['Flyback.cir'] = bad['Flyback.cir'].replace(b'.end', injection + b'\n.end')
            with self.subTest(injection=injection), patch('spice_export.project_files', return_value=bad):
                with self.assertRaisesRegex(ValueError, 'include'):
                    compile_unit(p, 'Blocked', bundle=bundle)
        bad = copy.deepcopy(files)
        bad['power_stage.inc'] += b'XUNSAFE a b UnknownSubcircuit\n'
        with patch('spice_export.project_files', return_value=bad), self.assertRaisesRegex(ValueError, '未解析'):
            compile_unit(p, 'Blocked', bundle=bundle)


if __name__ == '__main__':
    unittest.main(verbosity=2)
