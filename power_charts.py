"""Shared power-page/report chart contents, independent of Tk and pyplot.

Layouts can differ for print readability, but labels, samples, units and MOS
stage reconstruction must have a single implementation.
"""
import numpy as np
from matplotlib import rc_context

from power_stage import fmt_eng
from switching_transients import switching_voltage_data, draw_switching_event

POWER_CHART_STYLE = {
    'font.sans-serif': ['Microsoft YaHei', 'SimHei', 'DejaVu Sans'],
    'axes.unicode_minus': False,
    'axes.facecolor': '#ffffff', 'axes.edgecolor': '#c9d2dc',
    'axes.labelcolor': '#22303c', 'axes.titlecolor': '#22303c',
    'axes.titleweight': 'bold', 'axes.spines.top': True, 'axes.spines.right': True,
    'xtick.color': '#5b6b7a', 'ytick.color': '#5b6b7a',
    'axes.grid': True, 'grid.color': '#e6ebf1', 'grid.linewidth': .8,
}


def power_signals(topology):
    label = ('副边二极管电流 D1' if topology in
             ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD') else '二极管电流 D1')
    return [('i_sw', 'MOS 电流 Q1', 'A'), ('i_d', label, 'A'),
            ('vout_ripple', '输出纹波 v_rip', 'mV'), ('vout', '输出电压 v_out', 'V')]


def display_power_waveform(wf):
    """Use the imported impedance result in the plotted voltage when available."""
    ripple = wf.get('vout_ripple_impedance')
    if ripple is None:
        return wf, False
    return dict(wf, vout_ripple=ripple,
                vout=np.asarray(wf['vout']) - np.asarray(wf['vout_ripple']) + ripple), True


def _draw_power_signals(axes, topology, wf):
    """Draw the first four power charts in GUI row-major order."""
    wf, has_curve = display_power_waveform(wf)
    if 'iL_phases' in wf:
        _draw_cot_signals(axes, wf, has_curve=has_curve)
        return
    for ax, (key, label, unit) in zip(np.asarray(axes).ravel(), power_signals(topology)):
        ax.clear()
        if has_curve and key in ('vout_ripple', 'vout'):
            label += '（按导入阻抗）'
        y = np.asarray(wf[key])
        scale = 1e3 if unit == 'mV' else 1.0
        ax.plot(wf['t'] * 1e6, y * scale, lw=1.2,
                color='#b03a2e' if unit == 'mV' else
                      ('#1a7f37' if key == 'vout' else '#1558b0'))
        pk = float(np.max(np.abs(y))) if len(y) else 0.0
        rms = float(np.sqrt(np.mean(y ** 2)))
        ax.set_title(f'{label}\nrms={fmt_eng(rms*scale, unit)}  '
                     f'pk={fmt_eng(pk*scale, unit)}', fontsize=10)
        ax.set_xlabel('时间 / μs', fontsize=8)
        ax.set_ylabel(unit, fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(True)


def _draw_cot_signals(axes, wf, *, has_curve=False):
    from matplotlib import colormaps
    axes = np.asarray(axes).ravel()
    t = wf['t'] * 1e6
    phases = np.asarray(wf['iL_phases'])
    for ax in axes:
        ax.clear()
        ax.set_xlabel('时间 / μs', fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(True)
    ax = axes[0]
    rms = np.sqrt(np.mean(phases**2, axis=1))
    peak = np.max(np.abs(phases), axis=1)
    worst_rms = int(np.argmax(rms))
    worst_peak = int(np.argmax(peak))
    colors = colormaps['turbo'](np.linspace(.08, .91, len(phases)))
    for i, (curve, color) in enumerate(zip(phases, colors), 1):
        ax.plot(t, curve, label=f'相 {i} · {rms[i-1]:.3g} / {peak[i-1]:.3g}',
                color=color, lw=1.65 if i-1 in (worst_rms, worst_peak) else .9)
    if len(phases) <= 4:
        ax.legend(loc='best', fontsize=6.5, ncol=2,
                  title='相 · RMS / |峰值|（A）', title_fontsize=6.5)
    else:
        # Reserve a data-free area within this subplot. An external 16-row
        # legend would overlap its neighbours in the desktop's 2 x 3 layout.
        end = float(t[-1])
        span = max(end-float(t[0]), np.finfo(float).eps)
        ax.set_xlim(float(t[0])-.04*span, end+1.28*span)
        ax.set_xticks(np.linspace(float(t[0]), end, 3))
        ax.axvspan(end+.06*span, end+1.28*span, color='#f3f6fa', zorder=2)
        rows = (len(phases)+1)//2
        ax.text(.48, .97, '相 · RMS / |峰值|（A）', transform=ax.transAxes,
                va='top', fontsize=6.5, color='#22303c', zorder=3)
        for i, color in enumerate(colors):
            col, row = divmod(i, rows)
            ax.text(.48+.26*col, .83-.1*row,
                    f'{i+1:02d}  {rms[i]:.3g} / {peak[i]:.3g}',
                    transform=ax.transAxes, va='top', fontsize=6.5,
                    color=np.asarray(color[:3])*.55,
                    fontweight='bold' if i in (worst_rms, worst_peak) else 'normal',
                    zorder=3)
    ax.set_title(f'各相电感电流 · {len(phases)} 相\n'
                 f'最大 RMS：相 {worst_rms+1} · {rms[worst_rms]:.3g} A\n'
                 f'最大 |峰值|：相 {worst_peak+1} · {peak[worst_peak]:.3g} A', fontsize=9)
    ax.set_ylabel('A', fontsize=8)
    ripple_title = '公共输出纹波（按导入阻抗）' if has_curve else '公共输出端低频纹波'
    for ax, (key, title, u, scale, color) in zip(axes[1:], (
            ('iL_total', '电感汇流电流', 'A', 1., '#1558b0'),
            ('i_in', '各相合计输入电流', 'A', 1., '#207844'),
            ('vout_ripple', ripple_title, 'mV', 1e3, '#b03a2e'))):
        y = np.asarray(wf[key]) * scale
        ax.plot(t, y, color=color, lw=1.15)
        ax.set_ylabel(u, fontsize=8)
        pkpk = float(np.ptp(y))
        ax.set_title(f'{title}\n峰峰值 {pkpk:.4g} {u}', fontsize=10)


def _draw_power_switching(axes, op, p, res, *, real_time=False, drain_axes=None):
    """Draw the last two power charts and return their common time data."""
    data = switching_voltage_data(op, p, res['semi']['switch'])
    drains = (None, None) if drain_axes is None else drain_axes
    for ax, drain, event in zip(np.asarray(axes).ravel(), drains, ('on', 'off')):
        draw_switching_event(ax, data, event, real_time=real_time, drain_ax=drain)
        if op.get('cot'):
            ax.set_title('代表相高侧 · '+ax.get_title())
    return data


def draw_power_signals(axes, topology, wf):
    """Use the same chart theme even when exporting without visiting the GUI."""
    with rc_context(POWER_CHART_STYLE):
        _draw_power_signals(axes, topology, wf)


def draw_power_switching(axes, op, p, res, *, real_time=False, drain_axes=None):
    with rc_context(POWER_CHART_STYLE):
        return _draw_power_switching(axes, op, p, res,
                                     real_time=real_time, drain_axes=drain_axes)
