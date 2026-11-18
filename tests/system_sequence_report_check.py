"""Synthetic report projection checks, with no solver or real-waveform claim.

The three display samples deliberately disagree with the supplied full-data
statistics. This is a presentation fixture, not an electrical simulation.
Word assertions inspect content/OOXML only; page rendering is separate QA.
"""
from contextlib import ExitStack
import base64
import copy
import csv
from html.parser import HTMLParser
import json
from pathlib import Path
import queue
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import system_sequence_report as report

LABEL = 'SYNTHETIC PRESENTATION FIXTURE - NOT A SIMULATION RESULT'


def synthetic_fixture():
    source = dict(on_s=0., rise_s=.002, off_s=.025, fall_s=.002,
                  resistance_ohm=.05, current_limit_A=None, sink_current=False)
    unit_config = dict(vin_on_V=None, vin_off_V=None, enable_s=.004, disable_s=.031,
                       soft_start_s=None, wait_for_port='BUS-01', pg_threshold_V=8.,
                       pg_hysteresis_V=1., pg_delay_s=.002)
    manifest = dict(settings=dict(stop_s=.04, vin_case='max'), max_step_s=100e-9,
        source_project_sha256='a'*64, configuration={}, limitations=[LABEL, '合成边界 <未知> & 未验证', LABEL],
        sources={
            'BUS-01': dict(name='合成<源>&"', config=source, voltage_probe='V(src)', current_probe='I(src)'),
            'BUS-02': dict(name='合成备用源', config=dict(source, current_limit_A=10., sink_current=True), voltage_probe='V(backup)', current_probe='I(backup)')},
        units={'PSU-01': dict(config=unit_config,
            compiled_manifest=dict(topology='BUCK', sequence_unit=dict(thresholds=dict(soft_start_s=.0035))),
            input_current_probe='I(unit)', en_probe='V(en)',
            outputs=[dict(id=1, voltage_probe='V(out)')],
            probes=dict(sense='V(cs)', fault='V(fault)', controller=dict(filtered_cs='V(filtered)', cycle_limit='V(ilim)')))},
        connections={
            'LINK-001': dict(source='BUS-01', target='OR-01', current_probe='I(edge1)'),
            'LINK-002': dict(source='BUS-02', target='OR-01', current_probe='I(edge2)')},
        loads={'LOAD-01': dict(config=dict(on_V=9., off_V=7.), state_probe='V(load_state)')})
    output = dict(id=1, first_90pct_s=.0095, voltage_peak_V=12.75, voltage_final_V=.125,
                  voltage_at_disable_V=11.5, decay_10pct_s=None, residual_V=.125,
                  shutdown_observation_s=.009)
    unit = dict(id='PSU-01', topology='BUCK', enable=dict(first_on_s=.004, on_count=7, last_off_s=.031),
        outputs=[output], input_current_peak_A=29.375,
        branch_current_peaks=dict(primary=dict(peak_A=31.625)),
        ocp=dict(raw_cs_peak_V=.419, filtered_cs_peak_V=.377, sense_resistor_ohm=.02,
                 equivalent_sense_current_peak_A=20.95, fault_observed=False,
                 cycle_limit=dict(hit=True, observed_cycle_count=123456)))
    result = dict(status='completed', observed_end_s=.04,
        summary=dict(
            sources=[dict(id='BUS-01', supply_current_peak_A=37.125, supply_current_peak_s=.00125,
                          reverse_current_peak_A=1.875, current_limit_A=None, current_limit_exceeded=None),
                     dict(id='BUS-02', supply_current_peak_A=13.25, supply_current_peak_s=.022,
                          reverse_current_peak_A=.5, current_limit_A=10., current_limit_exceeded=True)],
            units=[unit],
            loads=[dict(id='LOAD-01', mode='P', first_power_s=.0115, current_peak_A=2.75,
                        state=dict(on_count=11, first_on_s=.011))],
            connections=[dict(id='LINK-001', source='BUS-01', target='OR-01', current_peak_A=36.5,
                              reverse_current_peak_A=.2, first_forward_s=.002, last_forward_s=.024),
                         dict(id='LINK-002', source='BUS-02', target='OR-01', current_peak_A=12.5,
                              reverse_current_peak_A=.1, first_forward_s=.024, last_forward_s=.032)]),
        waveforms=dict(time=[0., .02, .04]),
        events=[dict(time_s=.012345, id='PSU-01', type='cycle_limit_observed', observed_cycle_count=123456)],
        failure_reasons=[], log_warnings=['SYNTHETIC warning one', 'SYNTHETIC numerical tolerance warning'], limitations=[LABEL])
    for probe in ('V(src)', 'I(src)', 'V(backup)', 'I(backup)', 'I(unit)', 'V(en)', 'V(out)',
                  'V(cs)', 'V(fault)', 'V(filtered)', 'V(ilim)', 'I(edge1)', 'I(edge2)', 'V(load_state)'):
        result['waveforms'][probe.casefold()] = [0., .001, 0.]
    return manifest, result


