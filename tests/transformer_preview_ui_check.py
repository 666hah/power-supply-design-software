"""Preview isolation, owned transport and bounded screenshot validation."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transformer_preview_host import decode_png, read_scene, write_json, _watch_parent
from transformer_preview_ui import make_scene, worker_command, refresh_from_result, refresh_preview


class PreviewIntegrationChecks(unittest.TestCase):
    def test_owned_scene_roundtrip_and_reject_non_object(self):
        base = Path(__file__).resolve().parents[1] / 'artifacts' / 'transformer-preview-qa'
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as temp:
            path = Path(temp) / 'scene.json'
            value = {'title': '当前绕组', 'turns': [1, 2], 'core': {'name': 'PQ32-30'}}
            write_json(path, value)
            self.assertEqual(read_scene(path), value)
            write_json(path, {'title': '新场景'})
            self.assertEqual(read_scene(path), {'title': '新场景'})
            self.assertFalse(path.with_suffix('.json.tmp').exists())
            path.write_text('[]')
            with self.assertRaises(ValueError):
                read_scene(path)

    def test_invalid_png_never_reaches_save_dialog(self):
        for bad in ['file:///private', 'data:text/plain;base64,eA==',
                    'data:image/png;base64,###', 'data:image/png;base64,eA==', None]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                decode_png(bad)
        png = b'\x89PNG\r\n\x1a\n' + b'bounded_test_payload'
        self.assertEqual(decode_png('data:image/png;base64,' + base64.b64encode(png).decode()), png)

    def test_scene_consumes_current_geometry_and_resolved_core_without_mutating(self):
        profile = {'source': 'user profile'}
        wires = [{'id': 'P', 'turns': 12}]
        cfg = {'turn_positions': {'P_A': {'T1': .003}}}
        app = types.SimpleNamespace(_winding_preview_state={'core': 'PQ32-30', 'gap': {'gap_m': .0003}},
            _winding_source=wires, _geometry_profile=profile, _snapshot_valid=False,
            _winding_config=lambda: {'winding_config': copy.deepcopy(cfg)})
        seen = {}
        def builder(core, passed_wires, passed_cfg, **kwargs):
            seen.update(core=core, wires=copy.deepcopy(passed_wires), config=passed_cfg, **kwargs)
            passed_wires[0]['turns'] = 999
            kwargs['profile']['source'] = 'modified'
            return {'test': True}
        fake = types.SimpleNamespace(build_scene=builder)
        with patch.dict(sys.modules, {'transformer_preview_scene': fake}):
            self.assertEqual(make_scene(app), {'test': True})
        self.assertEqual(seen['core'], 'PQ32-30')
        self.assertEqual(seen['config'], cfg)
        self.assertTrue(seen['stale'])
        self.assertEqual(wires[0]['turns'], 12)
        self.assertEqual(profile['source'], 'user profile')

    def test_worker_is_separate_process_and_no_shell_command(self):
        path = Path('some folder') / 'scene.json'
        argv = worker_command(path)
        self.assertIn(str(path), argv)
        self.assertEqual(argv[0], sys.executable)
        self.assertIn('--parent-pid', argv)
        self.assertTrue(argv[1].endswith('transformer_preview_host.py'))

    def test_parent_watch_is_read_only_and_reports_live_process(self):
        import os
        alive, dispose = _watch_parent(os.getpid())
        try:
            self.assertTrue(alive())
        finally:
            dispose()

    def test_loading_desktop_preview_controller_does_not_load_webview(self):
        self.assertNotIn('webview', sys.modules)

    def test_non_transformer_result_clears_old_assembly(self):
        published = []
        session = types.SimpleNamespace(closed=False, process=types.SimpleNamespace(poll=lambda: None),
            publish=published.append)
        app = types.SimpleNamespace(_transformer_preview=session, _winding_source=[{'id': 'P'}],
            _winding_preview_state={'core': 'PQ32-30'})
        refresh_from_result(app, {'mag': {'inductor': {'core': 'EE22'}}})
        self.assertEqual(published[0]['windings'], [])
        self.assertEqual(published[0]['core']['model'], '当前拓扑无变压器')
        self.assertIsNone(app._winding_preview_state['core'])

    def test_failed_geometry_refresh_is_explicitly_stale_with_new_signature(self):
        published = []
        session = types.SimpleNamespace(closed=False, process=types.SimpleNamespace(poll=lambda: None),
            _last=json.dumps({'signature': 'old', 'windings': [{'id': 'P'}]}), publish=published.append)
        app = types.SimpleNamespace(_transformer_preview=session)
        with patch('transformer_preview_ui.make_scene', side_effect=ValueError('净窗口高度无效')):
            refresh_preview(app)
        self.assertTrue(published[0]['stale'])
        self.assertNotEqual(published[0]['signature'], 'old')
        self.assertIn('净窗口高度无效', published[0]['notes'][0])


if __name__ == '__main__':
    unittest.main()
