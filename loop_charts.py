"""Shared frequency and time-domain response plots."""
import numpy as np


def draw_feedback_load_step(axes, data):
    """Plot the same two feedback-port current steps on a common scale."""
    from matplotlib.ticker import MaxNLocator

    axes = np.asarray(axes).ravel()
    for ax in axes:
        ax.clear()
        ax.set_axis_on()
    if not data.get('available'):
        for ax in axes:
            ax.set_axis_off()
        axes[0].text(.5, .5, data['reason'], ha='center', va='center',
                     transform=axes[0].transAxes, wrap=True, fontsize=10)
        return axes

    nominal = data['output_voltage_V']
    low, high = data['current_low_A'], data['current_high_A']
    time = np.asarray(data['time_s']) * 1e3
    def plot(ax, key, direction, current, color, extreme):
        voltage = np.asarray(data[f'{key}_voltage_V'])
        metrics = data[key]
        peak = extreme(voltage[2:]) + 2
        ax.plot(time, voltage, color=color, lw=1.65)
        ax.axhline(metrics['final_voltage_V'], color='#73879b', lw=.8, ls='--')
        ax.axvline(0, color='#a1afbc', lw=.8, ls=':')
        ax.scatter(time[peak], voltage[peak], color=color, s=18, zorder=4)
        settled = metrics['settling_s']
        recovery = f'{settled*1e3:.3g} ms' if settled is not None else '观察窗内未恢复'
        ax.set_title(f'{direction}　{current}\n'
                     f"压降 {metrics['droop_V']*1e3:.3g} mV · 过冲 {metrics['overshoot_V']*1e3:.3g} mV · 恢复 {recovery}",
                     fontsize=10, pad=8)
        ax.set_xlim(time[0], time[-1])
        ax.set_xlabel('时间 / ms（0 为阶跃）', fontsize=10)
        ax.yaxis.set_major_locator(MaxNLocator(6))
        ax.tick_params(labelsize=9)
        ax.grid(True, alpha=.24)

    plot(axes[0], 'rise', '升载 10% → 90%', f'{low:.4g} → {high:.4g} A', '#2064b0', np.argmin)
    plot(axes[1], 'fall', '降载 90% → 10%', f'{high:.4g} → {low:.4g} A', '#a05317', np.argmax)
    minimum = min(data['rise']['min_V'], data['fall']['min_V'])
    maximum = max(data['rise']['max_V'], data['fall']['max_V'])
    pad = max(.08*(maximum-minimum), .0001*nominal)
    for ax in axes:
        ax.set_ylim(minimum-pad, maximum+pad)
        ax.ticklabel_format(axis='y', style='plain', useOffset=False)
    axes[0].set_ylabel(f"OUT{data['feedback_output']} 端口电压 / V", fontsize=10)
    return axes


def draw_multi_output_response(axes, loop, load_output=1):
    """All rails share one feedback denominator; no per-rail PM labels."""
    data = loop['multi_output']
    axes = np.asarray(axes).reshape(2, 2)
    for ax in axes.flat:
        ax.clear(); ax.set_axis_on()
    f = loop['f']
    for index, rail in enumerate(data['outputs']):
        label = f'OUT{rail["id"]}' + (' ★ 反馈' if rail['id'] == data['feedback_output'] else '')
        gain = data['reference'][index]
        axes[0, 0].semilogx(f, 20*np.log10(np.maximum(np.abs(gain), 1e-300)), label=label)
        axes[0, 1].semilogx(f, np.degrees(np.unwrap(np.angle(gain))), label=label)
    axes[0, 0].set(title='主参考到各路电压 · 相对变化率', ylabel='dB（% / %）')
    axes[0, 1].set(title='主参考跟踪相位', ylabel='deg')
    load = data['load']
    if load is not None:
        selected = min(max(int(load_output)-1, 0), len(data['outputs'])-1)
        for index, rail in enumerate(data['outputs']):
            label = f'OUT{rail["id"]}'
            gain = load[index, selected]
            axes[1, 0].loglog(f, np.maximum(np.abs(gain), 1e-14), label=label)
            axes[1, 1].semilogx(f, np.degrees(np.unwrap(np.angle(gain))), label=label)
        axes[1, 0].set(title=f'OUT{selected+1} 负载扰动 → 各路电压', ylabel='|ΔV / ΔI| / Ω')
        axes[1, 1].set(title=f'OUT{selected+1} 负载响应相位', ylabel='deg')
    else:
        for ax in axes[1]:
            ax.text(.5, .5, '理想匝比近似未建立独立负载动态\n不绘制虚假的交叉调整率曲线',
                    ha='center', va='center', transform=ax.transAxes, fontsize=10)
            ax.set_axis_off()
    for ax in axes.flat:
        if ax.axison:
            ax.set_xlabel('频率 / Hz', fontsize=9)
            ax.title.set_fontsize(10)
            ax.yaxis.label.set_fontsize(9)
            ax.tick_params(labelsize=8)
            ax.grid(True, which='both', alpha=.2)
            ax.legend(fontsize=8)
    return axes
