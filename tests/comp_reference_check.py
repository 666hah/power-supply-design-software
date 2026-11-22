"""Check desktop vector feedback views and report image assets."""
import argparse
from pathlib import Path
import sys
from time import monotonic
import tkinter as tk
from tkinter import font, ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_resources import resource_path
from compensation_report import NETWORKS
import feedback_compensation_diagram
import main


def labels(axis):
    return {item.get_text() for item in axis.texts}


def canvas_labels(view):
    canvas = view.canvas
    return {canvas.itemcget(item, 'text') for item in canvas.find_withtag('scene')
            if canvas.type(item) == 'text'}


def tool_buttons(widget):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.winfo_ismapped():
            yield child
        yield from tool_buttons(child)


def hidden_toplevel(parent):
    window = tk.Toplevel(parent)
    window.attributes('-alpha', 0)
    return window


def wait_for(root, predicate, message):
    deadline = monotonic() + 3.
    while monotonic() < deadline:
        root.update()
        if predicate():
            return
        root.after(15)
    raise AssertionError(message())


def check_canvas_controls(root, view, symbol, *, minimum_height=175):
    canvas = view.canvas
    buttons = {button.cget('text'): button for button in tool_buttons(view)}
    for name in ('−', '+', '适合窗口', '放大查看'):
        button = buttons[name]
        assert button.winfo_width() >= button.winfo_reqwidth(), name
        assert button.winfo_rootx() + button.winfo_width() <= view.winfo_rootx() + view.winfo_width(), name
    buttons['适合窗口'].invoke()
    root.update()
    items = canvas.find_withtag('scene')
    assert items and all(canvas.type(item) != 'image' for item in items)
    label = next(item for item in items if canvas.type(item) == 'text'
                 and canvas.itemcget(item, 'text') == symbol)
    label_font = font.nametofont(canvas.itemcget(label, 'font'), root=root)
    width, height = canvas.winfo_width(), canvas.winfo_height()
    x0, y0, x1, y1 = canvas.bbox('scene')
    assert width >= 350 and height >= minimum_height, (width, height)
    assert x1-x0 >= min(width * .62, height), (width, height, x0, x1)
    assert x0 >= canvas.canvasx(0) - 2 and x1 <= canvas.canvasx(width) + 2, (x0, x1, width)
    assert y0 >= canvas.canvasy(0) - 2 and y1 <= canvas.canvasy(height) + 2, (y0, y1, height)
    initial_scale = view.scale
    initial_font_size = abs(label_font.cget('size'))
    for _ in range(4):
        buttons['+'].invoke()
        if abs(label_font.cget('size')) > initial_font_size:
            break
    root.update()
    assert view.scale > initial_scale and abs(label_font.cget('size')) > initial_font_size
    left = canvas.canvasx(0)
    canvas.event_generate('<ButtonPress-1>', x=75, y=90)
    canvas.event_generate('<B1-Motion>', x=130, y=90)
    canvas.event_generate('<ButtonRelease-1>', x=130, y=90)
    root.update()
    assert canvas.canvasx(0) < left, (canvas.canvasx(0), left)
    assert canvas.find_withtag('scene') == items
    buttons['适合窗口'].invoke()
    root.update()
    assert abs(view.scale - initial_scale) < .001
    return initial_scale


def fits_vertically(widget, viewport):
    top = widget.winfo_rooty()
    return (viewport.winfo_rooty() <= top
            and top + widget.winfo_height() <= viewport.winfo_rooty() + viewport.winfo_height())


def check_text_priority(app):
    pane = app._comp_scroll
    diagram = app._comp_diagram_view
    assert pane.winfo_rooty() + pane.winfo_height() <= diagram.winfo_rooty()
    assert pane.winfo_height() >= max(220, diagram.winfo_height()), (
        pane.winfo_height(), diagram.winfo_height())
    label = app._comp_result_label
    assert fits_vertically(label, pane.canvas), (
        label.winfo_rooty() - pane.canvas.winfo_rooty(), label.winfo_height(), pane.canvas.winfo_height())
    assert 0 < int(label.cget('wraplength')) <= label.winfo_width()
    assert label.winfo_reqheight() <= label.winfo_height()


def check_long_form_scroll(root, app):
    canvas = app._comp_scroll.canvas
    canvas.yview_moveto(0)
    root.update()
    assert canvas.yview()[1] < 1.
    final_field = app.comp_inframe.winfo_children()[-1]
    canvas.yview_moveto(1)
    root.update()
    assert canvas.yview()[0] > 0.
    assert fits_vertically(final_field, canvas)
    assert fits_vertically(app.guide_comp, canvas)
    canvas.yview_moveto(0)
    root.update()


def open_large(root, view):
    button = next(button for button in tool_buttons(view) if button.cget('text') == '放大查看')
    with patch('topology_canvas.Toplevel', side_effect=hidden_toplevel):
        button.invoke()
    root.update()
    large = view._large_view
    assert large is not None and large.canvas.winfo_ismapped()
    window = large.winfo_toplevel()
    assert window.bind('<Escape>')
    assert view.show_large() is window
    # The hidden test desktop can be smaller than the forced main window.
    window.state('normal')
    window.maxsize(1920, 1080)
    window.geometry('1120x740+0+0')
    root.update()
    return large, window


