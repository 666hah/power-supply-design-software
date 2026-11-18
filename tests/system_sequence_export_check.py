"""System-deck/persistence contracts; compilation is not an LTspice result.

Two real Buck decks are compiled once. Other topology cases deliberately use
small, labelled compiler fixtures to inspect composition without repeated solves.
"""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import power_network as network
import system_workspace as workspace
import system_sequence_config as config
from system_sequence_export import project_files, export_project
from system_sequence_units import compile_unit, SUPPORTED_TOPOLOGIES


def example(name):
    return json.loads((ROOT/'examples'/name).read_text(encoding='utf-8-sig'))


def project(spec, second=None):
    value = workspace.fresh_project(spec)
    if second is not None:
        value['units'].append(dict(id='PSU-02', name='第二个独立电源', spec=copy.deepcopy(second), enabled=True))
        value['connections'].append(dict(id='LINK-002', source=dict(kind='bus', id='BUS-01', output=1),
                                         target='PSU-02', mode='direct', vf=.3, enabled=True))
    return network.normalize(value)


def fixture_compiler(spec, namespace, bundle=None):
    """Structural fixture only: no waveform, protection or convergence claim."""
    from power_units import unit_rails
    topology = spec['topology']
    if topology not in SUPPORTED_TOPOLOGIES:
        raise ValueError('结构夹具不支持此拓扑')
    rails = unit_rails(spec)
    name = namespace+'_UNIT'
    pins = ['input', 'en', 'vcc']+[f'out{i}' for i in range(1, len(rails)+1)]
    lines = ['* STRUCTURAL COMPILER FIXTURE - NOT A SIMULATOR RESULT.', '.subckt '+name+' '+' '.join(pins),
             'Rin input vin_bus .01', 'Cin vin_bus 0 1u',
             f'XU_CTRL en vcc gate {namespace}_FIXTURE_CTRL', 'Rsense sense 0 .1']
    for i in range(1, len(rails)+1):
        lines.extend((f'Cout{i} cap{i} 0 1u', f'Rout{i} cap{i} out{i} .01'))
    lines.append('.ends '+name)
    probes = dict(input='input', inputbus='vin_bus', en='en', vcc='vcc', gate='gate', sense='sense',
                  controller=dict(run='xu_ctrl:active'))
    for i in range(1, len(rails)+1):
        probes.update({f'cap{i}': f'cap{i}', f'out{i}': f'out{i}'})
    return dict(subckt_text='\n'.join(lines)+'\n',
                libraries={namespace+'_Fixture.lib': (f'* STRUCTURAL FIXTURE\n.subckt {namespace}_FIXTURE_CTRL en vcc gate\n'
                    'Rgate gate 0 1e9\nBactive active 0 V=V(en)\n'+f'.ends {namespace}_FIXTURE_CTRL\n').encode('ascii')},
                output_count=len(rails), outputs=[dict(id=i, name=r.get('name', f'OUT{i}'), V_out=r['V_out'],
                    P_out=r['P_out'], cap_node=f'cap{i}', out_node=f'out{i}') for i, r in enumerate(rails, 1)],
                probes=probes, manifest=dict(topology=topology, resolved_controller=dict(FSW=spec['f_sw']),
                    sequence_unit=dict(namespace=namespace, subckt_name=name, pins=pins,
                        model_scope='switching-power-stage-with-generic-behavioral-controller',
                        thresholds=dict(nominal_vcc_v=10.), limitations=['STRUCTURAL FIXTURE; not calculated or simulated.'])))


def leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    else:
        yield value


class SequenceExportChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vm = example('24W_BUCK_VM_TPS40200.json')
        cls.pcm = example('24W_BUCK_PCM_LTC3864.json')
        # Deliberately non-default distinct banks make retention measurable.
        cls.vm['input_capacitors'] = [dict(C=123e-6, ESR=.041, ESL=3e-9), dict(C=8.2e-6, ESR=.075, ESL=2e-9)]
        cls.vm['output_capacitors'] = [dict(C=221e-6, ESR=.031, ESL=4e-9), dict(C=33e-6, ESR=.052, ESL=5e-9)]
        cls.vm['spice_config']['include_cap_esl'] = 1
        cls.real_project = project(cls.vm, cls.pcm)
        cls.real_input = copy.deepcopy(cls.real_project)
        cls.compiled = {}
        def real_compiler(spec, namespace):
            unit = compile_unit(spec, namespace)
            cls.compiled[namespace] = copy.deepcopy(unit)
            return unit
        with patch('system_sequence_units.compile_unit', side_effect=real_compiler):
            cls.real_files, cls.real_manifest = project_files(cls.real_project)
        cls.artifacts = ROOT/'artifacts'/'system-sequence-export-check'
        cls.artifacts.mkdir(parents=True, exist_ok=True)

    def structural(self, value):
        with patch('system_sequence_units.compile_unit', side_effect=fixture_compiler):
            return project_files(value)

    def test_system_transient_retains_declared_parasitics_without_mutating_units(self):
        self.assertEqual(self.real_project,self.real_input)
        for identity,row in self.real_manifest['units'].items():
            policy=row['compiled_manifest']['sequence_unit']['switching_capacitance_policy']
            self.assertTrue(policy['retain_declared'])
            self.assertEqual(policy['effective_mode'],1.)
            namespace=row['instance'][1:]
            deck=self.real_files[namespace+'_unit.inc'].decode('ascii')
            for field in ('Q_COSS','Q_CG','DIODE_CJ'):
                value=float(re.search(r'^\.param '+field+r'=(\S+)',deck,re.M)[1])
                self.assertGreater(value,0.,(identity,field))
        value=copy.deepcopy(self.real_project)
        value['sequence_config']=config.normalize(value)
        value['sequence_config']['settings']['include_switching_capacitance']=False
        for unit in value['units']:unit['spec']['spice_config']['niso_edge_model']=0.
        _,manifest=self.structural(value)
        for row in manifest['units'].values():
            policy=row['compiled_manifest']['sequence_unit']['switching_capacitance_policy']
            self.assertFalse(policy['retain_declared'])
            self.assertEqual(policy['effective_mode'],0.)

    def assert_cards_are_scoped_and_unique(self, files):
        definitions = {}
        for filename, data in files.items():
            self.assertEqual(Path(filename).name, filename)
            self.assertNotRegex(filename, r'[/\\\s]')
            self.assertIsInstance(data, bytes)
            self.assertTrue(data.endswith(b'\n'), filename+' must end with a real newline')
            self.assertGreater(data.count(b'\n'), 1, filename)
            if Path(filename).suffix not in ('.lib', '.inc', '.cir'):
                continue
            text = data.decode('ascii')
            self.assertNotIn('\\n', text, filename+' must not contain escaped newline separators')
            scopes, elements = [], {}
            for index, raw in enumerate(text.splitlines()):
                line = raw.strip()
                if not line or line[0] in '*;':
                    continue
                if filename.endswith('.cir') and index == 0:
                    continue  # SPICE deck title, not an element.
                lower = line.casefold()
                if lower.startswith('.subckt '):
                    name = line.split()[1].casefold()
                    self.assertNotIn(name, definitions, f'global subcircuit collision: {filename}: {name}')
                    definitions[name] = filename
                    scopes.append(name)
                elif lower.startswith('.ends'):
                    self.assertTrue(scopes, filename+' has unmatched .ends')
                    if len(line.split()) > 1:
                        self.assertEqual(line.split()[1].casefold(), scopes[-1])
                    scopes.pop()
                elif line.startswith('.'):
                    if lower.startswith('.include '):
                        include = line.split()[1]
                        self.assertIn(include, files, filename+' has a missing include')
                        self.assertEqual(Path(include).name, include)
                else:
                    ref = line.split()[0].casefold()
                    scope = tuple(scopes)
                    seen = elements.setdefault(scope, set())
                    self.assertNotIn(ref, seen, f'{filename}/{scope}: duplicate element {ref}')
                    seen.add(ref)
            self.assertEqual(scopes, [], filename+' has an unclosed subcircuit')
        # Resolve X calls separately after gathering definitions across files.
        for filename, data in files.items():
            if Path(filename).suffix not in ('.inc', '.lib'):
                continue
            for line in data.decode('ascii').splitlines():
                if not line.lstrip().lower().startswith('x'):
                    continue
                tokens = line.split()
                parameter = next((i for i, token in enumerate(tokens) if '=' in token), len(tokens))
                model = parameter-1
                if tokens[model].casefold() == 'params:':
                    model -= 1
                self.assertIn(tokens[model].casefold(), definitions, filename+': unresolved '+tokens[0])

    def test_legacy_project_does_not_gain_sequence_config(self):
        value = project(self.vm)
        self.assertNotIn('sequence_config', value)
        self.assertNotIn('sequence_config', network.normalize(value))
        with tempfile.TemporaryDirectory(dir=self.artifacts) as folder:
            path = Path(folder)/'legacy.json'
            workspace.save_project(value, path)
            self.assertNotIn('sequence_config', json.loads(path.read_text('utf-8')))
            self.assertNotIn('sequence_config', workspace.load_project(path))
        self.assertNotIn('sequence_config', self.real_project)

    def test_saved_settings_roundtrip_and_original_input_not_mutated(self):
        value = project(self.vm)
        value['sequence_config'] = config.defaults(value)
        cfg = value['sequence_config']
        cfg['settings'].update(vin_case='max', stop_s=.06)
        cfg['sources']['BUS-01'].update(on_s=.003, off_s=.04, resistance_ohm=.093)
        cfg['units']['PSU-01'].update(enable_s=.005, disable_s=.05, vin_on_V=20., vin_off_V=18., soft_start_s=.007)
        cfg['rail_loads']['PSU-01/OUT1'].update(mode='I', on_V=8., off_V=6., input_capacitance_F=22e-6)
        expected = config.normalize(value)
        with tempfile.TemporaryDirectory(dir=self.artifacts) as folder:
            path = Path(folder)/'sequence.json'
            workspace.save_project(value, path)
            reopened = workspace.load_project(path)
        self.assertEqual(reopened['sequence_config'], expected)
        self.assertIsNone(expected['sources']['BUS-01']['current_limit_A'])
        self.assertEqual(self.real_project, self.real_input, 'export must not mutate the canvas')

    def test_orphan_settings_remain_editable_and_do_not_generate_circuit(self):
        value = project(self.vm, self.pcm)
        value['sequence_config'] = config.defaults(value)
        value['sequence_config']['units']['PSU-02'].update(enable_s=.007, wait_for_port='REMOVED/OUT1', pg_threshold_V=8.)
        value['sequence_config']['rail_loads']['PSU-02/OUT1']['power_W'] = 7.3
        original = copy.deepcopy(value['sequence_config'])
        workspace.remove_node(value, 'unit', 'PSU-02')
        normalized = network.normalize(value)
        for group, identity in (('units', 'PSU-02'), ('rail_loads', 'PSU-02/OUT1'), ('connections', 'LINK-002')):
            self.assertEqual(normalized['sequence_config'][group][identity], original[group][identity])
        with tempfile.TemporaryDirectory(dir=self.artifacts) as folder:
            path = Path(folder)/'orphans.json'
            workspace.save_project(normalized, path)
            reopened = workspace.load_project(path)
        self.assertEqual(reopened['sequence_config'], normalized['sequence_config'])
        files, manifest = self.structural(reopened)
        self.assertEqual(set(manifest['units']), {'PSU-01'})
        self.assertNotIn('PSU-02/OUT1', manifest['loads'])
        self.assertNotIn('U02_unit.inc', files)

    def test_dangling_pg_is_saved_but_active_export_rejects(self):
        value = project(self.vm)
        value['sequence_config'] = config.defaults(value)
        value['sequence_config']['units']['PSU-01'].update(wait_for_port='REMOVED/OUT1', pg_threshold_V=5.)
        normalized = network.normalize(value)
        self.assertEqual(normalized['sequence_config']['units']['PSU-01']['wait_for_port'], 'REMOVED/OUT1')
        with self.assertRaisesRegex(ValueError, 'PG'):
            self.structural(normalized)

    def test_constant_power_load_needs_positive_hysteretic_thresholds(self):
        value = project(self.vm)
        base = config.defaults(value)
        for on, off in ((None, None), (5., None), (5., 0.), (5., 5.), (4., 5.)):
            with self.subTest(on=on, off=off):
                changed = copy.deepcopy(base)
                changed['rail_loads']['PSU-01/OUT1'].update(mode='P', on_V=on, off_V=off)
                with self.assertRaises(ValueError):
                    config.normalize(value, changed)
        base['rail_loads']['PSU-01/OUT1'].update(mode='P', on_V=8., off_V=6.)
        value['sequence_config'] = config.normalize(value, base)
        files, manifest = self.structural(value)
        self.assertEqual(manifest['loads']['PSU-01/OUT1']['config']['mode'], 'P')
        self.assertIn('/max(V(LD001_port),6)', files['SystemNetwork.inc'].decode())

    def test_constant_current_requires_positive_thresholds_for_named_and_rail_loads(self):
        for group in ('loads', 'rail_loads'):
            with self.subTest(group=group):
                value = project(self.vm)
                identity = 'PSU-01/OUT1'
                if group == 'loads':
                    identity = 'LOAD-01'
                    value['loads'].append(dict(id=identity, name='结构测试恒流负载', power=24., min=0., max=0., enabled=True))
                    value['connections'].append(dict(id='LINK-002', source=dict(kind='unit', id='PSU-01', output=1),
                                                      target=identity, mode='direct', vf=.3, enabled=True))
                    value = network.normalize(value)
                base = config.defaults(value)
                for on, off in ((None, None), (5., None), (5., 0.), (5., 5.)):
                    changed = copy.deepcopy(base)
                    changed[group][identity].update(mode='I', enabled=True, on_V=on, off_V=off)
                    with self.subTest(on=on, off=off), self.assertRaises(ValueError):
                        config.normalize(value, changed)
                base[group][identity].update(mode='I', enabled=True, on_V=8., off_V=6.)
                value['sequence_config'] = config.normalize(value, base)
                files, manifest = self.structural(value)
                self.assertEqual(manifest['loads'][identity]['config']['mode'], 'I')
                self.assertIn('V(LD001_fraction)*(2)', files['SystemNetwork.inc'].decode())

    def test_standby_is_weighted_out_at_full_load_and_has_low_voltage_compliance(self):
        value = project(self.vm)
        value['sequence_config'] = config.defaults(value)
        value['sequence_config']['rail_loads']['PSU-01/OUT1'].update(
            mode='I', on_V=8., off_V=6., power_W=24., nominal_voltage_V=12., off_current_A=.03)
        files, manifest = self.structural(value)
        text = files['SystemNetwork.inc'].decode()
        load = next(line for line in text.splitlines() if line.startswith('BLD001_LOAD '))
        self.assertEqual(load, 'BLD001_LOAD LD001_port 0 I=if(V(LD001_port)>0,'
                         'V(LD001_fraction)*(2)+(1-V(LD001_fraction))*(0.03*limit(V(LD001_port)/6,0,1)),0)')
        self.assertEqual(load.count('0.03'), 1)
        self.assertIn('低压合规为工程假设', ' '.join(manifest['limitations']))
        self.assert_cards_are_scoped_and_unique(files)

    def test_ldo_quiescent_current_uses_continuous_low_voltage_compliance(self):
        value = workspace.load_project(ROOT/'examples'/'SYSTEM_LDO.json')
        files, manifest = project_files(value)
        compiled = manifest['units']['LDO-01']['compiled_manifest']['sequence_unit']
        scale = compiled['thresholds']['iq_compliance_voltage_v']
        self.assertGreater(scale, 0.)
        stage = files['U01_unit.inc'].decode()
        iq = next(line for line in stage.splitlines() if line.startswith('Biq '))
        self.assertEqual(iq, f'Biq input 0 I={value["units"][0]["spec"]["Iq_max"]:.12g}*limit(V(input)/{scale:.12g},0,1)')
        self.assertNotIn('if(V(input)>0', iq)
        self.assertIn('线性缩放', ' '.join(compiled['limitations']))
        self.assertIn('不是芯片UVLO或实测曲线', ' '.join(compiled['limitations']))

    def test_pg_and_load_delays_use_capacitor_state_without_idt_reset(self):
        value = project(self.vm, self.pcm)
        value['sequence_config'] = config.defaults(value)
        value['sequence_config']['units']['PSU-02'].update(
            wait_for_port='PSU-01/OUT1', pg_threshold_V=8., pg_delay_s=.002)
        files, manifest = self.structural(value)
        text = files['SystemNetwork.inc'].decode()
        self.assertNotIn('idt(', text.casefold())
        self.assertIn('CU02_PG_TIMER U02_PG_age 0 1u', text)
        self.assertIn('BU02_PG_TIMER 0 U02_PG_age I=if(V(U02_PG_READY)>.5,1u,0)', text)
        self.assertIn('SU02_PG_RESET U02_PG_age 0 0 U02_PG_READY SEQ_TIMER', text)
        self.assertIn('(V(U02_PG_age)>=0.002)', text)
        self.assertEqual(manifest['units']['PSU-02']['probes']['pg_age'], 'V(U02_PG_age)')
        self.assertIn('.model SEQ_TIMER SW(Ron=.01 Roff=1e12 Vt=-.5 Vh=.01)', text)
        # The explicit 1 uF state and 10 mOhm reset encode the declared 10 ns
        # logic surrogate; no physical timing result is claimed by this test.
        timer_names = re.findall(r'(?m)^(CLD\d+_TIMER) ', text)
        self.assertEqual(timer_names, ['CLD001_TIMER', 'CLD002_TIMER'])
        for index in (1, 2):
            name = f'LD{index:03d}'
            self.assertIn(f'C{name}_TIMER {name}_age 0 1u', text)
            self.assertIn(f'B{name}_TIMER 0 {name}_age I=if(V({name}_run)>.5,1u,0)', text)
            self.assertIn(f'S{name}_RESET {name}_age 0 0 {name}_run SEQ_TIMER', text)
        self.assert_cards_are_scoped_and_unique(files)

    def test_ldo_soft_start_enters_inc_as_en_controlled_reference_timer(self):
        value = workspace.load_project(ROOT/'examples'/'SYSTEM_LDO.json')
        original, _ = project_files(value)
        self.assertNotIn('Cssage ', original['U01_unit.inc'].decode())
        value['sequence_config'] = config.defaults(value)
        value['sequence_config']['units']['LDO-01']['soft_start_s'] = .0045
        files, manifest = project_files(value)
        stage = files['U01_unit.inc'].decode()
        self.assertIn('Bssrun ssrun 0 V=if(V(en)>.5,1,0)', stage)
        self.assertIn('Cssage ssage 0 1u', stage)
        self.assertIn('Bssage 0 ssage I=if(V(ssrun)>.5,1u,0)', stage)
        self.assertIn('Sssreset ssage 0 0 ssrun SEQ_TIMER', stage)
        self.assertIn('3.3*limit(V(ssage)/0.0045,0,1)', stage)
        self.assertNotIn('idt(', stage.casefold())
        metadata = manifest['units']['LDO-01']['compiled_manifest']['sequence_unit']
        self.assertEqual(metadata['thresholds']['soft_start_s'], .0045)
        self.assertIn('线性提升参考电压', ' '.join(metadata['limitations']))
        self.assert_cards_are_scoped_and_unique(files)

    def test_positive_pg_hysteresis_is_saved_and_schmitt_controls_timer_and_enable(self):
        value = project(self.vm, self.pcm)
        value['sequence_config'] = config.defaults(value)
        row = value['sequence_config']['units']['PSU-02']
        row.update(wait_for_port='PSU-01/OUT1', pg_threshold_V=8., pg_hysteresis_V=1., pg_delay_s=.002)
        with tempfile.TemporaryDirectory(dir=self.artifacts) as folder:
            path = Path(folder)/'pg-hysteresis.json'
            workspace.save_project(value, path)
            reopened = workspace.load_project(path)
        self.assertEqual(reopened['sequence_config']['units']['PSU-02']['pg_hysteresis_V'], 1.)
        files, manifest = self.structural(reopened)
        # The native ASC executes this authoritative included network deck.
        self.assertIn('!.include SystemNetwork.inc', files['SystemSequence.asc'].decode())
        text = files['SystemNetwork.inc'].decode()
        schmitt = next(line for line in text.splitlines() if line.startswith('AU02_PG '))
        self.assertIn('U01_OUT1 ', schmitt)
        self.assertIn('U02_PG_state 0 SCHMITT Vt=7.5 Vh=0.5', schmitt)
        self.assertIn('BU02_PG_TIMER 0 U02_PG_age I=if(V(U02_PG_state)>.5,1u,0)', text)
        en = next(line for line in text.splitlines() if line.startswith('BU02_EN '))
        self.assertIn('(V(U02_PG_state)>.5)&(V(U02_PG_age)>=0.002)', en)
        self.assertNotIn('V(U01_OUT1)>=8', en)
        self.assertEqual(manifest['units']['PSU-02']['probes']['pg_ready'], 'V(U02_PG_state)')
        self.assert_cards_are_scoped_and_unique(files)
        for invalid in (8., 8.1):
            changed = copy.deepcopy(value['sequence_config'])
            changed['units']['PSU-02']['pg_hysteresis_V'] = invalid
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, '迟滞'):
                config.normalize(value, changed)

    def test_old_source_configuration_defaults_to_non_sinking(self):
        value = project(self.vm)
        old = config.defaults(value)
        old['sources']['BUS-01'].pop('sink_current')
        normalized = config.normalize(value, old)
        self.assertIs(normalized['sources']['BUS-01']['sink_current'], False)
        self.assertNotIn('sink_current', old['sources']['BUS-01'])
        for invalid in (None, 0, 1, 'false'):
            changed = copy.deepcopy(old)
            changed['sources']['BUS-01']['sink_current'] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                config.normalize(value, changed)

    def test_source_reverse_sink_switch_preserves_actual_input_capacitors(self):
        default = self.real_files['SystemNetwork.inc'].decode()
        self.assertIn('DS01_BLOCK S01_internal S01_blocked SEQ_SOURCE_D', default)
        self.assertIn('.model SEQ_SOURCE_D D(Ron=1u Roff=1e12 Vfwd=0)', default)
        self.assertIn('RS01 S01_blocked N001 0.05', default)
        self.assertIs(self.real_manifest['sources']['BUS-01']['config']['sink_current'], False)
        value = copy.deepcopy(self.real_project)
        value['sequence_config'] = config.defaults(value)
        value['sequence_config']['sources']['BUS-01']['sink_current'] = True
        with patch('system_sequence_units.compile_unit', side_effect=lambda _spec, namespace: copy.deepcopy(self.compiled[namespace])):
            files, manifest = project_files(value)
        text = files['SystemNetwork.inc'].decode()
        self.assertNotRegex(text, r'(?m)^DS01_BLOCK\s')
        self.assertIn('RS01 S01_internal N001 0.05', text)
        self.assertIs(manifest['sources']['BUS-01']['config']['sink_current'], True)
        for ns in ('U01', 'U02'):
            self.assertEqual(files[ns+'_unit.inc'], self.real_files[ns+'_unit.inc'])
            self.assertIn('XC_IN1 vin_bus 0', files[ns+'_unit.inc'].decode())
        self.assertIn('源端能力假设', ' '.join(manifest['limitations']))
        self.assert_cards_are_scoped_and_unique(files)

    def test_declared_disabled_downstream_suppresses_rated_load(self):
        value = project(self.vm, self.pcm)
        edge = value['connections'][1]
        edge['source'] = dict(kind='unit', id='PSU-01', output=1)
        edge['enabled'] = False
        value['units'][1]['enabled'] = False
        defaults = config.defaults(value)
        self.assertFalse(defaults['rail_loads']['PSU-01/OUT1']['enabled'])
        files, manifest = self.structural(value)
        self.assertNotIn('PSU-01/OUT1', manifest['loads'])
        self.assertIn('PSU-02/OUT1', manifest['loads'])
        self.assertNotIn('LINK-002', manifest['connections'])
        self.assertNotIn('BLOAD', files['U01_unit.inc'].decode())
        # Removing the declaration restores the standalone rated CR fixture.
        value['connections'].pop()
        _, manifest = self.structural(value)
        self.assertEqual(manifest['loads']['PSU-01/OUT1']['config']['mode'], 'R')

    def test_distinct_real_buck_controllers_keep_separate_libraries(self):
        files, manifest = self.real_files, self.real_manifest
        one, two = (manifest['units'][identity]['compiled_manifest'] for identity in ('PSU-01', 'PSU-02'))
        self.assertNotEqual(one['niso']['id'], two['niso']['id'])
        self.assertEqual(one['sequence_unit']['namespace'], 'U01')
        self.assertEqual(two['sequence_unit']['namespace'], 'U02')
        self.assertIn('U01_GenericFlybackPWM.lib', files)
        self.assertIn('U02_GenericFlybackPWM.lib', files)
        self.assertNotEqual(files['U01_GenericFlybackPWM.lib'], files['U02_GenericFlybackPWM.lib'])
        for identity in ('PSU-01', 'PSU-02'):
            meta = manifest['units'][identity]['compiled_manifest']['sequence_unit']
            self.assertEqual(meta['model_scope'], 'switching-power-stage-with-generic-behavioral-controller')
            self.assertEqual(meta['common_return'], '0')
        self.assert_cards_are_scoped_and_unique(files)

    def test_actual_capacitor_banks_survive_and_extra_load_cap_is_independent(self):
        files, manifest = self.real_files, self.real_manifest
        stage = files['U01_unit.inc'].decode('ascii')
        for ref, parameter, capacitance, esr, esl in (
                ('XC_IN1', 'C_IN1', .000123, .041, 3e-9), ('XC_IN2', 'C_IN2', 8.2e-6, .075, 2e-9),
                ('XC_O1', 'C_O1', .000221, .031, 4e-9), ('XC_O1_2', 'C_O1_2', 33e-6, .052, 5e-9)):
            self.assertRegex(stage, r'(?m)^'+ref+r' .*\bC=\{'+parameter+r'_C\} ESR=\{'+parameter+r'_ESR\} ESL=\{'+parameter+r'_ESL\}')
            for suffix, expected in (('C', capacitance), ('ESR', esr), ('ESL', esl)):
                match = re.search(r'(?m)^\.param '+parameter+'_'+suffix+r'=(\S+)$', stage)
                self.assertIsNotNone(match)
                self.assertAlmostEqual(float(match[1]), expected, delta=max(abs(expected)*1e-10, 1e-18))
        self.assertNotRegex(files['SystemNetwork.inc'].decode(), r'(?m)^CLD\d+\s')
        changed = copy.deepcopy(self.real_project)
        changed['sequence_config'] = config.defaults(changed)
        changed['sequence_config']['rail_loads']['PSU-01/OUT1'].update(input_capacitance_F=17e-6, input_esr_ohm=.082, bleeder_ohm=1234.)
        # Reuse the two genuinely compiled frozen units; this mutation adds no
        # converter inputs, and must not trigger a converter recalculation.
        with patch('system_sequence_units.compile_unit', side_effect=lambda _spec, namespace: copy.deepcopy(self.compiled[namespace])):
            more, expanded = project_files(changed)
        self.assertEqual(more['U01_unit.inc'], files['U01_unit.inc'])
        self.assertEqual(more['U02_unit.inc'], files['U02_unit.inc'])
        text = more['SystemNetwork.inc'].decode()
        self.assertIn('CLD001 LD001_port 0 1.7e-05 Rser=0.082', text)
        self.assertIn('RLD001_BLEED LD001_port 0 1234', text)
        self.assertEqual(len(re.findall(r'(?m)^CLD\d+\s', text)), 1)
        self.assertEqual(expanded['loads']['PSU-01/OUT1']['config']['input_capacitance_F'], 17e-6)
        self.assert_cards_are_scoped_and_unique(more)

    def test_all_topology_scopes_are_projected_with_explicit_ldo_boundary(self):
        names = {'BUCK': '24W_BUCK_VM_TPS40200.json', 'BOOST': '24W_BOOST_PCM_LM5022.json',
                 'FLYBACK': '40W_CCM_FLYBACK.json', 'QR-FLYBACK': '90W_QR_L6565_300V_TUNED.json',
                 'ACF-FORWARD': '33W_3OUT_ACF_MP6005.json'}
        self.assertEqual(set(names), set(SUPPORTED_TOPOLOGIES))
        for topology, filename in names.items():
            with self.subTest(topology=topology):
                files, manifest = self.structural(project(example(filename)))
                compiled = manifest['units']['PSU-01']['compiled_manifest']
                self.assertEqual(compiled['topology'], topology)
                self.assertEqual(compiled['sequence_unit']['model_scope'], 'switching-power-stage-with-generic-behavioral-controller')
                self.assertIn('STRUCTURAL FIXTURE', ' '.join(manifest['limitations']))
                self.assert_cards_are_scoped_and_unique(files)
        ldo = workspace.load_project(ROOT/'examples'/'SYSTEM_LDO.json')
        files, manifest = project_files(ldo)
        compiled = manifest['units']['LDO-01']['compiled_manifest']
        self.assertEqual(compiled['sequence_unit']['model_level'], 'linear-regulator-behavior')
        self.assertIsNone(compiled['sequence_unit']['thresholds']['cycle_cs_ceiling_v'])
        self.assertIn('不是厂家', ' '.join(compiled['sequence_unit']['limitations']))
        self.assert_cards_are_scoped_and_unique(files)

    def test_probe_paths_subcircuit_pins_and_generated_file_hashes(self):
        files, manifest = self.real_files, self.real_manifest
        network_text = files['SystemNetwork.inc'].decode()
        for identity, unit in manifest['units'].items():
            instance = unit['instance']
            ns = unit['compiled_manifest']['sequence_unit']['namespace']
            pins = unit['compiled_manifest']['sequence_unit']['pins']
            exported_pins = dict(input=f'V({ns}_IN)', en=f'V({ns}_EN)', vcc=f'V({ns}_VCC)',
                                 **{f'out{i}': f'V({ns}_internal_out{i})' for i in range(1, len(unit['outputs'])+1)})
            for key, value in unit['probes'].items():
                for probe in leaves(value):
                    if key in exported_pins:
                        self.assertEqual(probe, exported_pins[key])
                    else:
                        self.assertRegex(probe, r'^V\('+instance+r':[A-Za-z0-9_]+(?::[A-Za-z0-9_]+)*\)$')
                    self.assertIn(probe, network_text)
            currents = unit['compiled_manifest']['sequence_unit']['current_probes']
            self.assertEqual(currents['representation'], 'independent-voltage-monitor')
            self.assertEqual(currents['scale_A_per_V'], 1.)
            self.assertIn('primary', unit['probes']['currents'])
            for key, branch in currents['branches'].items():
                monitor = currents['nodes'][key]
                self.assertIn(f'{monitor} 0 V=I({branch})', files[ns+'_unit.inc'].decode())
            self.assertIn('.subckt '+ns+'_UNIT '+' '.join(pins), files[ns+'_unit.inc'].decode())
            call = next(line for line in network_text.splitlines() if line.startswith(instance+' '))
            self.assertEqual(len(call.split()), len(pins)+2)
            self.assertEqual(call.split()[-1], ns+'_UNIT')
            self.assertIn(unit['input_current_probe'], network_text)
            self.assertIn(unit['en_probe'], network_text)
        for name, evidence in manifest['files'].items():
            self.assertEqual(evidence['bytes'], len(files[name]))
            self.assertEqual(evidence['sha256'], hashlib.sha256(files[name]).hexdigest())
        self.assertNotRegex(network_text, r'(?im)^\.step\b')
        self.assertEqual(sum(line.startswith('.tran ') for line in network_text.splitlines()), 1)
        self.assertNotIn('C:\\', network_text)
        self.assertNotIn('E:\\', network_text)

    def test_export_writes_the_exact_reviewed_bytes(self):
        with tempfile.TemporaryDirectory(dir=self.artifacts) as folder:
            with patch('system_sequence_export.project_files', return_value=(copy.deepcopy(self.real_files), copy.deepcopy(self.real_manifest))):
                manifest = export_project(self.real_project, folder)
            self.assertEqual(manifest, self.real_manifest)
            for filename, data in self.real_files.items():
                self.assertEqual((Path(folder)/filename).read_bytes(), data)
            self.assertEqual({path.name for path in Path(folder).iterdir()}, set(self.real_files))

    def test_unsupported_topology_rejects_before_calculation(self):
        changed = project(self.vm)
        changed['units'][0]['spec']['topology'] = 'BUCK-BOOST'
        with patch('design_engine.service.calculate_parameters', side_effect=AssertionError('unsupported must not calculate')):
            with self.assertRaisesRegex(ValueError, '不支持'):
                project_files(changed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
