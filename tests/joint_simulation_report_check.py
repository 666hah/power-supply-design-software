"""Verify joint report evidence gaps and single-package Word composition."""
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image

from joint_simulation_report import write_joint_report, _archived_design_bundle, _field_images


def png():
    stream = BytesIO()
    Image.new('RGB', (240, 90), 'white').save(stream, format='PNG')
    return stream.getvalue()


def field_record(report):
    return dict(topology='FLYBACK', report_path=str(report), field={
        'port_order': ['P', 'OUT1'], 'L_ports_H': [[100e-6, 45e-6], [45e-6, 25e-6]],
        'k_ports': [[1, .9], [.9, 1]], 'primary_self_H': 100e-6,
        'primary_short_H': 19e-6}, validation={}, model_conditions={
        'material': {'name': 'TEST', 'relative_permeability': 2400, 'temperature_C': 25, 'bias_current_A': 0},
        'core': {'calculator_core_model': 'TEST', 'total_gap_m': .001},
        'solver': {'mesh_profile': 'test', 'air_radius_m': .05},
        'bobbin': {'axial_window_m': .012, 'radial_window_m': .005},
        'layers': [['P', 6], ['OUT1', 12]], 'windings': [['P', 6], ['OUT1', 12]]})


def failed_spice():
    from spice_export import normalize_settings
    return dict(schema='powerdesign-spice-comparison-2', model='UNIT-TEST', topology='FLYBACK',
                settings=normalize_settings({}), cases=[dict(
                    id='Vinmin_标称负载', voltage=20, fault_test=False, complete=False,
                    error='本测试模拟超时，不是实际LTspice数据', measurements={}, loop={}, cross={})])


def design_chapters(doc, *, embedded):
    chapters = []
    for element in doc.element.body:
        if element.tag == qn('w:p'):
            para = Paragraph(element, doc)
            number, _, name = para.text.partition(' ')
            if embedded and para.style.name == 'Heading 1':
                if number == '5':
                    break
            if not embedded and para.style.name == 'Heading 1' and name == '工程验收与证据':
                break
            is_chapter = (para.style.name == 'Heading 2' and number.startswith('4.') if embedded
                          else para.style.name == 'Heading 1')
            if is_chapter:
                chapters.append((para, []))
                continue
        if chapters and element.tag in (qn('w:p'), qn('w:tbl')):
            if not element.xpath('./w:pPr/w:sectPr'):
                chapters[-1][1].append(element)
    return chapters


def chapter_contents(doc, elements):
    contents = []
    for element in elements:
        if element.tag == qn('w:tbl'):
            table = Table(element, doc)
            contents.append(('table', [[cell.text for cell in row.cells] for row in table.rows]))
        else:
            para = Paragraph(element, doc)
            if para.style.name in ('Report Contents Title', 'Report Contents Entry'):
                continue
            if element.xpath('./m:oMath | ./m:oMathPara'):
                contents.append(('equation', element.xpath('.//m:t/text()')))
            elif element.xpath('.//wp:extent'):
                contents.append(('figures', [(extent.get('cx'), extent.get('cy'))
                                             for extent in element.xpath('.//wp:extent')]))
            elif para.text:
                contents.append(('paragraph', re.sub(r'^(图|表) [\d.]+-\d+  ', r'\1 ', para.text)))
    return contents


