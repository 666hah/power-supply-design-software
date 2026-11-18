"""Report views of measured load transients and component-level RAW evidence."""

from dataclasses import dataclass
import re

import numpy as np


def _finish_axes(axes, xlabel='时间 / ms'):
    for axis in np.atleast_1d(axes).ravel():
        axis.grid(alpha=.2)
        if axis.get_legend_handles_labels()[0]:
            axis.legend(fontsize=7, loc='best')
    np.atleast_1d(axes).ravel()[-1].set_xlabel(xlabel)


def draw_load_step(fig, transient):
    data = transient['waveform']
    time = np.asarray(data['time']) * 1e3
    feedback = str(transient.get('feedback_output', 1))
    ports = data.get('ports') or {feedback: data['voltage']}
    others = {rail: values for rail, values in ports.items() if str(rail) != feedback}
    load = data.get('load_fraction')
    if load is not None and len(load) != len(time):
        load = None
    axes = np.atleast_1d(fig.subplots(1 + bool(others) + (load is not None), 1, sharex=True))
    output = axes[0]
    output.plot(time, data['voltage'], label=f'反馈端口 OUT{feedback}')
    reference = transient.get('reference_v')
    if reference is not None:
        radius = reference * transient.get('band_pct', 2.) / 100.
        output.axhspan(reference-radius, reference+radius, alpha=.09, color='tab:green', label='恢复观察带')
        output.axhline(reference, color='gray', ls=':', lw=.8)
    output.set_ylabel('反馈路 / V')
    if others:
        for rail, values in others.items():
            axes[1].plot(time, values, label=f'OUT{rail}')
        axes[1].set_ylabel('其余端口 / V')
    if load is not None:
        axes[-1].plot(time, np.asarray(load)*100, color='tab:orange', label='反馈路负载设定')
        axes[-1].set_ylabel('负载 / %')
        axes[-1].set_yticks([10, 50, 90])
    for event in transient.get('stimulus', []):
        for index, axis in enumerate(axes):
            axis.axvline(event['time_s']*1e3, color='.36', ls='--', lw=.7,
                         label=f"{event['before']:.0%}→{event['after']:.0%}" if index == 0 else None)
    _finish_axes(axes)


def draw_line_load(fig, data):
    axes = fig.subplots(3, 1, sharex=True)
    time = np.asarray(data['time'])*1e3
    axes[0].plot(time, data['input_V'], color='tab:purple', label='输入端口')
    axes[0].set_ylabel('输入 / V')
    for rail, values in data.get('ports', {}).items():
        axes[1].plot(time, values, label=f'OUT{rail}')
    axes[1].set_ylabel('输出 / V')
    for rail, values in data.get('load_fraction', {}).items():
        axes[2].plot(time, np.asarray(values)*100, lw=.75, label=f'OUT{rail}')
    axes[2].set_ylabel('负载 / %')
    _finish_axes(axes)


def draw_step_edges(fig, transient):
    data = transient['waveform']
    time = np.asarray(data['time'])
    output = np.asarray(data['voltage'])
    events = transient.get('stimulus') or []
    axes = np.atleast_1d(fig.subplots(len(events), 1))
    for index, (axis, event) in enumerate(zip(axes, events)):
        start = event['time_s']
        stop = events[index+1]['time_s'] if index+1 < len(events) else time[-1]
        recovery = next((row.get('recovery_s') for row in transient.get('events', [])
                         if row['time_s'] == start), None)
        show = min(stop-start, max(.003, (recovery or 0.)*1.2, .15*(stop-start)))
        selection = (time >= start-min(show/5, .002)) & (time <= start+show)
        axis.plot((time[selection]-start)*1000, output[selection], color='tab:blue')
        if transient.get('reference_v') is not None:
            reference = transient['reference_v']
            radius = reference*transient.get('band_pct', 2.)/100
            axis.axhspan(reference-radius, reference+radius, alpha=.09, color='tab:green')
        axis.axvline(0, color='.36', ls='--', lw=.7)
        axis.set(title=f"反馈路 {event['before']:.0%}→{event['after']:.0%}", ylabel='输出 / V')
    _finish_axes(axes, '相对阶跃时刻 / ms')


_POWER_KINDS = [('capacitor','逐颗电容电流与端电压'),('mos','MOS 沟道电流与漏源电压'),
                ('diode','二极管导通电流与反向电压')]


