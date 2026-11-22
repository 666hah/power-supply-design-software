"""Module-first simulation comparison keeps endpoint identity and evidence gaps."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from docx import Document
from docx_layout import table
from spice_comparison_report import _endpoint,_render_endpoint_modules,simulation_summary,write_report

class Pairing(unittest.TestCase):
 def render(self,modules,**options):
  doc=Document()
  _render_endpoint_modules(doc,modules,
   lambda h,r,w,**kw:table(doc,h,r,[x/2.54 for x in w],**kw),
   lambda t:doc.add_paragraph(t),lambda t:doc.add_heading(t,1),**options)
  return doc
 def module(self,endpoint,value,voltage=30,complete=True):
  return dict(case=dict(id=endpoint+'_标称负载',voltage=voltage,complete=complete,error='实际超时'),
   title='原边电流与控制过程',blocks=[dict(kind='table',headers=['指标','单位','设计计算','LTspice 实测','偏差','判定口径'],rows=[('峰值','A',value,value+.1,'+1%','待复核')])])
 def test_equal_voltage_keeps_explicit_endpoint_values(self):
  doc=self.render([self.module('Vinmin',10),self.module('Vinmax',20)])
  self.assertEqual(len([p for p in doc.paragraphs if p.style.name=='Heading 1']),1)
  data=doc.tables[1].rows[1].cells
  self.assertEqual(data[2].text,'10');self.assertEqual(data[5].text,'20')
  self.assertIn('Vinmin',doc.tables[1].rows[0].cells[2].text)
 def test_fixed_voltage_does_not_add_missing_endpoint(self):
  doc=self.render([self.module('Vinmin',10)],fixed_voltage=30)
  self.assertEqual(len(doc.tables),1)
  self.assertEqual(doc.tables[0].rows[1].cells[2].text,'10')
  text='\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
  self.assertNotIn('未执行',text)
  self.assertNotIn('Vinmax',text)
 def test_matching_equal_voltage_table_printed_once(self):
  doc=self.render([self.module('Vinmin',10),self.module('Vinmax',10)])
  self.assertEqual(len(doc.tables),1)
  self.assertEqual(doc.tables[0].rows[1].cells[3].text,'10.1')
 def test_failed_side_does_not_borrow_other_modules(self):
  left=self.module('Vinmin',10)
  failed=dict(case=dict(id='Vinmax_标称负载',voltage=30,complete=False,error='实际超时'),title='运行与稳态检查',blocks=[dict(kind='paragraph',text='实际超时')])
  doc=self.render([left,failed]);text='\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
  self.assertIn('实际超时',text);self.assertIn('未取得',text)
  row=doc.tables[1].rows[1].cells;self.assertEqual(row[5].text,'未取得')
 def test_rows_unique_to_one_endpoint_remain_visible(self):
  a=self.module('Vinmin',10);b=self.module('Vinmax',20)
  b['blocks'][0]['rows'].append(('新增实测项','V',1,2,'+100%','待复核'))
  doc=self.render([a,b]);self.assertIn('新增实测项','\n'.join(c.text for t in doc.tables for r in t.rows for c in r.cells))
 def test_unbound_id_is_explicit_not_guessed_from_voltage(self):
  a=self.module('other',10);doc=self.render([a])
  self.assertIn('未绑定端点','\n'.join(p.text for p in doc.paragraphs))
  self.assertIsNone(_endpoint(a['case'])[0])
 def test_duplicate_evidence_cannot_silently_overwrite(self):
  with self.assertRaisesRegex(ValueError,'重复证据'):self.render([self.module('Vinmin',10),self.module('Vinmin',20)])
 def test_different_units_are_not_lost(self):
  a=self.module('Vinmin',10);b=self.module('Vinmax',20);b['blocks'][0]['rows'][0]=('峰值','V',20,21,'+5%','待复核')
  doc=self.render([a,b]);self.assertIn('Vinmin A / Vinmax V',doc.tables[1].rows[1].cells[1].text)
 def test_same_voltage_different_test_families_are_not_merged(self):
  modules=[self.module('Vinmin',10),self.module('Vinmax',20),self.module('Vinmin',30),self.module('Vinmax',40)]
  for m in modules[2:]:m['case']['id']=m['case']['id'].replace('标称负载','负载阶跃')
  doc=self.render(modules)
  self.assertEqual(len(doc.tables),4)
  self.assertEqual(doc.tables[1].rows[1].cells[2].text,'10')
  self.assertEqual(doc.tables[1].rows[1].cells[5].text,'20')
  self.assertEqual(doc.tables[3].rows[1].cells[2].text,'30')
  self.assertEqual(doc.tables[3].rows[1].cells[5].text,'40')

 def test_startup_stress_has_numeric_subcolumns_and_repeating_endpoint_groups(self):
  from spice_box_figures import STARTUP_HEADERS
  left, right = self.module('Vinmin',10,252), self.module('Vinmax',20,442)
  for module,peak,time,status in ((left,443,20,'观察峰值未超限'),(right,710,21,'超过配置降额限值')):
   module['blocks'][0].update(headers=STARTUP_HEADERS,rows=[('Q1 Vds','V',peak,time,800,680,status)])
  grid=self.render([left,right]).tables[-1]
  self.assertEqual([c.text for c in grid.rows[1].cells],list(STARTUP_HEADERS)+list(STARTUP_HEADERS[2:]))
  self.assertEqual([c.text for c in grid.rows[2].cells],
    ['Q1 Vds','V','443','20','800','680','观察峰值未超限','710','21','800','680','超过配置降额限值'])
  self.assertEqual([len(row._tr.xpath('./w:trPr/w:tblHeader')) for row in grid.rows],[1,1,0])
  self.assertEqual([c.grid_span for c in grid.rows[0]._tr.tc_lst],[2,5,5])
  self.assertEqual(str(grid.rows[2].cells[-1].paragraphs[0].runs[0].font.color.rgb),'A12D24')

  single=self.render([left],fixed_voltage=252).tables[-1]
  self.assertEqual([c.text for c in single.rows[0].cells],list(STARTUP_HEADERS))


class ReviewSummary(unittest.TestCase):
 def nominal(self, endpoint='Vinmin', voltage=30, **extra):
  case=dict(id=endpoint+'_标称负载', voltage=voltage, fault_test=False, complete=True,
            periodicity={'stable':True}, nominal_comparable=True, rows=[])
  case.update(extra)
  return case

 def test_declared_second_endpoint_without_evidence_is_pending(self):
  summary=simulation_summary({'cases':[self.nominal()], 'plan':{'voltages':[30,50]}})
  self.assertEqual(summary['state'],'undefined')
  self.assertIn('Vinmax',summary['pending'][0][0])
  self.assertIn('50 V',summary['pending'][0][1])

 def test_fra_acceptance_uses_unrounded_minimum_and_valid_evidence(self):
  settings = {'fra_enabled': True}
  metrics = dict(pm=65., crossings=[dict(pm=65.), dict(pm=45.)])
  loop = dict(available=True, simulation={'loop': metrics})
  evidence = dict(cases=[self.nominal(loop=loop)], settings=settings)
  summary = simulation_summary(evidence)
  self.assertEqual(summary['state'], 'review')
  self.assertIn('45 ° 未达标', summary['findings'][0][1])
  metrics['crossings'][-1]['pm'] = 45.0001
  self.assertEqual(simulation_summary(evidence)['state'], 'pass')
  loop['available'] = False
  self.assertEqual(simulation_summary(evidence)['state'], 'undefined')

 def test_nominal_steady_check_and_priority_deviation_survive_on_cover(self):
  rows=[dict(metric='原边电流 RMS',status='偏差待复核',delta_percent=-7.0),
        dict(metric='输出电压',status='偏差在提示阈值内',delta_percent=2.0)]
  a=self.nominal(steady_before_step={'passed':False,'reason':'阶跃前窗口未稳态'},
                 nominal_comparable=False,rows=rows)
  b=self.nominal('Vinmax', 50, rows=rows)
  summary=simulation_summary({'cases':[a,b], 'settings':{'comparison_tolerance_pct':5}})
  self.assertEqual(summary['state'],'review')
  self.assertEqual(summary['review_count'],2)
  self.assertEqual(summary['findings'][0][1],'阶跃前窗口未稳态')
  self.assertEqual(summary['findings'][1][0],'原边电流 RMS')
  self.assertIn('Vinmin 30 V · 标称负载 -7.00%',summary['findings'][1][1])
  self.assertIn('Vinmax 50 V · 标称负载 -7.00%',summary['findings'][1][1])

 def test_failed_fixed_input_stays_portrait_and_embedded_cover_does_not_repeat(self):
  from docx_layout import new_document
  from spice_export import normalize_settings
  evidence=dict(model='TEST',topology='FLYBACK',input_range_V=[30,30],settings=normalize_settings({}),
                cases=[self.nominal(complete=False,error='本次仿真超时')])
  doc=write_report(None,evidence,save=False)
  self.assertEqual(len(doc.sections),1)
  self.assertLess(doc.sections[0].page_width,doc.sections[0].page_height)
  self.assertIn('1 评审结论',[p.text for p in doc.paragraphs])
  self.assertIn('本次仿真超时',[p.text for p in doc.paragraphs])
  joint=new_document('联合报告','','')
  write_report(None,evidence,document=joint,save=False,include_conclusion=False,section_number=4)
  self.assertEqual(len(joint.sections),1)
  self.assertIn('4 电路仿真与设计对照',[p.text for p in joint.paragraphs])
  self.assertNotIn('评审结论',[p.text for p in joint.paragraphs])

 def test_measured_unload_and_missing_line_study_are_not_passes(self):
  case=self.nominal(load_transient=dict(complete=True,band_pct=2,events=[dict(rail=1,before=1,after=0,recovery_s=None,observed_s=.01)]))
  summary=simulation_summary(dict(cases=[case],settings=dict(line_load_enabled=1)))
  self.assertEqual(summary['state'],'review')
  self.assertIn('100%→0%',summary['findings'][0][0])
  self.assertIn('10 ms',summary['findings'][0][1])
  self.assertIn('线载联合动态稳定度',dict(summary['pending']))

if __name__=='__main__':unittest.main(verbosity=2)