class HtmlProjection(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tables, self.images = [], []
        self.table = self.row = self.cell = None
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        if tag == 'table':
            self.table = []
        elif tag == 'tr':
            self.row = []
        elif tag in ('th', 'td'):
            self.cell = ''
        elif tag == 'img':
            self.images.append(dict(attributes))

    def handle_data(self, data):
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr':
            self.table.append(self.row)
            self.row = None
        elif tag == 'table':
            self.tables.append(self.table)
            self.table = None


class ReportProjectionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts = ROOT/'artifacts'/'system-sequence-report-check'
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(dir=cls.artifacts)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        cls.manifest, cls.result = synthetic_fixture()
        cls.before = copy.deepcopy((cls.manifest, cls.result))
        with ExitStack() as stack:
            for target in ('design_engine.service.calculate_parameters', 'system_sequence_units.compile_unit',
                           'system_sequence_analysis.analyze', 'spice_runtime._run'):
                stack.enter_context(patch(target, side_effect=AssertionError('reports must not solve or reanalyze')))
            cls.output = report.write(cls.folder/'synthetic', cls.manifest, cls.result)
        cls.blocks = list(report.sections(cls.manifest, cls.result))
        cls.html = Path(cls.output['html_path']).read_text('utf-8')
        cls.parsed = HtmlProjection(cls.html)
        from docx import Document
        cls.document = Document(cls.output['word_path'])

    def test_html_csv_and_word_use_exactly_the_same_section_metrics(self):
        tables = [[list(map(str, headers))]+[list(map(str, row)) for row in rows]
                  for _, headers, rows in self.blocks]
        self.assertEqual(self.parsed.tables, tables)
        with Path(self.output['csv_path']).open(encoding='utf-8-sig', newline='') as stream:
            csv_rows = list(csv.reader(stream))
        expected = []
        for title, headers, rows in self.blocks:
            expected.extend([[title], list(map(str, headers)), *[list(map(str, row)) for row in rows], []])
        self.assertEqual(csv_rows, expected)
        word_tables = [[[cell.text for cell in row.cells] for row in table.rows] for table in self.document.tables]
        self.assertEqual(word_tables, [table for table in tables if len(table)>1])
        titles = [paragraph.text for paragraph in self.document.paragraphs if paragraph.style.name == 'Heading 1']
        self.assertEqual(titles[0], '1 关键结论')
        self.assertEqual([title.split(' ', 1)[1] for title in titles[1:1+len(self.blocks)]],
                         [title.split(' ', 1)[1] for title, _, _ in self.blocks])

    def test_display_samples_do_not_replace_full_data_statistics_or_counts(self):
        blocks = {title: rows for title, _headers, rows in self.blocks}
        startup = blocks['4 启动时序与输出电压'][0]
        self.assertEqual(startup, ['PSU-01/OUT1', '4', '9.5', '7', '12.75', '0.125'])
        source = blocks['5 源浪涌与反向电流'][0]
        self.assertEqual(source, ['BUS-01', '37.125', '1.25', '1.875', '未提供', '未知'])
        protection = dict(blocks['6.1 PSU-01 电流与保护观察'])
        self.assertEqual(protection['逐周期限流正向证据'], '已观察到；采样周期下界 123456')
        self.assertEqual(protection['primary 实际支路峰值 A'], '31.625')
        self.assertEqual(protection['FAULT保护状态'], '本次未观察到')
        self.assertEqual(blocks['7 负载耗功与重复启动'][0][-1], '11')
        self.assertEqual(len(self.result['waveforms']['time']), 3)
        self.assertLess(max(self.result['waveforms']['i(src)']), 1.)
        self.assertEqual((self.manifest, self.result), self.before)
        self.assertIn('表内峰值、事件和计数直接统计完整RAW', self.html)

    def test_html_embeds_images_and_word_contains_the_same_png_bytes(self):
        images = self.parsed.images
        self.assertGreaterEqual(len(images), 6)
        self.assertEqual(len(images), len(self.output['images']))
        embedded = []
        for item, path in zip(images, self.output['images']):
            self.assertTrue(item['src'].startswith('data:image/png;base64,'))
            self.assertNotIn('http', item['src'][:30])
            blob = base64.b64decode(item['src'].split(',', 1)[1], validate=True)
            self.assertTrue(blob.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(blob, Path(path).read_bytes())
            embedded.append(blob)
        with ZipFile(self.output['word_path']) as archive:
            self.assertIsNone(archive.testzip())
            media = [archive.read(name) for name in archive.namelist() if name.startswith('word/media/')]
        self.assertEqual(set(media), set(embedded))
        self.assertEqual(len(self.document.inline_shapes), len(images))

    def test_frozen_model_notes_are_scoped_deduplicated_in_all_formats(self):
        manifest=copy.deepcopy(self.manifest)
        note='振荡器age有限回零；合成声明，不代表物理仿真'
        manifest['units']['PSU-01']['compiled_manifest'].update(model_version='synthetic-1.3',approximation_notes=[note,note])
        manifest['units']['PSU-02']=copy.deepcopy(manifest['units']['PSU-01'])
        with patch.object(report,'figures',side_effect=AssertionError('projection only')):
            output=report.write(self.folder/'frozen-models',manifest,self.result,plots=[])
        blocks={title:rows for title,_headers,rows in report.sections(manifest,self.result)}
        rows=blocks['1.1 冻结单元模型与近似']
        self.assertIn(['PSU-01、PSU-02',note],rows)
        self.assertEqual(sum(row[1]==note for row in rows),1)
        html=Path(output['html_path']).read_text('utf8')
        self.assertEqual(html.count(note),1)
        from docx import Document
        cells=[c.text for t in Document(output['word_path']).tables for r in t.rows for c in r.cells]
        self.assertEqual(cells.count(note),1)
        with Path(output['csv_path']).open(encoding='utf-8-sig',newline='') as stream:
            csv_rows=list(csv.reader(stream))
        self.assertEqual(csv_rows.count(['PSU-01、PSU-02',note]),1)

    def test_unknowns_and_model_boundaries_do_not_turn_into_protection_pass(self):
        blocks = {title: rows for title, _headers, rows in self.blocks}
        startup = blocks['3 各电源启动条件'][0]
        self.assertEqual(startup[2], '未提供 / 未提供')
        self.assertEqual(startup[4], '3.5', 'known controller soft-start is a labelled fallback')
        shutdown = blocks['8 关机与残余电压'][0]
        self.assertEqual(shutdown, ['PSU-01/OUT1', '31', '11.5', '未提供', '0.125', '9'])
        protection = dict(blocks['6.1 PSU-01 电流与保护观察'])
        self.assertIn('逐周期限流见采样证据', protection['保护评估'])
        self.assertIn('<h2>关键结论</h2>', self.html)
        self.assertLess(self.html.index('<h2>关键结论</h2>'), self.html.index('试验条件与模型范围'))
        self.assertEqual(self.html.count(LABEL), 1, 'repeated limitations are presented once')
        self.assertNotIn('合成<源>', self.html)
        self.assertIn('合成&lt;源&gt;&amp;&quot;', self.html)
        self.assertEqual(blocks['2 外部输入源'][0][1], '合成<源>&"')
        warnings = dict(blocks['1 试验条件与模型范围'])['求解器警告']
        self.assertTrue(warnings.startswith('2 条'))
        self.assertIn('Flyback.log', warnings)

    def test_events_csv_preserves_events_and_not_an_inferred_display_count(self):
        with (Path(self.output['csv_path']).parent/'events.csv').open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.reader(stream))
        self.assertEqual(rows[0], ['time_ms', 'node_id', 'event', 'details'])
        self.assertEqual(rows[1][:3], ['12.345', 'PSU-01', 'cycle_limit_observed'])
        self.assertIn('123456', rows[1][3])
        self.assertEqual(len(rows), len(self.result['events'])+1)

    def test_failure_receipt_is_readable_in_every_output_and_escapes_html(self):
        failed = dict(status='failed', failure_reasons=['合成失败：RAW未完成 <script>alert(1)</script>'],
                      summary=dict(sources=[], units=[], loads=[], connections=[]),
                      waveforms=dict(time=[]), events=[], limitations=[LABEL])
        with patch.object(report, 'figures', side_effect=AssertionError('empty failure must not require plot generation')):
            output = report.write(self.folder/'failure', {}, failed, plots=[])
        html = Path(output['html_path']).read_text('utf-8')
        self.assertIn('仿真未完成', html)
        self.assertIn('RAW未完成', html)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        from docx import Document
        document = Document(output['word_path'])
        text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn(failed['failure_reasons'][0], text)
        self.assertIn('本次无记录', text)
        self.assertIn(LABEL, text)
        with Path(output['csv_path']).open(encoding='utf-8-sig', newline='') as stream:
            csv_rows = list(csv.reader(stream))
        self.assertIn(['运行状态', 'failed'], csv_rows)
        self.assertIn(['未完成原因', failed['failure_reasons'][0]], csv_rows)
        self.assertEqual(output['images'], [])

    def test_ldo_report_uses_linear_observations_without_switching_cs_rows(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['units'] = {'LDO-01': dict(config=copy.deepcopy(manifest['units']['PSU-01']['config']),
            compiled_manifest=dict(topology='LDO', sequence_unit=dict(thresholds=dict(soft_start_s=.0045))))}
        result = copy.deepcopy(self.result)
        result['summary']['units'] = [dict(id='LDO-01', topology='LDO', input_current_peak_A=.125,
            enable=dict(first_on_s=None, on_count=0, last_off_s=None), outputs=[], ocp={})]
        blocks = list(report.sections(manifest, result))
        linear = next(rows for title, _headers, rows in blocks if title == '6.1 LDO-01 线性稳压器观察')
        indicators = dict(linear)
        self.assertEqual(indicators['输入端全程峰值 A'], '0.125')
        self.assertIn('LDO 压差和限流行为估算', indicators['保护评估'])
        self.assertFalse(any('CS' in str(row) or '逐周期' in str(row) for row in linear))
        output = report.write(self.folder/'ldo', manifest, result, plots=[])
        expected = [[list(map(str, headers))]+[list(map(str, row)) for row in rows] for _title, headers, rows in blocks]
        self.assertEqual(HtmlProjection(Path(output['html_path']).read_text('utf-8')).tables, expected)
        from docx import Document
        document = Document(output['word_path'])
        actual = [[[cell.text for cell in row.cells] for row in table.rows] for table in document.tables]
        self.assertEqual(actual, [table for table in expected if len(table)>1])

    def test_html_only_return_paths_point_to_real_files(self):
        with patch.object(report, 'figures', side_effect=AssertionError('explicit plots must be reused')):
            output = report.write(self.folder/'html-only', self.manifest, self.result, word=False, plots=[])
        self.assertEqual(output['report_path'], output['html_path'])
        self.assertIsNone(output['word_path'])
        for key in ('report_path', 'html_path', 'csv_path'):
            self.assertTrue(Path(output[key]).is_file(), key)
        self.assertEqual(HtmlProjection(Path(output['html_path']).read_text('utf-8')).tables, self.parsed.tables)

    def test_actual_source_protection_and_staged_load_report_share_all_formats(self):
        manifest,result=copy.deepcopy((self.manifest,self.result))
        manifest['sources']['BUS-01']['config'].update(protection_mode='hiccup',current_limit_A=2.,
            trip_delay_s=.001,retry_s=.005,voltage_profile=[dict(time_s=0.,level=0.),
                dict(time_s=.002,level=1.),dict(time_s=.015,level=0.),dict(time_s=.025,level=1.)])
        manifest['sources']['BUS-01'].update(limit_active_probe='V(slimit)',fault_probe='V(sfault)')
        source=result['summary']['sources'][0]
        source.update(protection_mode='hiccup',protection_model_executed=True,protection_observations_complete=True,
            current_limit_A=2.,current_limit_exceeded=False,
            limit_state=dict(on_count=4,first_on_s=.0012,active_time_s=.0048),
            fault_state=dict(on_count=3,off_count=2))
        # Keep the other source below threshold to isolate the new findings.
        result['summary']['sources'][1]['current_limit_exceeded']=False
        plan=[dict(name='固件启动',after_s=0.,ramp_s=.0001,mode='I',power_W=.15),
              dict(name='通信运行',after_s=.003,ramp_s=.0005,mode='I',power_W=.4)]
        manifest['loads']['LOAD-01']['config'].update(stages=plan,delay_s=.001,off_current_A=.002,
            ready_conditions=[dict(port='PSU-01/OUT1',on_V=4.5,off_V=4.1)])
        manifest['loads']['LOAD-01'].update(stage_probe='V(stage)',ready_probe='V(ready)',
            voltage_probe='V(loadv)',current_probe='I(load)',active_current_probe='V(active)')
        result['summary']['loads'][0].update(active_current_peak_A=.1212,
            stage_observations=dict(observed=True,reset_count=2,restart_count=1,final_index=2,
                stages=[dict(index=1,first_entry_s=.006,last_entry_s=.026,entry_count=2),
                        dict(index=2,first_entry_s=.009,last_entry_s=.029,entry_count=2)]))
        for probe in ('V(slimit)','V(sfault)','V(stage)','V(ready)','V(loadv)','I(load)','V(active)'):
            result['waveforms'][probe.casefold()]=[0.,1.,0.]
        result['events'].append(dict(id='LOAD-01',type='load_stage_enter',time_s=.009,
                                     stage_index=2,stage_name='通信运行',configured_after_s=.003))
        before=copy.deepcopy((manifest,result))
        output=report.write(self.folder/'v2-staged',manifest,result)
        blocks=list(report.sections(manifest,result))
        tables=[[list(map(str,headers))]+[list(map(str,row)) for row in rows] for _,headers,rows in blocks]
        html=Path(output['html_path']).read_text('utf-8')
        parsed=HtmlProjection(html)
        self.assertEqual(parsed.tables,tables)
        from docx import Document
        doc=Document(output['word_path'])
        self.assertEqual([[[c.text for c in r.cells] for r in table.rows] for table in doc.tables],
                         [table for table in tables if len(table)>1])
        rows_by_title={title:rows for title,headers,rows in blocks}
        self.assertEqual(rows_by_title['2 外部输入源'][0][2:4],['显式时序','见下表'])
        self.assertEqual(rows_by_title['5.2 源限流与保护实际动作'][0][2:5],['1.2','4.8','3 / 2'])
        self.assertEqual(rows_by_title['7.1.1 阶段计划与实际进入'][1],['2 · 通信运行','I / 0.4','3 / 0.5','9 / 29','2'])
        details=dict(rows_by_title['7.1 LOAD-01 复位与真实负载条件'])
        self.assertEqual(details['全端口 / 运行部分峰值电流 A'],'2.75 / 0.1212')
        self.assertIn('PSU-01/OUT1',details['额外多轨就绪条件'])
        self.assertIn('开关级瞬态仿真',html)
        self.assertNotIn('本模型未执行源限流','\n'.join(report.findings(result)))
        self.assertGreaterEqual(len(output['images']),len(self.output['images'])+2)
        self.assertTrue(any('source-1-protection.png' in p for p in output['images']))
        self.assertTrue(any('load-1-stages.png' in p for p in output['images']))
        self.assertEqual((manifest,result),before)

    def test_ui_displays_dict_summary_and_opens_the_existing_returned_report(self):
        # Headless widget substitutes exercise the same poll/view_report code.
        # No native app or external program is opened by this test.
        from system_sequence_ui import SystemSequenceDialog
        class Status:
            def __init__(self):
                self.value = ''
            def set(self, value):
                self.value = value
        class Button:
            def configure(self, **options):
                self.options = options
        messages = []
        result = dict(status='completed', directory=str(Path(self.output['report_path']).parent),
                      report_path=self.output['report_path'], html_path=self.output['html_path'],
                      summary=copy.deepcopy(self.result['summary']))
        dialog = SimpleNamespace(mailbox=queue.Queue(), poll_id=None, job=None, result={}, terminal_received=False,
            directory=None, status=Status(), append=messages.append, open_report=Button(), open_folder=Button(),
            run_button=Button(), cancel_button=Button(), close_pending=False, _open=Mock())
        dialog.mailbox.put(('done', result))
        SystemSequenceDialog.poll(dialog)
        self.assertIsInstance(dialog.result['summary'], dict)
        self.assertEqual(dialog.result['summary'], self.result['summary'])
        rendered = json.loads(messages[-1])
        self.assertEqual(rendered['summary']['units'][0]['enable']['on_count'], 7)
        self.assertEqual(dialog.open_report.options, {'state': 'normal'})
        self.assertEqual(dialog.open_folder.options, {'state': 'normal'})
        SystemSequenceDialog.view_report(dialog)
        dialog._open.assert_called_once_with(self.output['report_path'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