def _value(number):
    return '—' if number is None else f'{number:.5g}'


def _related_devices(ref,kind):
    # Keep the same section pairing at Vinmin and Vinmax, even when a probe
    # is missing or the curves only match at one endpoint.
    if kind=='capacitor':
        if re.fullmatch(r'C_IN\d+',ref):
            return '输入电容组'
        output = re.fullmatch(r'C_O(\d+)([A-Z]|_\d+)?',ref)
        if output:
            return f'OUT{output[1] if output[2] else 1} 电容组'
    if kind=='diode' and re.fullmatch(r'D_OUT\d+',ref):
        return '输出防反二极管'
    return ref


def _device_groups(evidence,kinds):
    devices = {device['ref']:device for device in evidence.get('devices',[])}
    for kind,title in kinds:
        rows = [row for row in evidence['rows'] if row['kind']==kind]
        refs = list(dict.fromkeys(row['ref'] for row in rows))
        banks = {}
        for ref in refs:
            banks.setdefault(_related_devices(ref,kind),[]).append(ref)
        groups, group = [], []
        for bank in banks.values():
            if group and len(group)+len(bank)>4:
                groups.append(group)
                group = []
            group.extend(bank)
        if group:
            groups.append(group)
        for group in groups:
            subject = '、'.join(group) if len(group)<=6 else _related_devices(group[0],kind)
            yield (kind, title+' · '+subject, [row for row in rows if row['ref'] in group],
                   [devices[ref] for ref in group if ref in devices])


@dataclass(frozen=True,eq=False)
class _PlotTrace:
    ref: str
    time: np.ndarray
    values: np.ndarray
    label: str
    peak: tuple | None
    scale: float
    normalized: np.ndarray | None


def _matches(left,right):
    if left.label!=right.label or not np.array_equal(left.time,right.time):
        return False
    if np.array_equal(left.values,right.values):
        return True
    if left.normalized is None or right.normalized is None:
        return False
    swing = min(np.ptp(left.normalized),np.ptp(right.normalized),1.)
    # A large DC component must not hide differences in small ripple. Bound
    # mismatch by the smaller normalized swing as well as by full scale.
    return swing>=.05 and np.max(np.abs(left.normalized-right.normalized))<=.01*swing


def _plot_channels(devices,series,*,merge=True):
    """Group only synchronous displayed samples. Never alter evidence or metrics."""
    channels = []
    for key,axis_title in [('current','电流 / A'),('voltage','电压 / V')]:
        groups = []
        for device in devices:
            wave = series(device,key)
            if wave is None:
                continue
            time,values,label,peak = wave
            time,values = np.asarray(time),np.asarray(values,dtype=float)
            if values.shape!=time.shape or not values.size or not np.isfinite(values).all():
                continue
            scale = float(np.max(np.abs(values)))
            shape = values/scale if key=='current' and scale>1e-12 else None
            item = _PlotTrace(device['ref'],time,values,label,peak,scale,shape)
            for group in groups if merge else ():
                if all(_matches(item,other) for other in group):
                    group.append(item)
                    break
            else:
                groups.append([item])
        dimensional, scaled = [], []
        for group in groups:
            different_scale = key=='current' and any(not np.array_equal(group[0].values,item.values)
                                                     for item in group[1:])
            (scaled if different_scale else dimensional).append(group)
        if dimensional:
            channels.append((axis_title,dimensional,False))
        if scaled:
            channels.append(('归一化电流 / p.u.',scaled,True))
    return channels


def _draw_channels(fig,axes_data,xlabel):
    if not axes_data:
        return
    axes = fig.subplots(len(axes_data),1,sharex=True,squeeze=False)[:,0]
    for axis,(axis_title,groups,per_unit) in zip(axes,axes_data):
        for index,group in enumerate(groups):
            trace = group[0]
            refs = '、'.join(item.ref for item in group) if len(group)<=6 else f'{len(group)} 个器件，位号见图注'
            y,peak = trace.values,trace.peak
            if per_unit and trace.normalized is not None:
                y = trace.normalized
                if peak is not None:
                    peak = (peak[0],peak[1]/trace.scale)
            line, = axis.plot(trace.time,y,label=refs+' '+trace.label,color=f'C{index%10}',lw=1.)
            if peak is not None:
                axis.scatter(*peak, color=line.get_color(), s=10, zorder=5)
        axis.set_ylabel(axis_title)
        axis.grid(alpha=.2)
        axis.legend(fontsize=7,ncol=1 if any(len(group)>1 for group in groups) else 2)
    axes[-1].set_xlabel(xlabel)


