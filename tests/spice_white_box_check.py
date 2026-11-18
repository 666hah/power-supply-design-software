"""Independent probe inventory, metrology and optional local LTspice smoke."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from spice_white_box import collect, collect_startup, prepare


class WhiteBoxChecks(unittest.TestCase):
    def test_shared_waveform_keeps_phase_ripple_and_real_units(self):
        from spice_box_figures import _plot_channels, _merged_waveform_note

        def device(ref,values,*,offset=0.,label='Ic'):
            return {'ref':ref,'wave':([offset+i for i in range(5)],values,label,None)}

        wave = [0.,.6,1.,.2,-.5]
        traces = [device('C1',wave),device('C2',[2*v for v in wave]),
                  device('C3',[-v for v in wave]),device('C4',wave,offset=.1),
                  device('C5',[1.,1.001,1.,1.001,1.]),device('C6',[2.,2.,2.001,2.,2.]),
                  device('C7',[0.]*5),device('C8',[0.,.6,1.,.2,-.8])]
        channels = _plot_channels(traces,lambda d,k:d['wave'] if k=='current' else None)
        self.assertEqual([channel[0] for channel in channels],['电流 / A','归一化电流 / p.u.'])
        self.assertEqual([[trace.ref for trace in group] for group in channels[1][1]],[['C1','C2']])
        self.assertEqual(len(channels[0][1]),6)
        self.assertIn('C1 1 A，C2 2 A',_merged_waveform_note(channels))
        voltages = [device('C1',[60.]*5,label='Vc'),device('C2',[60.]*5,label='Vc'),
                    device('C3',[12.]*5,label='Vc')]
        channels = _plot_channels(voltages,lambda d,k:d['wave'] if k=='voltage' else None)
        self.assertEqual([[trace.ref for trace in group] for group in channels[0][1]],[['C1','C2'],['C3']])
        self.assertFalse(channels[0][2])

    def test_output_bank_keeps_nonadjacent_devices_in_one_figure(self):
        from spice_box_figures import _device_groups

        refs = ['C_IN1','C_IN2','C_SN1','C_O1A','C_O2A','C_O1B','C_O1C','C_O2B']
        rows = [dict(ref=ref,kind='capacitor') for ref in refs]
        groups = list(_device_groups(dict(rows=rows,devices=rows),[('capacitor','电容')]))
        self.assertEqual([[row['ref'] for row in group[2]] for group in groups],
                         [refs[:3],['C_O1A','C_O1B','C_O1C'],['C_O2A','C_O2B']])

    def test_startup_voltage_only_for_capacitors_and_flyback_q1(self):
        from matplotlib.figure import Figure
        from spice_box_figures import white_startup_sections

        wave = dict(time_s=[0.,1.],values=[0.,10.],label='实测',peak_s=1.,peak_value=10.)
        rows, devices = [], []
        for ref, kind in [('C_O1','capacitor'),('Q1','mos'),('Q1 Coss','aux')]:
            devices.append(dict(ref=ref,kind=kind,current=wave,voltage=wave if kind!='aux' else None))
            for channel,unit in [('current','A'),('voltage','V')]:
                if kind=='aux' and channel=='voltage':continue
                rows.append(dict(ref=ref,kind=kind,channel=channel,metric='实测',unit=unit,simulation=10.,
                                 time_s=1.,rating=None,limit=None,status='记录观察峰值',scope='器件端子'))
        case = dict(white_box_startup=dict(rows=rows,devices=devices,start_s=0.,end_s=1.))
        sections = list(white_startup_sections(case,flyback_ramp=True))
        self.assertEqual(len(sections),2)
        for _,_,values,_,draw in sections:
            self.assertEqual([row[1] for row in values],['V'])
            fig = Figure()
            draw(fig)
            self.assertEqual([axis.get_ylabel() for axis in fig.axes],['电压 / V'])
        self.assertEqual(len(case['white_box_startup']['rows']),5)

    def test_cot_report_black_white_sections_and_missing_evidence(self):
        from types import SimpleNamespace
        from cot_spice_comparison import _write_report
        from docx import Document
        from docx.oxml.ns import qn

        raw = SimpleNamespace(time=np.array([0.,.1,.2]),trace={'i(sh1)':np.array([0.,-1.,-.5])}.__getitem__)
        files={'design_params.inc':b'','analysis.inc':b'','power_stage.inc':b'SH1 input sw gate 0 SWMOD\n'}
        startup=collect_startup(raw,prepare(files,{'result':{'op':{}}}),0.,.2)
        evidence=dict(model='COT · 分类回归用例',settings=dict(fra_enabled=0),parameters={'V_out':1.2},
            cases=[dict(id='Vinmin',voltage=10.,complete=False,error='测试用例：未运行满载',
                        nominal_comparable=False,rows=[],measurements={},loop=dict(available=False),
                        white_box_startup=startup,
                        load_transient=dict(waveform={'time':[0.,.1,.2,.3],'voltage':[1.2,1.1,1.25,1.2]},
                            reference_v=1.2,stimulus=[dict(time_s=.1,rail=1,before=.1,after=.9),dict(time_s=.2,rail=1,before=.9,after=.1)],
                            low_fraction=.1,high_fraction=.9,events=[]))])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cot.docx'
            _write_report(path,evidence)
            doc=Document(path)
            text='\n'.join(p.text for p in doc.paragraphs)
            self.assertLess(text.index('2 黑盒'),text.index('3 白盒'))
            self.assertIn('开机时间与过冲',text)
            self.assertIn('双向负载阶跃与恢复',text)
            self.assertIn('额定负载环路',text)
            self.assertIn('线载联合动态稳定度',text)
            self.assertIn('本次未选择线载联合试验',text)
            self.assertIn('负载升降与端口响应',text)
            self.assertIn('本次记录缺少稳态器件探针数据',text)
            self.assertGreaterEqual(len(doc.inline_shapes),2)
            blocks=list(doc.element.body)
            texts=[''.join(block.xpath('.//w:t/text()')) for block in blocks]
            entry=next(i for i,part in enumerate(texts) if part=='MOS 启动电流与漏源电压 · SH1')
            table=next(i for i in range(entry+1,len(blocks)) if blocks[i].tag==qn('w:tbl'))
            self.assertIn('缺少有效 RAW 探针',texts[table])
            chart=next(i for i in range(table+1,len(blocks)) if blocks[i].xpath('.//w:drawing'))
            steady=next(i for i,part in enumerate(texts) if part=='稳态应力')
            self.assertLess(chart,steady)

    def test_piecewise_ac_rms_switch_polarity_reverse_voltage_and_missing(self):
        from types import SimpleNamespace
        axis = np.array([0.,.14,.9,1.])
        signals={'i(xc_o1:cmain)':5+2*axis, 'i(xq1:smain)':-3*axis,
                 'v(drain)':4+axis,'v(sense)':1+axis,'v(out1)':4+2*axis}
        raw = SimpleNamespace(time=axis,trace=signals.__getitem__)
        files={'design_params.inc':b'.param D_IN_EN=0\n','analysis.inc':b'.save V(drain)\n',
               'power_stage.inc':b'XC_O1 out1 0 GPWR_CAP C=1u\nXQ1 drain gate sense GPWR_MOS\nXD_SN1 drain out1 GPWR_DIODE\nXD_IN input bus GPWR_DIODE ACT={D_IN_EN}\n'}
        case={'result':{'op':{'I_sw_rms':3**.5,'I_sw_pk':3.,'V_sw_max':3.},'capacitors':{'output':{'caps':[{'total':1/3**.5}]}}}}
        probes=prepare(files,case)
        self.assertEqual([p['ref'] for p in probes],['C_O1','Q1','D_SN1'])
        self.assertEqual(files['analysis.inc'].decode().lower().count('v(drain)'),1)
        evidence=collect(raw,probes,0,1,.5,comparable=True,tolerance=5)
        rows=evidence['rows']
        self.assertAlmostEqual(rows[0]['simulation'],1/3**.5)
        self.assertAlmostEqual(rows[0]['delta_percent'],0.)
        self.assertAlmostEqual(rows[1]['simulation'],6.)
        self.assertAlmostEqual(rows[2]['simulation'],3**.5)
        self.assertAlmostEqual(rows[3]['simulation'],3.)
        self.assertAlmostEqual(rows[4]['simulation'],3.)
        self.assertEqual(rows[5]['status'],'缺少 RAW 探针')
        self.assertEqual(rows[7]['simulation'],1.)
        self.assertAlmostEqual(evidence['devices'][0]['current_A'][-1],7.)
        self.assertAlmostEqual(evidence['devices'][1]['current_A'][-1],3.)
        observed=collect(raw,probes,0,1,.5,comparable=False,tolerance=5)
        self.assertTrue(all(row['delta_percent'] is None for row in observed['rows']))

    def test_startup_keeps_raw_narrow_peak_and_diode_direction(self):
        from types import SimpleNamespace
        from spice_box_figures import white_startup_sections

        axis = np.array([0,.0999,.1,.1001,1.,1.2])
        signals = {'i(xc_o1:cmain)':np.array([0.,1.,-7.,1.,.1,200.]),
                   'i(xd_sn1:dmain)':np.array([0.,1.,-9.,3.,.1,200.]),
                   'v(drain)':np.array([0.,3.,2.,1.,.1,200.]),'v(out1)':np.array([0.,0.,2.,9.,10.,200.])}
        raw = SimpleNamespace(time=axis,trace=signals.__getitem__)
        files = {'design_params.inc':b'','analysis.inc':b'',
                 'power_stage.inc':b'XC_O1 out1 0 GPWR_CAP C=1u\nXD_SN1 drain out1 GPWR_DIODE\n'}
        probes = prepare(files,{'result':{'op':{}}})
        probes[0].update(voltage_rating=11,voltage_limit=9.9)
        evidence = collect_startup(raw,probes,0,1,bins=2)
        capacitor_current, capacitor_voltage, diode_current, diode_voltage = evidence['rows']
        self.assertEqual((capacitor_current['simulation'],capacitor_current['time_s']),(7.,.1))
        self.assertEqual(capacitor_voltage['status'],'超过配置降额限值')
        self.assertEqual((diode_current['simulation'],diode_current['time_s']),(3.,.1001))
        self.assertEqual(diode_voltage['simulation'],9.9)
        wave = evidence['devices'][0]['current']
        self.assertEqual((wave['values'][wave['time_s'].index(.1)],wave['peak_value']),(-7.,-7.))
        sections = list(white_startup_sections({'white_box_startup':evidence}))
        self.assertEqual(len(sections),2)
        self.assertTrue(all(section[2] and callable(section[4]) for section in sections))
        incomplete = collect_startup(raw,probes,0,1.5)
        self.assertFalse(incomplete['complete_window'])
        self.assertEqual(incomplete['end_s'],1.2)

    def test_real_deck_device_coverage(self):
        from design_engine.service import calculate
        from spice_export import project_files
        for example,required in (
                ('24W_BUCK_CAP_IMPEDANCE',{'C_IN1','C_O1','Q1','D_O1'}),
                ('24W_BOOST_PCM_LM5022',{'C_IN1','C_O1','Q1','D_O1'}),
                ('90W_QR_L6565_252_442V_REFERENCE',{'Q1','D_O2','C_O1A','C_O2A','C_SN1'}),
                ('33W_3OUT_ACF_MP6005_COMPACT',{'Q1','QA','C_ACTIVE','D_F2','C_O3A'}),
                ('40W_CCM_3OUT_FLYBACK',{'Q1','D_O3','C_O3A'}),
                ('96W_BUCK_COT_4PH',{'SH4','SL4','DH4','DL4','C_IN1','C_O1'})):
            with self.subTest(example=example):
                spec=json.loads((ROOT/'examples'/(example+'.json')).read_text(encoding='utf-8-sig'))
                bundle=calculate(spec,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
                case=bundle['cases'][0]
                files=project_files(bundle['base_spec'],bundle=bundle)
                probes=prepare(files,case)
                refs=[p['ref'] for p in probes]
                self.assertEqual(len(refs),len(set(refs)))
                self.assertTrue(required<=set(refs),required-set(refs))
                self.assertTrue(all(p['rms'] is not None for p in probes if p['ref'].startswith(('C_IN','C_O'))))
                if example=='24W_BUCK_CAP_IMPEDANCE':
                    self.assertFalse(next(p for p in probes if p['ref']=='C_O1')['direct'])
                if os.getenv('WHITE_BOX_LTSPICE'):
                    self.check_live(files,probes)

    def test_cot_line_load_preserves_controls_and_load_type(self):
        from cot_line_load import prepare_cot_line_load
        from cot_buck_spice import project_files
        from design_engine.service import calculate
        from spice_line_load import run_line_load
        from spice_runtime import _run
        full=json.loads((ROOT/'examples/96W_BUCK_COT_4PH.json').read_text('utf-8'))
        for advanced in (True,False):
            spec=dict(full)
            if not advanced:
                spec.pop('cot_config',None)
            else:
                spec['cot_config']=dict(model='current_feedback',load_mode='current',current_feedback_hz_per_a=4.,
                                        source_rise_s=.0008,source_resistance_ohm=.03)
            spec.update(buck_phases=1,f_sw=3000.,L=.0005,V_out=3.,P_out=4.,fc_target=80.,
                        cot_kp_hz=1200.,cot_ki_hz_per_s=50000.,P_out_min=.4)
            bundle=calculate(spec,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()
            base=bundle['base_spec']
            case=bundle['cases'][-1]
            files=project_files(base,bundle=bundle,case=case)
            settings=json.loads(files['manifest.json'])['settings']
            settings.update(step_ms=25.,cross_timeout_s=70)
            new,schedule=prepare_cot_line_load(files,[base],[10,14],settings,3000.)
            self.assertNotIn(b'sgnd',new['analysis.inc'])
            self.assertIn(b'V(lpatt1)',new['power_stage.inc'])
            self.assertIn(b'V(linebias)',new['control.inc'])
            self.assertEqual(len(schedule),1)
            self.assertEqual(b'.meas TRAN fault_max' in new['analysis.inc'],advanced)
            if os.getenv('COT_LINE_LTSPICE'):
                with tempfile.TemporaryDirectory() as tmp:
                    def execute(folder,timeout):
                        return _run(os.environ['COT_LINE_LTSPICE'],folder,timeout,lambda:False)
                    result=run_line_load(files,[base],[10,14],settings,3000.,Path(tmp)/'line',execute,prepare=prepare_cot_line_load)
                    log=Path(tmp)/'line'/'Flyback.log'
                    if not result['complete'] and log.exists():
                        from spice_runtime import read_log
                        self.fail(str(result)+'\n'+read_log(log)[1][-3500:])
                self.assertTrue(result['complete'],result)
                self.assertEqual(result['protection_available'],advanced)
                self.assertEqual(result['line_plateaux_V'],[10.,14.,10.])

    def check_live(self,files,probes):
        from spice_runtime import _run, TransientRaw
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            for name,payload in files.items():
                if name=='analysis.inc':
                    content=payload.decode('ascii')
                    content=re.sub(r'(?im)^\.tran.*$',r'.tran 0 40u 0 20n',content)
                    payload='\n'.join(line for line in content.splitlines() if not line.lower().startswith('.meas')).encode('ascii')+b'\n'
                if name=='design_params.inc':
                    payload=b'\n'.join(line for line in payload.splitlines() if not line.startswith(b'.step'))+b'\n'
                (path/name).write_bytes(payload)
            _run(os.environ['WHITE_BOX_LTSPICE'],path,35,lambda:False)
            raw=TransientRaw(path/'Flyback.raw')
            try:
                data=collect(raw,probes,.00001,.00003,.00002,comparable=False,tolerance=5)
                self.assertTrue(data['available'])
                self.assertFalse([row['metric'] for row in data['rows'] if row['simulation'] is None])
                startup=collect_startup(raw,probes,0,.000025)
                self.assertTrue(startup['complete_window'])
                self.assertFalse([row['metric'] for row in startup['rows'] if row['simulation'] is None])
            finally:
                raw.close()


if __name__=='__main__':
    unittest.main()
