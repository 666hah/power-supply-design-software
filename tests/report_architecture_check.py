"""Paired reports preserve endpoint data, native equations and evidence gaps."""
import copy
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from docx import Document
from docx_layout import new_document,table,equation,paragraph
from report_architecture import (comparison_rows,capture_document,write_paired_modules,
    add_acceptance_report,add_paired_figure,available_width,acceptance_columns,acceptance_findings,
    report_cases)


class ReportArchitectureChecks(unittest.TestCase):
    def test_repeated_metric_pairs_and_missing_rows_are_not_lost(self):
        rows=comparison_rows(['参数','结果','参数','结果'],
            [('电压','20 V','电流','1 A')],[('电压','30 V','频率','100 kHz')])
        self.assertEqual(rows,[('电压','20 V','30 V'),('电流','1 A','未提供此项'),
                               ('频率','未提供此项','100 kHz')])

    def test_capture_reassembly_keeps_equations_and_pairs_native_tables(self):
        documents=[]
        for voltage in ('20 V','30 V'):
            doc=Document();doc.add_heading('2  关键时域波形',1)
            paragraph(doc,'共同模型说明');table(doc,['参数','值'],[('电压',voltage)])
            equation(doc,'I=V/R');documents.append(capture_document(doc))
        out=new_document('双端点设计报告','测试已完成数据的重组','测试')
        result=write_paired_modules(out,documents,[dict(id='Vinmin',voltage=20,result={}),
            dict(id='Vinmax',voltage=30,result={})])
        self.assertEqual(result['paired_tables'],1)
        self.assertEqual(len(out.element.xpath('.//m:oMath')),1)
        self.assertEqual(sum(p.text=='共同模型说明' for p in out.paragraphs),1)
        self.assertEqual([[c.text for c in r.cells] for r in out.tables[0].rows],
            [['参数','Vinmin','Vinmax'],['电压','20 V','30 V']])
        self.assertGreater(available_width(out),9)

    def test_acceptance_retains_missing_sources_and_native_table_cells(self):
        snapshot=dict(summary=dict(label='待补证据/目标',counts={'undefined':2},unresolved_issues=0),
            evidence_notes=['未取得匹配仿真'],issues=[],rows=[dict(id='ripple',name='输出纹波',
            comparison='<=',limit=.1,unit='V',cases={case:dict(calculation=.02,simulation=None,
                measurement=None,states=dict(calculation='pass',simulation='undefined',measurement='undefined'),
                status='undefined') for case in ('Vinmin','Vinmax')})])
        doc=new_document('设计验收','仅测试证据投影','测试')
        with patch('report_architecture.acceptance_snapshot',return_value=snapshot):
            result=add_acceptance_report(doc,{}, {})
        self.assertIs(result,snapshot)
        cells='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn('仿真待补，实测待补','\n'.join(p.text for p in doc.paragraphs))
        from engineering_acceptance import STATE_LABELS
        self.assertIn(STATE_LABELS['undefined'],cells)
        self.assertNotIn('仿真 0',cells)

    def test_acceptance_groups_preserve_each_limit_and_show_history_separately(self):
        from engineering_workbook import page
        from report_xlsx import write_acceptance_details

        review = dict(label='超限', state='review', counts={'review': 1, 'pass': 1})
        passed = dict(label='满足', state='pass', counts={'pass': 2})
        device_case = dict(comparison='<=', limit=40., calculation=39.,
                           states={'calculation': 'pass'}, status='pass')
        ripple_case = dict(comparison='<=', limit=.1, calculation=.12,
                           states={'calculation': 'review'}, status='review')
        snapshot = dict(summary=review, groups=[
            dict(id='components', title='器件规格', summary=passed),
            dict(id='performance', title='电源外特性', summary=review),
        ], issues=[dict(id='I1', title='历史记录', effective_status='open')], rows=[
            dict(id='vds', name='Q1 阻断电压', group='components', unit='V', comparison='<=', limit=40.,
                 cases={case: device_case for case in ('Vinmin', 'Vinmax')}),
            dict(id='ripple', name='输出纹波', group='performance', unit='V', limits_vary=True,
                 cases={'Vinmin': ripple_case, 'Vinmax': dict(ripple_case, limit=.15, status='pass',
                                                            states={'calculation': 'pass'})}),
        ])
        doc = new_document('工程验收', '两组限值与证据', '测试')
        add_acceptance_report(doc, {}, snapshot=snapshot)
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith('Heading')]
        self.assertEqual(headings, ['工程验收', '器件规格', '电源外特性', '补充记录 · 整改'])
        cells = [[c.text for c in t.rows[1].cells] for t in doc.tables]
        self.assertIn('Q1 阻断电压', cells[0])
        self.assertIn('限值 <= 100 mV', cells[1][2])
        self.assertIn('限值 <= 150 mV', cells[1][3])
        labels, rows = acceptance_columns(snapshot, None)
        self.assertEqual(acceptance_findings(snapshot, labels), [('输出纹波', 'Vinmin 计算 120 mV，要求 <= 100 mV')])
        sheet = page('工程验收', '工程验收', widths=(12,) * 17)
        write_acceptance_details(sheet, 5, snapshot, labels, rows)
        values = [str(cell[0]) for cell in sheet.cells.values()]
        self.assertIn('器件规格  满足', values)
        self.assertIn('电源外特性  超限', values)
        self.assertIn('补充记录 · 整改', values)

    def test_missing_figure_is_explicit_and_not_duplicated(self):
        from PIL import Image
        image=BytesIO();Image.new('RGB',(800,400),'white').save(image,format='PNG')
        doc=new_document('图像证据','缺失右端','测试')
        add_paired_figure(doc,image.getvalue(),None,'波形对照')
        self.assertEqual(len(doc.inline_shapes),1)
        self.assertIn('Vinmax 图像未提供','\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells))
        from docx.oxml.ns import qn
        self.assertIsNotNone(doc.tables[0]._tbl.getnext().find(qn('w:pPr')).find(qn('w:keepNext')))

    def test_fixed_vin_keeps_different_measurement_evidence(self):
        case_result = {'op': {'D': .25}}
        bundle = dict(base_spec={'V_in': 30}, cases=[
            dict(id=case_id, voltage=30, result=case_result) for case_id in ('Vinmin','Vinmax')])
        cell = dict(calculation=.02, simulation=.021, measurement=None, status='undefined')
        row = dict(name='输出纹波', comparison='<=', limit=.1, unit='V',
                   cases={case_id: dict(cell) for case_id in ('Vinmin','Vinmax')})
        snapshot = dict(rows=[row])
        self.assertEqual(len(report_cases(bundle)),1)
        self.assertEqual(acceptance_columns(snapshot,bundle)[0],['固定输入'])
        self.assertEqual(acceptance_columns(snapshot,None,bundle['base_spec'])[0],['固定输入'])
        row['cases']['Vinmax'].update(measurement=.024,measurement_record={'source':'QA source'})
        self.assertEqual(acceptance_columns(snapshot,bundle)[0],['Vinmin','Vinmax'])

    def test_fixed_vin_different_mos_event_parameters_retains_two_cases(self):
        shared = {'op': {'D': .25}}
        bundle = dict(base_spec={'V_in':30,'mos_miller_mode':'manual',
                                 'mos_manual_events':{'min':{'on':{'Vgp':3.8}},
                                                      'max':{'on':{'Vgp':4.0}}}}, cases=[
            dict(id=case_id, voltage=30, result=shared) for case_id in ('Vinmin','Vinmax')])
        self.assertEqual(len(report_cases(bundle)),2)

    def test_mos_platform_and_envelope_have_distinct_labels_without_mutation(self):
        from report_architecture import component_check_label
        platform=dict(ref='Q1',metric='voltage',name='Q1 MOS 稳态 Vds',value=35)
        envelope=dict(ref='Q1',metric='peak',name='Q1 MOS 稳态 Vds',value=42)
        before=copy.deepcopy([platform,envelope])
        self.assertIn('阻断平台',component_check_label(platform))
        self.assertIn('峰值包络',component_check_label(envelope))
        self.assertEqual([platform,envelope],before)

    def test_paired_winding_legend_does_not_cover_spatial_layer_labels(self):
        from matplotlib.figure import Figure
        from report_architecture import comparison_charts,prepare_chart
        fig=Figure();ax=fig.subplots();ax.plot([0,1],label='P 6T 利兹线')
        ax.set_title('12 × 3.3 mm 净窗口 · 当前层绕方案可放下')
        ax.text(1,.5,'L2 · P');ax.legend()
        with comparison_charts():prepare_chart(fig)
        self.assertIsNone(ax.get_legend())
        self.assertEqual(ax.texts[0].get_text(),'L2 · P')


if __name__=='__main__':unittest.main(verbosity=2)