def _merged_waveform_note(channels):
    notes = []
    for title,groups,per_unit in channels:
        if not any(len(group)>1 for group in groups):
            continue
        for group in groups:
            if len(group)>1:
                refs = '、'.join(item.ref for item in group)
                notes.append(f'{refs} 共用一条{title.split(" / ")[0]}曲线。')
        if per_unit:
            scales = '，'.join(f'{item.ref} {_value(item.scale)} A' for group in groups for item in group)
            notes.append(f'按绘图窗的最大绝对电流归一化。各器件 1 p.u. 分别为 {scales}。')
    return ''.join(notes)


def white_sections(record, *, flyback_ramp=False):
    evidence = record.get('white_box') or {}
    headers = ['指标','单位','设计计算','LTspice 仿真','偏差','测量说明']
    if not evidence.get('rows'):
        yield '稳态器件覆盖', headers, [], evidence.get('reason') or '本次记录缺少稳态器件探针数据。', None
        return
    time = evidence.get('time_s') or []
    x = [(t-time[0])*1e6 for t in time]
    cap_current = record.get('nominal_comparable') is not False

    def series(device,key):
        if flyback_ramp and key=='current' and device['kind']=='mos' and device['ref']=='Q1':
            return None
        if key=='current' and device['kind']=='capacitor' and not cap_current:
            return None
        values = device.get('current_A' if key=='current' else 'voltage_V') or []
        if x and len(values)==len(x):
            return x,values,device.get(key+'_label',key),None

    for kind,title,group,devices in _device_groups(evidence,_POWER_KINDS):
        if kind=='capacitor' and not cap_current:
            group = [row for row in group if row['unit']!='A']
            title = title.replace('逐颗电容电流与端电压','逐颗电容端电压')
        if flyback_ramp and kind=='mos':
            group = [row for row in group if row['ref']!='Q1' or row['unit']!='A']
            title = title.replace('MOS 沟道电流与漏源电压','MOS 漏源电压')
        rows = [(row['metric'],row['unit'],_value(row['design']),_value(row['simulation']),
                 '—' if row['delta_percent'] is None else f"{row['delta_percent']:+.2f}%",row['status']+'。'+row['scope'])
                for row in group]
        channels = _plot_channels(devices,series)
        draw = (lambda fig,channels=channels:_draw_channels(fig,channels,'局部时间 / µs')) if channels else None
        note = ('并联电容逐颗统计，交流有效值扣除直流分量。' if kind=='capacitor' else
                '表中峰值取自完整稳态测量窗，图中展示其中的局部开关周期。')
        if kind=='capacitor' and not cap_current:
            note = '本工况的稳态检查未通过，电容纹波电流待测。'
        note += _merged_waveform_note(channels)
        yield title,headers,rows,note,draw


def draw_excitation_ramps(fig, ramp):
    axis=fig.subplots()
    segments=ramp['segments']
    for index,segment in enumerate(segments):
        t=(np.asarray(segment['time_s'])-segment['turn_on_s'])*1e6
        axis.plot(t,segment['current_A'],lw=1.05,alpha=.8,label=f'脉冲 {index+1}' if len(segments)<=6 else None)
    axis.axvspan(0,ramp['blank_s']*1e6,alpha=.1,color='.55')
    axis.set(xlabel='相对门极开通 / µs',ylabel='原边绕组电流 / A',xlim=(0,None))
    _finish_axes([axis],'相对门极开通 / µs')


STARTUP_HEADERS = ('器件与指标','单位','峰值','时刻 / ms','额定值','降额限值','判定')
STARTUP_WIDTHS = (3.8, 1.05, 1.75, 1.7, 1.55, 1.72, 3.65)


def _startup_table_rows(rows):
    return [(row['ref']+' '+row['metric'],row['unit'],_value(row['simulation']),
             _value(row['time_s']*1e3 if row['time_s'] is not None else None),
             _value(row['rating']),_value(row['limit']),row['status']) for row in rows]


