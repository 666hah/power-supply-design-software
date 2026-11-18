"""Original functional diagrams of the implemented controller behaviours."""


def _item(id, key, kind, x, y, w, h, label, **style):
    return dict(id=id, key=key, kind=kind, x=x, y=y, w=w, h=h, label=label, **style)


def _pin(id, key, x, y, label, *, side='left', **style):
    return _item(id, key, 'pin', x, y, 0, 0, label, side=side, **style)


def _wire(*points, label=None, label_at=None, arrow=True, tone=None):
    line = dict(points=[list(point) for point in points], arrow=arrow)
    if label:
        line.update(label=label, label_at=list(label_at))
    if tone:
        line['tone'] = tone
    return line


def _diagram(title, items, routes, *, junctions=(), source=None):
    diagram = dict(width=850, height=414, title=title, boundary=[116, 29, 618, 346],
                   items=items, routes=routes, junctions=[list(point) for point in junctions])
    if source:
        diagram['source'] = source
    return diagram


def _ports(*ports):
    return [dict(name=name, x=x, y=y) for name, x, y in ports]


def qr_schematic():
    """L6565 pin names and numbers, with the software's SSR control path."""
    zcd_fields = ['qr_aux_ratio', 'qr_zcd_winding', 'qr_zcd_r', 'qr_zcd_c_pf',
                  'qr_zcd_delay_ns', 'qr_zcd_arm_v', 'qr_zcd_trigger_v']
    return _diagram(
        'L6565 参考 · 准谐振行为模型',
        [
            _pin('zcd_pin', 'sense', 116, 101, 'ZCD ⑤', focus_fields=zcd_fields),
            _pin('comp_pin', 'feedback', 116, 222, 'COMP ②'),
            _pin('cs_pin', 'sense', 116, 270, 'CS ④', focus_fields=['cs_filter_ns', 'blanking_ns']),
            _pin('vff_pin', 'pwm', 116, 320, 'VFF ③'),
            _pin('vcc_pin', 'start', 734, 75, '⑧ VCC', side='right'),
            _pin('gd_pin', 'drive', 734, 158, '⑦ GD', side='right'),
            _pin('gnd_pin', 'start', 734, 353, '⑥ GND', side='right'),
            _item('zcd_cmp', 'sense', 'comparator', 150, 66, 93, 70, 'ZCD',
                  detail='迟滞边沿', parameter='qr_zcd_winding', focus_fields=zcd_fields),
            _item('off_window', 'clock', 'block', 275, 78, 128, 46, '关断消隐',
                  detail='随 COMP 变化', parameter='qr_off_min_us'),
            _item('restart', 'clock', 'block', 275, 143, 128, 38, '启动定时器', parameter='qr_starter_us'),
            _item('set', 'clock', 'sum', 453, 93, 34, 34, '≥1'),
            _item('permit', 'start', 'block', 500, 109, 36, 36, '使能'),
            _item('uvlo', 'start', 'block', 588, 55, 103, 40, 'UVLO', parameter='qr_uvlo_on_v'),
            _item('latch', 'drive', 'latch', 552, 125, 76, 114, '锁存',
                  pins=_ports(('S', 565, 144), ('R', 565, 218), ('Q', 615, 158))),
            _item('gate', 'drive', 'driver', 658, 130, 56, 56, '驱动', parameter='driver_resistance'),
            _item('comp', 'feedback', 'block', 151, 202, 106, 40, '电流命令',
                  detail='COMP 量纲', parameter='kp'),
            _item('cs_filter', 'sense', 'block', 151, 247, 106, 46, 'CS 滤波',
                  detail='RC', parameter='cs_filter_ns', focus_fields=['cs_filter_ns']),
            _item('vff', 'pwm', 'block', 151, 302, 106, 36, '线电压前馈', parameter='qr_vff_v'),
            _item('clamp', 'pwm', 'block', 294, 202, 99, 40, 'COMP 限幅', parameter='qr_cs_clamp_v'),
            _item('gain', 'sense', 'block', 294, 250, 99, 40, '增益 / LEB',
                  parameter='blanking_ns', focus_fields=['blanking_ns']),
            _item('pwm', 'pwm', 'comparator', 433, 201, 71, 81, 'PWM',
                  pins=_ports(('+', 440, 268), ('−', 440, 219))),
            _item('reset', 'drive', 'sum', 512, 201, 34, 34, '≥1'),
            _item('ocp', 'protect', 'comparator', 315, 300, 82, 56, 'OCP', parameter='qr_ocp_v'),
            _item('fault', 'protect', 'latch', 445, 304, 100, 48, '故障锁存',
                  detail='VCC 欠压复位', parameter='qr_ocp_v'),
            _item('watchdog', 'drive', 'block', 576, 264, 140, 42, '最长导通',
                  detail='模型定时器', parameter='qr_max_on_us'),
            _item('ground', 'start', 'note', 611, 342, 93, 22, '信号参考'),
            _item('zcd_source', 'sense', 'note', 17, 118, 87, 20, '绕组电压副本',
                  focus_fields=zcd_fields, parameter='qr_zcd_winding'),
            _item('ssr_source', 'feedback', 'note', 16, 232, 88, 20, '外部 SSR 补偿', parameter='kp'),
            _item('test', 'test', 'note', 610, 389, 165, 18, '仿真工况与测量'),
            _item('external', 'power', 'note', 46, 389, 200, 18, '外部谐振功率级'),
        ],
        [
            _wire((116, 101), (150, 101)),
            _wire((243, 101), (275, 101)),
            _wire((403, 101), (435, 101), (435, 110), (453, 110)),
            _wire((403, 162), (438, 162), (438, 122), (458, 122)),
            _wire((487, 110), (491, 110), (491, 127), (500, 127)),
            _wire((536, 127), (543, 127), (543, 144), (552, 144)),
            _wire((734, 75), (691, 75)),
            _wire((588, 75), (518, 75), (518, 109), label='RUN', label_at=(556, 64)),
            _wire((628, 158), (658, 158), arrow=False),
            _wire((714, 158), (734, 158)),
            _wire((734, 353), (706, 353), arrow=False),
            _wire((116, 222), (151, 222), tone='external'),
            _wire((257, 222), (294, 222)),
            _wire((393, 222), (433, 222)),
            _wire((116, 270), (151, 270)),
            _wire((257, 270), (294, 270)),
            _wire((393, 270), (433, 270)),
            _wire((116, 320), (151, 320)),
            _wire((257, 320), (285, 320), (285, 229), (294, 229)),
            _wire((504, 241.5), (508, 241.5), (508, 218), (512, 218)),
            _wire((546, 218), (552, 218)),
            _wire((272, 270), (272, 328), (315, 328), tone='protection'),
            _wire((397, 328), (445, 328), tone='protection'),
            _wire((545, 328), (553, 328), (553, 246), (535, 246), (535, 234),
                  label='FAULT', label_at=(514, 279), tone='protection'),
            _wire((646, 158), (646, 264)),
            _wire((576, 286), (569, 286), (569, 252), (522, 252), (522, 233)),
        ],
        junctions=[(272, 270), (646, 158)],
    )


