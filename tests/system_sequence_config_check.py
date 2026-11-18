"""Focused SI configuration contracts; no solver, UI or user profile access."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from system_sequence_config import normalize


class SequenceLoadPriorityChecks(unittest.TestCase):
    def setUp(self):
        self.project = json.loads((ROOT/'examples/SYSTEM_STAGED_STARTUP.json').read_text('utf8'))
        self.config = copy.deepcopy(self.project['sequence_config'])
        self.load = self.config['loads']['LOAD-3V3']
        self.load['on_V'] = self.load['off_V'] = None
        for stage in self.load['stages']:
            stage['mode'] = 'R'

    def test_resistive_stages_override_inactive_legacy_current_or_power(self):
        for legacy_mode in ('I', 'P'):
            with self.subTest(legacy_mode=legacy_mode):
                self.load['mode'] = legacy_mode
                original = copy.deepcopy(self.config)
                resolved = normalize(self.project, self.config)
                row = resolved['loads']['LOAD-3V3']
                self.assertIsNone(row['on_V'])
                self.assertIsNone(row['off_V'])
                self.assertEqual(row['mode'], legacy_mode)
                self.assertEqual(row['stages'], self.load['stages'])
                self.assertEqual(self.config, original)

    def test_any_current_or_power_stage_requires_positive_thresholds(self):
        self.load['mode'] = 'R'
        for stage_mode in ('I', 'P'):
            for off in (None, 0.):
                with self.subTest(stage_mode=stage_mode, off=off):
                    self.load['stages'][1]['mode'] = stage_mode
                    self.load['on_V'] = None if off is None else 3.05
                    self.load['off_V'] = off
                    with self.assertRaisesRegex(ValueError, '正的耗功启停电压'):
                        normalize(self.project, self.config)
            self.load['on_V'], self.load['off_V'] = 3.05, 2.75
            self.assertEqual(normalize(self.project, self.config)['loads']['LOAD-3V3']['stages'][1]['mode'], stage_mode)

    def test_empty_stages_restore_legacy_threshold_requirement(self):
        self.load['stages'] = []
        for legacy_mode in ('I', 'P'):
            with self.subTest(legacy_mode=legacy_mode):
                self.load['mode'] = legacy_mode
                with self.assertRaisesRegex(ValueError, '正的耗功启停电压'):
                    normalize(self.project, self.config)
        self.load['mode'] = 'R'
        self.assertEqual(normalize(self.project, self.config)['loads']['LOAD-3V3']['stages'], [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