def _startup_scope(rows):
    scopes = {}
    for row in rows:
        if row.get('scope'):
            scopes.setdefault(row['scope'],{})[row['ref']] = None
    return ''.join(' '+'、'.join(refs)+' 的测量口径为 '+scope.rstrip('。')+'。' for scope,refs in scopes.items())


def white_startup_sections(record, *, flyback_ramp=False):
    evidence = record.get('white_box_startup') or {}
    headers = STARTUP_HEADERS
    if not evidence.get('rows'):
        yield '启动器件覆盖', headers, [], evidence.get('reason') or '本次记录缺少启动器件探针数据。', None
        return

    def show_current(device):
        return device['kind']!='capacitor' and (not flyback_ramp or device['ref'] not in
            ('Q1','Q1 栅极','Q1 Coss','Q1 体二极管'))

    def series(device,key):
        if key=='current' and not show_current(device):
            return None
        wave = device.get(key)
        if wave:
            peak = (wave['peak_s']*1e3,wave['peak_value']) if wave['peak_s'] is not None else None
            return [t*1e3 for t in wave['time_s']],wave['values'],wave['label'],peak

    kinds = [('mos','MOS 启动漏源电压' if flyback_ramp else 'MOS 启动电流与漏源电压'),
             ('diode','二极管启动电流与反向电压'),
             ('capacitor','逐颗电容启动端电压'),('winding','绕组启动电流与电压'),
             ('aux','输入、驱动与辅助支路')]
    display = dict(evidence,rows=[row for row in evidence['rows'] if row['channel']!='current' or show_current(row)])
    for kind,title,group,devices in _device_groups(display,kinds):
        rows = _startup_table_rows(group)
        channels = _plot_channels(devices,series)
        draw = (lambda fig,channels=channels:_draw_channels(fig,channels,'启动时间 / ms')) if channels else None
        note = ('电流取正向峰值，反压取 VR 的正向峰值。' if kind=='diode' else
                '表中峰值为绝对值，波形保留正负方向。')
        note += f"测量窗 {evidence['start_s']*1e3:.5g}–{evidence['end_s']*1e3:.5g} ms，曲线保留分段原始极值，圆点标出表内峰值。"
        if evidence.get('reason'):
            note += evidence['reason']+'。'
        note += _startup_scope(group)
        note += _merged_waveform_note(channels)
        yield title,headers,rows,note,draw

    detail = evidence.get('qr_peak_detail')
    if detail:
        def peak_view(device,key):
            wave = device.get(key)
            if wave:
                peak = ((wave['peak_s']-detail['peak_s'])*1e6,wave['peak_value']) if wave['peak_s'] is not None else None
                return [(t-detail['peak_s'])*1e6 for t in wave['time_s']],wave['values'],wave['label'],peak

        def draw_detail(fig):
            gate = next((device for device in detail['devices'] if device['ref']=='Q1 栅极'),{})
            switch = [device for device in detail['devices'] if device is not gate
                      and (not flyback_ramp or device.get('voltage'))]
            def voltage_focus(device,key):
                return peak_view(device,key) if not flyback_ramp or key=='voltage' else None
            channels = _plot_channels(switch,voltage_focus,merge=False)
            _draw_channels(fig,channels,'相对 Q1 漏源峰值时刻 / µs')
            gate_view = peak_view(gate,'voltage')
            if gate_view and fig.axes:
                x,y,_,peak = gate_view
                gate_axis = fig.axes[-1].twinx()
                gate_axis.plot(x,y, color='C3', lw=1., ls='--')
                if peak is not None:
                    gate_axis.scatter(*peak,color='C3',s=10,zorder=5)
                gate_axis.set_ylabel('Vgs / V',color='C3')
                gate_axis.tick_params(axis='y',labelcolor='C3')

        rows = _startup_table_rows(row for row in detail['rows']
                if row['channel']!='current' or (not flyback_ramp and row['ref']!='Q1 栅极'))
        note = '以完整启动窗的 Q1 漏源峰值为时间零点。右轴显示 Vgs。'
        if not flyback_ramp:
            note += '电流图显示沟道和 Coss 支路。'
        yield 'Q1 漏源峰值和换流局部波形',headers,rows,note,draw_detail
