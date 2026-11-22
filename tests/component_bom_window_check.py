"""BOM editor draft handling in a test-owned Tk instance."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from component_ui import ComponentManager
from power_stage import DEFAULT_PARAMS


class ComponentDraftChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0)
        self.root.update()
        self.addCleanup(self.root.destroy)
        self.params = dict(DEFAULT_PARAMS, topology='BUCK', d_in_enable=True, outputs=[])
        self.context = Mock(side_effect=lambda: (self.params, None))
        self.selection = Mock(return_value=True)
        self.changed = Mock(side_effect=lambda value: self.params.update(component_management=value))
        self.manager = ComponentManager(self.root, self.context, self.changed,
                                        on_select=self.selection)
        self.manager.refresh()

    def test_dirty_selection_cancel_and_apply_event_once(self):
        manager = self.manager
        self.assertTrue(manager.select_ref('Q1'))
        manager.draft['model'].set('retain until accepted')
        with patch('component_ui.messagebox.askyesnocancel', return_value=None) as ask:
            self.assertFalse(manager.select_ref('D_IN'))
            manager.tree.selection_set('D_IN')
            manager.select()
            self.assertEqual(ask.call_count, 2)
        self.assertEqual(manager.current, 'Q1')
        self.assertEqual(manager.tree.selection(), ('Q1',))
        self.assertEqual(manager.draft['model'].get(), 'retain until accepted')
        self.selection.assert_not_called()

        with patch('component_ui.messagebox.askyesnocancel', return_value=False):
            self.assertFalse(manager.select_ref('D_IN', before_commit=lambda: False))
        self.assertEqual(manager.current, 'Q1')
        self.assertEqual(manager.draft['model'].get(), 'retain until accepted')

        with patch('component_ui.messagebox.askyesnocancel', return_value=True):
            manager.tree.selection_set('D_IN')
            manager.select()
        self.root.update()
        self.selection.assert_called_once_with('D_IN')
        self.assertEqual(self.params['component_management']['items']['Q1']['model'], 'retain until accepted')
        self.assertEqual(manager.current, 'D_IN')
        self.selection.return_value = False
        manager.tree.selection_set('Q1')
        manager.select()
        self.assertEqual(manager.tree.selection(), ('D_IN',))

    def test_refresh_keeps_unapplied_retired_item(self):
        manager = self.manager
        self.assertTrue(manager.select_ref('D_IN'))
        manager.draft['model'].set('retired draft')
        self.params['d_in_enable'] = False
        manager.refresh()
        self.assertFalse(manager.tree.exists('D_IN'))
        self.assertEqual(manager.current, 'D_IN')
        self.assertEqual(manager.draft['model'].get(), 'retired draft')
        with patch('component_ui.messagebox.askyesnocancel', return_value=None):
            self.assertFalse(manager.confirm_draft())
        self.assertEqual(manager.draft['model'].get(), 'retired draft')
        with patch('component_ui.messagebox.askyesnocancel', return_value=True):
            self.assertTrue(manager.confirm_draft())
        self.assertEqual(self.params['component_management']['items']['D_IN']['model'], 'retired draft')

    def test_apply_metadata_while_calculation_inputs_are_invalid(self):
        manager = self.manager
        self.assertTrue(manager.select_ref('Q1'))
        self.context.side_effect = ValueError('当前电气参数无效')
        manager.draft['model'].set('applied while inputs are invalid')
        self.assertTrue(manager.apply_item())
        self.assertEqual(self.params['component_management']['items']['Q1']['model'], 'applied while inputs are invalid')
        self.assertIn('待重新计算', manager.selected_label.get())
        with patch('component_ui.messagebox.askyesnocancel') as ask:
            self.assertTrue(manager.select_ref('D_IN'))
        ask.assert_not_called()


if __name__ == '__main__':
    unittest.main()
