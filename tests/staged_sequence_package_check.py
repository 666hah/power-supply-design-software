"""Evidence packaging tests; no simulator and no Word artifact creation."""
from pathlib import Path
import sys,tempfile,unittest,zipfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.package_staged_sequence_example import package_files,write_archive,model_approximations,ocp_observation


class PackageTests(unittest.TestCase):
    def test_original_raw_once_no_nested_archives_or_qa(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as temporary:
            folder=Path(temporary);run=folder/'normal'/'frozen';run.mkdir(parents=True)
            for name in ('Flyback.raw','manifest.json','source-1.png','child.zip','page-1.png','qa/page-2.png'):
                file=run/name;file.parent.mkdir(exist_ok=True);file.write_bytes(b'synthetic')
            (folder/'report.docx').write_bytes(b'synthetic')
            (folder/'unrelated.raw').write_bytes(b'synthetic')
            selected=package_files(folder,{'normal':run},'report.docx',False)
            self.assertEqual({p.name for p in selected},{'Flyback.raw','manifest.json','source-1.png','report.docx'})

    def test_archive_reuse_is_hash_bound_and_changed_raw_rebuilds(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts') as temporary:
            folder=Path(temporary);run=folder/'normal'/'frozen';run.mkdir(parents=True)
            raw=run/'Flyback.raw';raw.write_bytes(b'synthetic full RAW '+b'x'*10000)
            first=write_archive(folder,{'normal':run},'report.docx',False)
            self.assertFalse(first['reused'])
            with zipfile.ZipFile(first['path']) as archive:
                self.assertEqual(archive.namelist(),['normal/frozen/Flyback.raw'])
                self.assertEqual(archive.read(archive.namelist()[0]),raw.read_bytes())
            self.assertTrue(write_archive(folder,{'normal':run},'report.docx',False)['reused'])
            raw.write_bytes(b'changed full RAW')
            self.assertFalse(write_archive(folder,{'normal':run},'report.docx',False)['reused'])

    def test_report_reads_frozen_approximation_declarations(self):
        source='源平滑夹限 0.1%'
        diode='连接二极管 epsilon=1u'
        switch='MOS连续开关 Vh=-0.2VG'
        age='振荡器age采用有限回零，周期保持原值'
        found=model_approximations({'normal':dict(limitations=[source,diode],units={'U':dict(compiled_manifest=dict(limitations=[switch,age]))}),
            'slow':dict(limitations=[source,'其他说明'])})
        self.assertEqual(found,[source,diode,switch,age])
        # Production Buck manifests store these under approximation_notes.
        continuous='通用MOS使用有限连续电导过渡，半宽0.2×VG'
        actual=model_approximations({'normal':dict(units={'U':dict(compiled_manifest=dict(
            approximation_notes=[continuous,age,'器件参数来源说明']))})})
        self.assertEqual(actual,[continuous,age])

    def test_ocp_summary_keeps_unknown_separate_from_fault_false(self):
        unknown=ocp_observation(dict(cycle_limit=dict(hit=None,observed_cycle_count=0),fault_observed=False))
        self.assertIn('未知',unknown)
        self.assertNotIn('明确状态未命中',unknown)
        self.assertIn('未观察到FAULT',unknown)
        positive=ocp_observation(dict(cycle_limit=dict(hit=True,observed_cycle_count=7),fault_observed=None))
        self.assertIn('周期数≥7',positive)
        self.assertIn('FAULT未知',positive)


if __name__=='__main__':unittest.main()
