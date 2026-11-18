"""COT Word projection consumes the shared phase and dynamic calculations."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.service import calculate
from docx_layout import new_document
from report_docx import export_design_docx


class CotReportChecks(unittest.TestCase):
    def test_phase_protection_and_dynamic_sections_keep_engine_values(self):
        p=json.loads((ROOT/'examples/96W_BUCK_COT_4PH.json').read_text('utf-8'))
        p.setdefault('cot_config',{}).setdefault('dynamic',{}).update(
            step_A=20.,rise_s=20e-6,delay_s=2e-6,droop_V=.06,overshoot_V=.06)
        case=calculate(p,analysis='endpoints',include_loop=True,include_cross_regulation=False).runtime_bundle()['cases'][0]
        res=case['result'];before=deepcopy(case['p'])
        doc=new_document('COT 计算报告验证','','验证')
        export_design_docx('',case['p'],res['op'],res['wf'],res,models=case.get('models'),
            document=doc,save=False,efficiency_curve=dict(fracs=[1.],etas=[res['eta']],modes=[res['op']['mode']],failures=[]))
        text='\n'.join(x.text for x in doc.paragraphs)+'\n'+'\n'.join(
            cell.text for table in doc.tables for row in table.rows for cell in row.cells)
        for label in ('逐相均流与动态约束','采样余量','电荷初筛','平均闭环负载响应','总电流反馈增益'):
            self.assertIn(label,text)
        self.assertEqual(case['p'],before)
        # Identical capacitor curves may be combined for readability, while
        # every physical branch still appears in the per-capacitor table.
        self.assertIn('相同曲线合并展示',text)
        self.assertGreaterEqual(len(doc.inline_shapes),6)


if __name__=='__main__':unittest.main(verbosity=2)