def pwm_schematic(profile=None, *, voltage=False):
    """Fixed-frequency core, with optional mode/path labels or the ACF output."""
    forward = profile == 'acf'
    voltage = voltage or profile == 1
    nonisolated = isinstance(profile, int)
    title = {
        None: '反激 · 通用固定频率 PWM 模型',
        'acf': 'MP6005 参考 · 有源钳位正激模型',
        1: 'TPS40200 参考 · Buck 电压模式',
        2: 'LTC3864 参考 · Buck 峰值电流',
        3: 'LM5022 参考 · Boost 峰值电流',
    }[profile]
    source = {
        1: 'https://www.ti.com/lit/ds/symlink/tps40200.pdf',
        2: 'https://www.analog.com/media/en/technical-documentation/data-sheets/ltc3864.pdf',
        3: 'https://www.ti.com/lit/ds/symlink/lm5022.pdf',
    }.get(profile)
    input_labels = {2: 'SENSE', 3: 'CS'}
    comp_label = {1: 'COMP', 2: 'ITH', 3: 'COMP'}
    output = {1: 'GDRV', 2: 'GATE', 3: 'OUT'}
    input_name = input_labels.get(profile, 'CS')
    protection_label = '可选 SCP / OLP' if nonisolated else 'SCP / OLP'
    items = [
        _pin('vcc', 'start', 116, 79, 'VCC / EN'),
        _pin('fb', 'feedback', 116, 190, 'FB' if nonisolated else 'COMP'),
        _pin('cs', 'sense', 116, 242, input_name),
        _pin('gnd', 'start', 734, 295, 'GND', side='right'),
        _pin('gate', 'drive', 734, 175, output.get(profile, 'GATE'), side='right'),
        _item('uvlo', 'start', 'block', 153, 59, 130, 40, 'EN / UVLO', parameter='uvlo'),
        _item('ss', 'start', 'block', 153, 112, 130, 38, '软启动 SS', parameter='soft_start_ms'),
        _item('clock', 'clock', 'block', 352, 61, 128, 44, '振荡器',
              detail='时钟 / Dmax', parameter='frequency_hz'),
        _item('permit', 'start', 'block', 518, 138, 32, 38, '开'),
        _item('latch', 'drive', 'latch', 555, 139, 74, 111, '锁存',
              pins=_ports(('S', 568, 158), ('R', 568, 231), ('Q', 616, 175))),
        _item('driver', 'drive', 'driver', 654, 149, 57, 52, '驱动', parameter='driver_resistance'),
        _item('feedback', 'feedback', 'block', 153, 170, 130, 41,
              '误差与补偿' if nonisolated else '调制命令',
              detail=comp_label.get(profile, 'COMP'), parameter='kp'),
        _item('sense', 'sense', 'block', 153, 222, 130, 40, '采样滤波',
              detail='RC / LEB', parameter='cs_filter_ns'),
        _item('ramp', 'clock' if profile == 1 else 'pwm', 'block', 332, 222, 130, 40,
              ('VIN 前馈斜坡' if profile == 1 else '电压模式斜坡') if voltage else '电流斜坡混合',
              detail='锯齿调制' if voltage else 'CS × 增益 + 斜坡',
              **({'parameter': 'niso_ramp_ratio'} if profile == 1 else
                 {} if voltage else {'parameter': 'niso_lm_cs_resistor' if profile == 3 else 'slope_mode'})),
        _item('pwm', 'pwm', 'comparator', 479, 180, 72, 79, 'PWM',
              pins=_ports(('+', 487, 242), ('−', 487, 197))),
        _item('reset', 'drive', 'sum', 506, 274, 36, 36, '≥1'),
        _item('current_limit', 'pwm', 'block', 332, 271, 130, 40, '逐周期限流', parameter='cs_limit'),
        _item('protection', 'protect', 'block', 332, 326, 130, 40, protection_label,
              detail='故障 / 打嗝 / 锁存', parameter='short_mode'),
        _item('analog_ground', 'start', 'note', 643, 284, 61, 21, '参考'),
        _item('power', 'power', 'note', 55, 389, 197, 18, '外部功率级与寄生'),
        _item('test', 'test', 'note', 609, 389, 165, 18, '仿真工况与测量'),
    ]
    routes = [
        _wire((116, 79), (153, 79)),
        _wire((218, 99), (218, 112)),
        _wire((218, 150), (218, 170), label='SS', label_at=(233, 161)),
        _wire((480, 83), (533, 83), (533, 138), label='周期开始', label_at=(506, 72)),
        _wire((460, 105), (460, 152), (476, 152), (476, 279), (510, 279),
              label='Dmax', label_at=(451, 137)),
        _wire((550, 157), (555, 157)),
        _wire((283, 79), (307, 79), (307, 119), (511, 119), (511, 149), (518, 149),
              label='RUN', label_at=(324, 106)),
        _wire((116, 190), (153, 190), tone='external'),
        _wire((283, 190), (479, 190)),
        _wire((116, 242), (153, 242)),
        _wire((462, 242), (479, 242)),
        _wire((551, 219.5), (551, 295), (542, 295)),
        _wire((537, 280), (549, 280), (549, 231), (555, 231)),
        _wire((283, 242), (309, 242), (309, 345), (332, 345), tone='protection'),
        _wire((309, 291), (332, 291)),
        _wire((462, 291), (506, 291)),
        _wire((462, 345), (524, 345), (524, 310), tone='protection'),
        _wire((629, 175), (654, 175), arrow=False),
        _wire((711, 175), (734, 175)),
        _wire((734, 295), (707, 295), arrow=False),
    ]
    junctions = [(309, 242), (309, 291)]
    if profile == 1:
        items.append(_pin('vin', 'clock', 116, 280, 'VIN'))
        routes.append(_wire((116, 280), (295, 280), (295, 251), (332, 251)))
    elif voltage:
        routes.append(_wire((403, 105), (403, 222), label='锯齿', label_at=(427, 151)))
    else:
        routes.append(_wire((309, 242), (332, 242)))
    if forward:
        items += [
            _item('deadtime', 'drive', 'block', 590, 312, 117, 46, '双边沿死区',
                  detail='AC 移位在功率级', parameter='acf_dead_ns'),
            _pin('sync', 'drive', 734, 335, 'SYNC', side='right'),
        ]
        routes += [
            _wire((721, 175), (721, 270), (648, 270), (648, 312)),
            _wire((707, 335), (734, 335)),
        ]
        junctions.append((721, 175))
    return _diagram(title, items, routes, junctions=junctions, source=source)