class JointReportChecks(unittest.TestCase):
    def test_early_failure_remains_visible_without_invented_evidence(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp:
            path = Path(tmp) / '联合.docx'
            record = dict(status='failed', stages=[dict(name='场仿真', status='failed', error='窗口超限')])
            receipt = write_joint_report(path, record)
            doc = Document(path)
            text = '\n'.join(p.text for p in doc.paragraphs)
            self.assertIn('电磁仿真，电路仿真，设计计算联合报告', text)
            tables = '\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
            self.assertIn('窗口超限', tables)
            self.assertIn('场解数据待补', text)
            self.assertIn('电路仿真数据待补', text)
            titles = [p.text for p in doc.paragraphs if p.style.name == 'Heading 1']
            self.assertEqual(titles.count('1 评审结论'), 1)
            self.assertIn('目录', text)
            self.assertEqual(set(doc.element.xpath('.//w:hyperlink/@w:anchor')),
                             set(doc.element.xpath('.//w:bookmarkStart/@w:name')))
            self.assertTrue(receipt['incomplete'])
            self.assertFalse(receipt['circuit_evidence_available'])

    def test_local_and_embedded_field_images_are_embedded_not_linked(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp:
            folder = Path(tmp)
            (folder / 'field.png').write_bytes(png())
            report = folder / 'report.html'
            report.write_text('<img src="field.png" alt="本地场图"><img src="data:image/png;base64,' +
                              base64.b64encode(png()).decode() + '" alt="内嵌场图">' +
                              '<img src="https://example.com/private.png" alt="远程图">' +
                              '<img src="../outside.png" alt="越界图">', 'utf-8')
            images, notes = _field_images(report)
            self.assertEqual(len(images), 2)
            self.assertEqual(len(notes), 2)
            record = dict(status='partial', field=field_record(report), margin={
                'factor': 1.25, 'off_diagonal_scale': .97, 'port_order': ['P', 'OUT1'],
                'primary_self_H': 100e-6, 'original_primary_short_H': 19e-6,
                'adopted_primary_short_H': 23.75e-6,
                'adopted_L_ports_H': [[100e-6, 43.660e-6], [43.660e-6, 25e-6]],
                'adopted_k_ports': [[1, .8732], [.8732, 1]]})
            path = folder / '联合.docx'
            result = write_joint_report(path, record)
            self.assertEqual(result['figures'], 2)
            self.assertGreaterEqual(result['equations'], 2)
            with ZipFile(path) as archive:
                xml = archive.read('word/document.xml').decode('utf-8')
                self.assertNotIn('r:link=', xml)
                self.assertIn('r:embed=', xml)
            tables = '\n'.join(c.text for t in Document(path).tables for row in t.rows for c in row.cells)
            self.assertIn('23.75', tables)
            self.assertIn('45 → 43.66', tables)
            self.assertIn('网格收敛待验证', '\n'.join(p.text for p in Document(path).paragraphs))

    def test_spice_append_preserves_styles_sections_equations_and_footer(self):
        from docx_layout import new_document, equation, figure
        from spice_comparison_report import write_report
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp:
            doc = new_document('组合验证', '测试', '前一章节')
            equation(doc, 'P=V×I')
            figure(doc, png(), '第一节图片')
            original_size = doc.styles['Normal'].font.size
            original_footer = doc.sections[0].footer.part.partname
            write_report(None, failed_spice(), document=doc, save=False)
            self.assertEqual(doc.styles['Normal'].font.size, original_size)
            self.assertEqual(len(doc.sections), 2)
            self.assertAlmostEqual(doc.sections[0].page_width.mm, 210, places=1)
            self.assertAlmostEqual(doc.sections[0].page_height.mm, 297, places=1)
            self.assertAlmostEqual(doc.sections[-1].page_width.mm, 297, places=1)
            self.assertAlmostEqual(doc.sections[-1].page_height.mm, 210, places=1)
            self.assertNotEqual(doc.sections[-1].footer.part.partname, original_footer)
            self.assertGreaterEqual(len(doc.element.xpath('.//m:oMath')), 2)
            self.assertIn('本测试模拟超时', '\n'.join(p.text for p in doc.paragraphs))
            path = Path(tmp) / '组合.docx'
            doc.save(path)
            reopened = Document(path)
            self.assertEqual(len(reopened.sections), 2)
            ids = [n.get('id') for n in reopened.element.xpath('.//wp:docPr')]
            self.assertEqual(len(ids), len(set(ids)))
            for node in reopened.element.iter():
                rid = node.get(qn('r:embed'))
                if rid:
                    self.assertIn(rid, reopened.part.rels)

    def test_complete_design_snapshot_is_consumed_without_recomputation(self):
        from unittest.mock import patch
        from design_engine.service import calculate, export_report
        config = json.loads((ROOT / 'examples/40W_CCM_FLYBACK.json').read_text('utf-8'))
        run = calculate(config, analysis='endpoints', include_loop=True,
                        include_efficiency=True, include_cross_regulation=False)
        before = deepcopy(config)
        record = dict(status='partial', stages=[dict(name='电路仿真', status='failed', error='测试超时')],
                      adopted_config=config, circuit={'evidence': failed_spice()})
        with (tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp,
              patch('design_engine.service.calculate', side_effect=AssertionError('renderer must not calculate')),
              patch('report_docx.compute_design', side_effect=AssertionError('renderer must use saved efficiency')),
              patch('joint_simulation_report._archived_design_bundle', side_effect=AssertionError('live run takes precedence'))):
            path = Path(tmp) / '联合.docx'
            receipt = write_joint_report(path, record, design_run=run)
            doc = Document(path)
            design_path = Path(tmp) / '计算.docx'
            export_report(run, design_path, compensation_state=config.get('__comp'))
            design_doc = Document(design_path)
            text = '\n'.join(p.text for p in doc.paragraphs)
            self.assertIn('Vinmin', text)
            self.assertNotIn('Vinmax', text)
            self.assertIn('固定输入 30 V', text)
            titles = [p.text for p in doc.paragraphs if p.style.name == 'Heading 1']
            self.assertEqual(titles.count('1 评审结论'), 1)
            self.assertIn('4.1 ', text)
            self.assertEqual(titles.count('5 电路仿真与设计对照'), 1)
            self.assertEqual(titles.count('6 工程验收与证据'), 1)
            self.assertIn('本测试模拟超时', text)
            self.assertEqual(text.count('图 4.2-1  电路拓扑与器件位号'), 1)
            self.assertIn('关键时域波形', text)
            expected = design_chapters(design_doc, embedded=False)
            actual = design_chapters(doc, embedded=True)
            self.assertGreater(len(expected), 5)
            self.assertEqual(len(actual), len(expected))
            contents_links = {entry.xpath('string(w:hyperlink)'): entry
                              for entry in doc.element.xpath('.//w:p[w:hyperlink[@w:anchor]]')}
            for index, ((joint_heading, joint_blocks), (design_heading, design_blocks)) in enumerate(zip(actual, expected), 1):
                with self.subTest(chapter=joint_heading.text):
                    name = design_heading.text.partition(' ')[2]
                    if index == 1:
                        name = '计算评审结论'
                    self.assertEqual(joint_heading.text, f'4.{index} {name}')
                    self.assertEqual(joint_heading.runs[0].font.size, design_heading.runs[0].font.size)
                    self.assertEqual(joint_heading.runs[0].bold, design_heading.runs[0].bold)
                    anchor, = joint_heading._p.xpath('./w:bookmarkStart/@w:name')
                    entry = contents_links[joint_heading.text]
                    self.assertEqual(entry.xpath('./w:hyperlink/@w:anchor'), [anchor])
                    self.assertEqual(entry.xpath('./w:fldSimple/@w:instr'), [f'PAGEREF {anchor} \\h'])
                    self.assertTrue(Paragraph(entry, doc).paragraph_format.left_indent)
                    labels = [Paragraph(block, doc).text for block in joint_blocks
                              if block.tag == qn('w:p') and Paragraph(block, doc).style.name in
                              ('Caption', 'Report Table Caption')]
                    self.assertTrue(all(re.match(rf'^(图|表) 4\.{index}-\d+  ', label)
                                        for label in labels), labels)
                    numbers = [number for block in joint_blocks for number in block.xpath('./w:r[w:tab]/w:t/text()')
                               if number.startswith('(')]
                    self.assertTrue(all(number.startswith(f'(4.{index}-') for number in numbers), numbers)
                    joint_contents = chapter_contents(doc, joint_blocks)
                    design_contents = chapter_contents(design_doc, design_blocks)
                    if index == 1:
                        # The acceptance summary line is already shown in the
                        # joint report's overall conclusion and evidence chapter.
                        design_contents = [item for item in design_contents
                                           if item[0] != 'paragraph' or not item[1].startswith('工程验收 ')]
                        joint_contents = [(kind, data.replace('表 计算评审结论 · ', '表 评审结论 · ', 1))
                                          if kind == 'paragraph' else (kind, data)
                                          for kind, data in joint_contents]
                    self.assertEqual(joint_contents, design_contents)
            self.assertGreater(receipt['equations'], 5)
            self.assertEqual(receipt['sections'], 2)
            self.assertGreater(doc.sections[-1].page_width, doc.sections[-1].page_height)
            self.assertTrue(receipt['complete_design_snapshot'])
            self.assertEqual(receipt['design_snapshot_source'], 'live')
            self.assertTrue(receipt['incomplete'])
        self.assertEqual(config, before)

    def test_archived_design_snapshot_restores_full_chapter_and_rejects_mismatches(self):
        from unittest.mock import patch
        from design_engine.service import calculate
        config = json.loads((ROOT / 'examples/40W_CCM_FLYBACK.json').read_text('utf-8'))
        run = calculate(config, analysis='endpoints', include_loop=True,
                        include_efficiency=True, include_cross_regulation=False)
        with (tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as tmp,
              patch('design_engine.service.calculate', side_effect=AssertionError('renderer must not calculate')),
              patch('report_docx.compute_design', side_effect=AssertionError('renderer must use saved efficiency')),
              patch('design_engine.service.prepare_endpoint_bundle', side_effect=AssertionError('renderer must not solve'))):
            directory = Path(tmp)
            saved = directory / '03-电路设计计算快照.json'
            snapshot_id = run.save(saved)
            previous_directory = directory / '旧运行目录'
            record = dict(status='partial', directory=str(previous_directory), adopted_config=config,
                          calculation=dict(snapshot_path=str(previous_directory / saved.name), snapshot_id=snapshot_id,
                                           endpoint_metrics=[dict(case='Vinmin', vin_V=30)]),
                          circuit={'evidence': failed_spice()})
            report = directory / '恢复计算章节.docx'
            receipt = write_joint_report(report, record, archive_directory=directory)
            text = '\n'.join(p.text for p in Document(report).paragraphs)
            self.assertIn('4 采用回填参数后的设计计算', text)
            self.assertIn('计算结果来自本次联合运行保存的设计快照。', text)
            self.assertIn('关键时域波形', text)
            self.assertEqual(text.count('图 4.2-1  电路拓扑与器件位号'), 1)
            self.assertTrue(receipt['complete_design_snapshot'])
            self.assertEqual(receipt['design_snapshot_source'], 'archive')
            self.assertIsNone(receipt['design_snapshot_issue'])
            self.assertGreater(receipt['figures'], 0)

            wrong_id = dict(record, calculation=dict(record['calculation'], snapshot_id='unrelated'))
            bundle, issue = _archived_design_bundle(wrong_id, directory)
            self.assertIsNone(bundle)
            self.assertIn('编号', issue)
            wrong_inputs = dict(record, adopted_config=dict(config, V_out=35))
            bundle, issue = _archived_design_bundle(wrong_inputs, directory)
            self.assertIsNone(bundle)
            self.assertIn('设计参数不一致', issue)
            wrong_path = dict(record, calculation=dict(record['calculation'], snapshot_path=str(directory.parent / saved.name)))
            bundle, issue = _archived_design_bundle(wrong_path, directory)
            self.assertIsNone(bundle)
            self.assertIn('超出联合运行目录', issue)

            receipt = write_joint_report(report, record)
            text = '\n'.join(p.text for p in Document(report).paragraphs)
            self.assertFalse(receipt['complete_design_snapshot'])
            self.assertIn('缺少计算快照文件', receipt['design_snapshot_issue'])
            self.assertIn('本节列出已保存的端点摘要', text)
            self.assertNotIn('关键时域波形', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