def check_shared_views(root, app):
    assert app.update_all(), app.status_var.get()
    root.update()
    snapshot = app._last
    render = feedback_compensation_diagram.draw_compensation_network
    with patch.object(feedback_compensation_diagram, 'draw_compensation_network', wraps=render) as draw, \
            patch.object(app, 'schedule_update') as schedule, \
            patch.object(app, 'request_update') as request, \
            patch('input_voltage_range.calculate_input_operating_point') as solve:
        root.maxsize(1920, 1080)
        root.geometry('1040x700')
        app.restore_result_page('comp')
        root.update()
        app.comp_type.set(dict(app.COMP_TOPOS)['tl431nf'])
        app.comp_dir.set('fwd')
        app._on_comp_dir_change()
        wait_for(root, lambda: '回代校验' in app.comp_result.get() and 'D_Z' in labels(app.ax_comp),
                 lambda: f'Compensation summary did not update: {app.comp_result.get()}')
        check_text_priority(app)
        app.comp_dir.set('rev')
        app._on_comp_dir_change()
        app.comp_vars['C2'].set(1.)
        wait_for(root, lambda: 'D_Z' in labels(app.ax_comp) and 'C2' in labels(app.ax_comp),
                 lambda: f'Compensation drawing did not show C2: {app.status_var.get()}')
        view = app._comp_diagram_view
        check_long_form_scroll(root, app)
        compact_scale = check_canvas_controls(root, view, 'D_Z', minimum_height=100)
        large, window = open_large(root, view)
        assert large.scale > compact_scale * 1.15, (large.scale, compact_scale)
        assert 'C2' in canvas_labels(large)
        app.comp_vars['C2'].set(0.)
        wait_for(root, lambda: 'D_Z' in labels(app.ax_comp) and 'C2' not in labels(app.ax_comp),
                 lambda: f'Compensation drawing did not remove C2: {app.status_var.get()}')
        assert 'C2' not in canvas_labels(large) and 'D_Z' in canvas_labels(large)
        window.destroy()
        assert view._large_view is None
        root.geometry('1500x940')
        root.update()
        check_text_priority(app)
        assert check_canvas_controls(root, view, 'D_Z') > compact_scale
        result_page = draw.call_args
        assert result_page.args[1] == 'tl431nf'
        assert result_page.kwargs['snapshot']['parts']['C2'] == 0.

        app.restore_result_page('topology')
        wait_for(root, lambda: 'D_Z' in labels(app.ax_topology) and 'C2' not in labels(app.ax_topology),
                 lambda: f'Topology did not pick up the compensation state: {app.status_var.get()}')
        topology_page = draw.call_args
        assert topology_page.args[1] == result_page.args[1]
        for name in ('snapshot', 'sense_net', 'sense_ground', 'controller_ground', 'output_net'):
            assert topology_page.kwargs[name] == result_page.kwargs[name], name

        view = app.topology_view
        root.geometry('1040x700')
        root.update()
        view.fit()
        overview_scale = view.scale
        large, window = open_large(root, view)
        assert large._focus_region == 'feedback_loop'
        assert large.scale > overview_scale * 1.5, (large.scale, overview_scale)
        assert {'D_Z', 'TL431', 'COMP'} <= canvas_labels(large)
        assert all(large.canvas.type(item) != 'image' for item in large.canvas.find_withtag('scene'))
        app.restore_result_page('comp')
        app.comp_vars['C2'].set(1.)
        wait_for(root, lambda: 'C2' in canvas_labels(large),
                 lambda: 'Topology popout did not refresh across the result-tab switch')
        window.destroy()
        assert view._large_view is None
        assert app._last is snapshot and app._snapshot_valid
        schedule.assert_not_called()
        request.assert_not_called()
        solve.assert_not_called()


def check(bundle=None):
    root = tk.Tk()
    root.attributes('-alpha', 0)
    root.geometry('1440x900')
    with patch.object(main.PowerSupplyAnalyzer, 'schedule_update'), \
            patch.object(main.PowerSupplyAnalyzer, 'request_update'):
        app = main.PowerSupplyAnalyzer(root)
    try:
        app.restore_result_page('comp')
        root.update()
        parts = {'opamp3': 'EA', 'gm3': 'gm', 'tl431nf': 'D_Z', 'tl431f': 'TL431'}
        for key, title in app.COMP_TOPOS:
            app.comp_type.set(title)
            app._draw_comp_schematic()
            assert not app.ax_comp.images, key
            assert app.ax_comp.lines, key
            assert parts[key] in labels(app.ax_comp), (key, labels(app.ax_comp))
            assert parts[key] in canvas_labels(app._comp_diagram_view), key
        check_shared_views(root, app)
        print('Source: text-first layout, scrolling, all four vector networks, fit, zoom, pan and live large views verified.')

        if bundle is not None:
            bundle = Path(bundle).resolve()
            with patch.object(sys, '_MEIPASS', str(bundle), create=True):
                for _, filename in NETWORKS.values():
                    path = resource_path(Path('comp_images') / filename)
                    assert path == bundle / 'comp_images' / filename and path.is_file(), path
            print('Bundle: all four compensation report images are present.')
    finally:
        app.dispose()
        root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle')
    check(parser.parse_args().bundle)