def cot_schematic():
    """Pulse-rate PI, phase offsets and fixed on-time from the COT export."""
    return _diagram(
        'Buck COT · 同步交错行为模型',
        [
            _pin('enable', 'start', 116, 83, '启动'),
            _pin('vout', 'feedback', 116, 173, 'VOUT'),
            _pin('vin', 'clock', 116, 264, 'VIN'),
            _pin('out', 'drive', 734, 216, 'GH / GL', side='right'),
            _item('ss', 'start', 'block', 156, 60, 126, 46, '参考缓升',
                  detail='Tstart / Tss', parameter='soft_start_ms'),
            _item('error', 'feedback', 'sum', 311, 140, 40, 40, 'Σ'),
            _item('pi', 'feedback', 'block', 387, 136, 140, 48, 'PI 调节', detail='误差 → 脉冲频率'),
            _item('clamp', 'clock', 'block', 387, 199, 140, 48, '频率限制', detail='最短关断时间'),
            _item('ton', 'clock', 'block', 156, 241, 126, 46, 'Ton 前馈', detail='手动 / 自动'),
            _item('interleave', 'pwm', 'block', 566, 192, 97, 48, '各相分配', detail='交错相位'),
            _item('gate', 'drive', 'driver', 677, 190, 47, 52, '驱动'),
            _item('power', 'power', 'note', 55, 389, 197, 18, '外部功率级与寄生'),
            _item('test', 'test', 'note', 609, 389, 165, 18, '仿真工况与测量'),
        ],
        [
            _wire((116, 83), (156, 83)),
            _wire((282, 83), (331, 83), (331, 140), label='参考 +', label_at=(361, 99)),
            _wire((116, 173), (316, 173), label='反馈 −', label_at=(206, 157), tone='external'),
            _wire((351, 160), (387, 160)),
            _wire((457, 184), (457, 199)),
            _wire((527, 223), (566, 223)),
            _wire((116, 264), (156, 264)),
            _wire((282, 264), (614, 264), (614, 240), label='Ton', label_at=(551, 276)),
            _wire((663, 216), (677, 216), arrow=False),
            _wire((724, 216), (734, 216)),
        ],
    )
