"""XLSX export regression: endpoint identity, native cells, images and failure."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from calculation_scheduler import calculate_report_efficiency_curve
from report_xlsx import export_input_range_xlsx, _math_text
from xlsx_report_writer import numeric_text, S, D


def read_workbook(path):
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        xml={n:ET.fromstring(archive.read(n)) for n in archive.namelist() if n.endswith(('.xml','.rels'))}
        book=xml['xl/workbook.xml']
        names=[e.get('name') for e in book.findall('{'+S+'}sheets/{'+S+'}sheet')]
        for name,root in xml.items():
            if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'): continue
            merged=[]
            from openpyxl.utils.cell import range_boundaries
            for e in root.findall('{'+S+'}mergeCells/{'+S+'}mergeCell'):
                bounds=range_boundaries(e.get('ref'))
                for old in merged:
                    assert bounds[2]<old[0] or old[2]<bounds[0] or bounds[3]<old[1] or old[3]<bounds[1],(name,bounds,old)
                merged.append(bounds)
        return archive.namelist(),names,xml


def sample(name='40W_CCM_FLYBACK.json',lo=27.,hi=33.):
    config=json.loads((ROOT/'examples'/name).read_text(encoding='utf-8'))
    p=load_spec(dict(config,V_in_min=lo,V_in_max=hi,input_voltage_case='max'))
    result=calculate_input_endpoints(p)
    for case in result['cases']:
        if case.get('result'):
            # Explicit precomputed snapshot: no hidden load scan in writer.
            case['efficiency_curve']=dict(fracs=[1.],etas=[case['result']['eta']],
                                          modes=[case['result']['op']['mode']],failures=[])
    return result


class ExcelReportCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.snapshot=sample()

    def test_native_values_units_and_safe_text(self):
        self.assertEqual(numeric_text('84.15%'),(.8415,'0.00%'))
        self.assertEqual(numeric_text('-50 pF'),(-50.,'0.00" pF"'))
        self.assertEqual(numeric_text('OUT1'),('OUT1',None))
        self.assertEqual(numeric_text('1 / 2'),('1 / 2',None))
        self.assertEqual(numeric_text('未定义'),('未定义',None))

    def test_tolerance_evidence_is_shared_by_word_and_excel(self):
        from docx import Document
        from input_range_report import export_input_range_docx
        from openpyxl import load_workbook

        case = dict(id='B013', voltage=33., load_profile='满载', parameters={'Rds_on': .06})
        inputs = [dict(path='Rds_on', label='主 MOS 导通电阻', unit='Ω', nominal=.05,
                       low=.04, high=.06, distribution='uniform', source='演示用范围')]
        statistics = dict(count=96, missing_count=4, mean=77., std=1., moment_4sigma_low=73.,
                          moment_4sigma_high=81., quantile_4sigma_low=None, quantile_4sigma_high=None,
                          expected_tail_count=.003, reason='尾部样本不足')
        rows = [dict(name='主开关电压', unit='V', direction='max', limit=80., worst=82.,
                     margin=-2., status='review', case=case, statistics=statistics,
                     evaluated_cases=20, expected_cases=20)]
        evidence = dict(rows=rows, variables=inputs, samples=100, seed=42, evaluations=120,
                        failure_count=4, failures=[dict(case, error='样例未收敛')],
                        scope='已声明的稳态工况', input_fingerprint='0'*64)
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            word = Path(folder)/'容差.docx'
            excel = Path(folder)/'容差.xlsx'
            export_input_range_docx(word, self.snapshot, tolerance_result=evidence)
            export_input_range_xlsx(excel, self.snapshot, tolerance_result=evidence)
            doc = Document(word)
            self.assertEqual(1, sum(p.style.name == 'Heading 1' and '最坏工况与容差' in p.text
                                    for p in doc.paragraphs))
            doc_rows = [tuple(c.text for c in r.cells) for t in doc.tables for r in t.rows]
            self.assertIn(('主开关电压', '≤ 80 V', '82 V', '-2 V', 'B013 · 33 V · 满载', '20 / 20', '需复核'), doc_rows)
            self.assertIn(('主开关电压', '—', '—', '0.003', '待补尾部样本\n尾部样本不足'), doc_rows)
            with excel.open('rb') as stream:
                workbook = load_workbook(stream, read_only=True)
                values = [tuple(v for v in row if v is not None and v != '')
                          for row in workbook['最坏工况与容差'].values]
                workbook.close()
            self.assertIn(('主开关电压', '≤ 80 V', 82, -2, 'B013 · 33 V · 满载', '20 / 20', '需复核'), values)
            self.assertIn(('主开关电压', '—', '—', .003, '待补尾部样本\n尾部样本不足'), values)
            self.assertIn(('B013 · 33 V · 满载', '样例未收敛'), values)

    def test_equation_descriptions_preserve_grouping_and_sum(self):
        from word_math import element, Parser
        self.assertEqual(_math_text(element('oMath', *Parser('T(s)=Gc(s)·Gb(s)').expr())),
                         'T(s)=G_{c}(s)·G_{b}(s)')
        text = _math_text(element('oMath', *Parser('P=∑_j(Ij^2)').expr()))
        self.assertIn('∑_{j}',text)
        self.assertIn('I_{j}^(2)',text)

    def test_full_report_schema_and_endpoint_identity(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path=Path(folder)/'report.xlsx'
            snapshot=self.snapshot
            original=snapshot['base_spec'].copy()
            result=export_input_range_xlsx(path,snapshot)
            parts,names,xml=read_workbook(path)
            self.assertEqual(snapshot['base_spec'],original)
            self.assertEqual(result['successful_cases'],2)
            self.assertEqual(result['sheet_count'],13)
            self.assertEqual(names[0],'00 工程验收')
            self.assertIn('14 关键器件BOM与降额',names)
            self.assertFalse(result['incomplete'])
            self.assertIn('06 磁件与绕制',names)
            self.assertIn('07 环路与补偿电路',names)
            self.assertNotIn('10 MP6005 PSR',names)
            for i in range(1,len(names)+1):
                root=xml[f'xl/worksheets/sheet{i}.xml']
                cells={c.get('r'):c for c in root.findall('.//{'+S+'}c')}
                self.assertIn('Vinmin',ET.tostring(cells['A4'],encoding='unicode'))
                self.assertIn('Vinmax',ET.tostring(cells['J4'],encoding='unicode'))
                self.assertEqual(root.find('.//{'+S+'}pane').get('ySplit'),'4')
            overview=names.index('01 需求与工况总览')+1
            cells={c.get('r'):c for c in xml[f'xl/worksheets/sheet{overview}.xml'].findall('.//{'+S+'}c')}
            for addr,case in zip(('E6','N6'),snapshot['cases']):
                self.assertEqual(cells[addr].get('t'),'n')
                self.assertAlmostEqual(float(cells[addr].find('{'+S+'}v').text),case['result']['eta'],places=12)
            drawing_count=sum(len(e.findall('{'+D+'}oneCellAnchor')) for n,e in xml.items() if n.startswith('xl/drawings/drawing'))
            self.assertEqual(drawing_count,result['figure_count'])
            topology=names.index('02 拓扑与多路输出')+1
            self.assertEqual(len(xml[f'xl/drawings/drawing{topology}.xml'].findall('{'+D+'}oneCellAnchor')),1)
            power=names.index('03 功率级与开关波形')+1
            self.assertGreaterEqual(len(xml[f'xl/drawings/drawing{power}.xml'].findall('{'+D+'}oneCellAnchor')),4)
            self.assertTrue(any(n.startswith('xl/media/') for n in parts))

    def test_failure_is_visible_not_cloned(self):
        snapshot=dict(self.snapshot,cases=[self.snapshot['cases'][0],
            dict(self.snapshot['cases'][1],error='QA endpoint failure',result=None)])
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path=Path(folder)/'partial.xlsx'; result=export_input_range_xlsx(path,snapshot)
            _,_,xml=read_workbook(path)
            self.assertEqual(result['failed_cases'],['Vinmax'])
            self.assertTrue(result['incomplete'])
            for name,root in xml.items():
                if name.startswith('xl/worksheets/sheet'):
                    self.assertIn('QA endpoint failure',ET.tostring(root,encoding='unicode'))

    def test_duplicate_or_missing_case_rejected(self):
        with self.assertRaises(ValueError):
            export_input_range_xlsx('unused.xlsx',dict(self.snapshot,cases=[self.snapshot['cases'][0]]*2))

    def test_psr_has_own_module_and_real_data(self):
        snapshot=sample('MP6005_PSR_FLYBACK.json',30.,30.)
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path=Path(folder)/'psr.xlsx'
            result=export_input_range_xlsx(path,snapshot)
            _,names,xml=read_workbook(path)
            self.assertIn('10 MP6005 PSR',names)
            self.assertEqual(result['successful_cases'],2)
            self.assertEqual(result['displayed_case_count'],1)
            text=''.join(ET.tostring(e,encoding='unicode') for n,e in xml.items() if n.startswith('xl/worksheets/sheet'))
            self.assertIn('固定输入',text)
            self.assertNotIn('r="J4"',text)
            self.assertIn('Rcomp',text)

    def test_nonisolated_does_not_get_clamp_or_psr_sheet(self):
        from design_api import DEFAULT_PARAMS
        p=load_spec(dict(DEFAULT_PARAMS,topology='BUCK',V_in_min=40.,V_in_max=50.))
        snapshot=calculate_input_endpoints(p)
        for case in snapshot['cases']:
            if case.get('result'):
                case['efficiency_curve']=dict(fracs=[1.],etas=[case['result']['eta']],modes=[case['result']['op']['mode']],failures=[])
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path=Path(folder)/'buck.xlsx';result=export_input_range_xlsx(path,snapshot)
            _,names,_=read_workbook(path)
            self.assertEqual(result['successful_cases'],2)
            self.assertNotIn('08 钳位与复位',names)
            self.assertNotIn('10 MP6005 PSR',names)


if __name__=='__main__': unittest.main()
