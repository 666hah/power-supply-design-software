"""Native workbook navigation, numeric evidence and incomplete-result projection."""
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from engineering_workbook import index, page, table, verdict
from xlsx_report_writer import S, save_workbook


class EngineeringWorkbookChecks(unittest.TestCase):
    def test_summary_links_keep_destination_and_typed_numeric_evidence(self):
        summary=page('评审结论','台架验证',freeze_rows=0)
        row=verdict(summary,4,'待复核','高线尚缺证据。','review')
        index(summary,row+1,[('联合·器件','查看器件','额定电压')])
        details=page('联合·器件','器件数据',widths=(26,16,18))
        table(details,4,('位号','电压 / V','状态'),[('D1',49.25,'pass')],state_col=2)
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'report.xlsx'
            save_workbook(target,[summary,details])
            with ZipFile(target) as report:
                self.assertIsNone(report.testzip())
                cover=ElementTree.fromstring(report.read('xl/worksheets/sheet1.xml'))
                page2=ElementTree.fromstring(report.read('xl/worksheets/sheet2.xml'))
        tag=lambda name:f'{{{S}}}{name}'
        location=cover.find('.//'+tag('hyperlink')).attrib['location']
        self.assertEqual(location,"'联合·器件'!A1")
        self.assertIsNone(cover.find('.//'+tag('pane')))
        value=page2.find(f".//{tag('c')}[@r='B5']")
        self.assertEqual(value.attrib['t'],'n')
        self.assertEqual(float(value.find(tag('v')).text),49.25)

    def test_partial_circuit_report_preserves_reason_without_invented_waveforms(self):
        from spice_comparison_xlsx import write_spice_xlsx

        evidence=dict(model='Test schema',topology='QR-FLYBACK',input_range_V=[252.,442.],
                      settings={'fra_enabled':1},cases=[
                          dict(id='Vinmin_标称负载',voltage=252.,complete=False,error='超出观察窗口')])
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'partial.xlsx'
            write_spice_xlsx(target,evidence)
            with ZipFile(target) as report:
                self.assertIsNone(report.testzip())
                cover=report.read('xl/worksheets/sheet1.xml').decode('utf-8')
                self.assertIn('超出观察窗口',cover)
                self.assertNotIn('全部满足',cover)
                self.assertFalse(any(n.startswith('xl/media/') for n in report.namelist()))


if __name__=='__main__':
    unittest.main()
