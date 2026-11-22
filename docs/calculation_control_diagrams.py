"""Original control diagrams for the calculation reference."""
from functools import lru_cache
from io import BytesIO
from os import environ
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SCALE = 2
WIDTH = 1200
BOX_WIDTH = 194
BOX_HEIGHT = 78
COLUMNS = (42, 272, 502, 732, 962)
INK = '#162F4D'
SIGNAL = '#32659A'
WHITE = '#FFFFFF'
BLOCKS = {
    'control': ('#EAF2FC', '#ABC6E4'),
    'sense': ('#F2F6FA', '#C3D3E4'),
    'timing': ('#E8F5F7', '#A8CFD7'),
    'plant': ('#DDECF9', '#7BA4D0'),
}


@lru_cache(maxsize=48)
def _font(size, bold=False):
    windows_fonts = Path(environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    font_paths = (
        windows_fonts / ('msyhbd.ttc' if bold else 'msyh.ttc'),
        Path('/usr/share/fonts/opentype/noto')
        / ('NotoSansCJK-Bold.ttc' if bold else 'NotoSansCJK-Regular.ttc'),
        Path('/System/Library/Fonts/PingFang.ttc'),
    )
    for path in font_paths:
        if path.is_file():
            return ImageFont.truetype(str(path), size * SCALE)
    raise FileNotFoundError('绘制控制框图需要支持中文的微软雅黑、Noto Sans CJK 或苹方字体')


def _scaled(points):
    return [(round(x * SCALE), round(y * SCALE)) for x, y in points]


class _Diagram:
    def __init__(self, height):
        self.image = Image.new('RGB', (WIDTH * SCALE, height * SCALE), WHITE)
        self.draw = ImageDraw.Draw(self.image)

    def label(self, x, y, value, size=21, *, bold=False, color=INK, width=None):
        font = _font(size, bold)
        if width:
            while self.draw.textlength(value, font=font) > width * SCALE and size > 16:
                size -= 1
                font = _font(size, bold)
            if self.draw.textlength(value, font=font) > width * SCALE:
                raise ValueError(f'控制框图文字超出框宽：{value}')
        left, top, right, bottom = self.draw.textbbox((0, 0), value, font=font)
        origin = (round(x * SCALE - (left + right) / 2),
                  round(y * SCALE - (top + bottom) / 2))
        self.draw.text(origin, value, fill=color, font=font)

    def box(self, column, y, title, detail, kind='control'):
        x = COLUMNS[column]
        fill, border = BLOCKS[kind]
        self.draw.rectangle(_scaled(((x, y), (x + BOX_WIDTH, y + BOX_HEIGHT))),
                            fill=fill, outline=border, width=2 * SCALE)
        self.label(x + BOX_WIDTH / 2, y + 25, title, 25, bold=True,
                   width=BOX_WIDTH - 14)
        self.label(x + BOX_WIDTH / 2, y + 54, detail, 20, width=BOX_WIDTH - 12)

    def route(self, *points, arrow=True):
        self.draw.line(_scaled(points), fill=SIGNAL, width=3 * SCALE, joint='curve')
        if arrow:
            a, b = points[-2:]
            length = abs(b[0] - a[0]) + abs(b[1] - a[1])
            dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            x, y = b[0] - 12 * dx, b[1] - 12 * dy
            self.draw.polygon(_scaled((b, (x - 5.5 * dy, y + 5.5 * dx),
                                       (x + 5.5 * dy, y - 5.5 * dx))), fill=SIGNAL)

    def junction(self, x, y):
        self.draw.ellipse(_scaled(((x - 4, y - 4), (x + 4, y + 4))), fill=SIGNAL)

    def main_chain(self, y, nodes):
        for i, (title, detail, kind) in enumerate(nodes):
            self.box(i, y, title, detail, kind)
        for left, right in zip(COLUMNS, COLUMNS[1:]):
            self.route((left + BOX_WIDTH, y + BOX_HEIGHT // 2),
                       (right, y + BOX_HEIGHT // 2))

    def voltage_feedback(self, y, lower_y, title, detail, *, output='反馈端电压',
                         pickup_x=1059):
        self.box(1, lower_y, title, detail, 'sense')
        lower = lower_y + BOX_HEIGHT // 2
        main_bottom = y + BOX_HEIGHT
        self.route((pickup_x, main_bottom), (pickup_x, lower), (466, lower))
        self.route((272, lower), (139, lower), (139, main_bottom))
        self.label(760, lower - 22, output, color=SIGNAL)

    def png(self):
        result = BytesIO()
        self.image.save(result, 'PNG', dpi=(412, 412), optimize=True)
        result.seek(0)
        return result


def _voltage_pwm():
    diagram = _Diagram(410)
    diagram.main_chain(164, (
        ('误差比较', 'Vref − Vfb', 'control'),
        ('电压环补偿', 'Gc(s) → VCOMP', 'control'),
        ('电压型 PWM 比较', 'VCOMP 与斜坡比较', 'control'),
        ('门极驱动', '占空比 D', 'control'),
        ('开关功率级', '功率开关与输出滤波', 'plant'),
    ))
    diagram.box(2, 33, '振荡器与斜坡', '周期 Tsw / 幅值 Vm', 'timing')
    diagram.route((599, 111), (599, 164))
    diagram.voltage_feedback(164, 305, '输出取样', '反馈比例 β')
    return diagram


def _peak_current_pwm():
    diagram = _Diagram(416)
    diagram.main_chain(164, (
        ('误差比较', 'Vref − Vfb', 'control'),
        ('电压环补偿', 'Gc(s) → VCOMP', 'control'),
        ('峰值电流比较', '达到命令阈值时复位', 'control'),
        ('PWM 锁存与驱动', '每周期置位 / 关断复位', 'control'),
        ('开关功率级', '电感或原边电流', 'plant'),
    ))
    diagram.box(2, 44, '电流采样和斜坡', 'Rs / Asense / 斜坡 ma', 'sense')
    diagram.box(3, 44, '固定频率时钟', '周期置位 / 导通窗口', 'timing')
    diagram.route((599, 122), (599, 164))
    diagram.route((829, 122), (829, 164))
    diagram.route((1156, 203), (1180, 203), (1180, 17), (599, 17), (599, 44))
    diagram.label(1038, 39, '开关电流', color=SIGNAL)
    diagram.voltage_feedback(164, 309, '输出取样', '反馈比例 β')
    return diagram


def _mp6005_psr():
    diagram = _Diagram(498)
    diagram.main_chain(161, (
        ('FB 误差比较', '2 V − VFB', 'control'),
        ('误差放大与补偿', 'gEA / COMP 阻容网络', 'control'),
        ('工作区选择', '按负载工作点判定', 'control'),
        ('重载 PWM', '定频 / 峰值电流关断', 'control'),
        ('反激功率级', '原边开关与辅助绕组', 'plant'),
    ))
    diagram.box(3, 34, '原边电流采样', '采样电阻 Rs', 'sense')
    diagram.route((1059, 161), (1059, 73), (926, 73))
    diagram.route((829, 112), (829, 161))
    diagram.box(3, 266, '轻载 PFM', '频率与峰值工作点估算', 'timing')
    diagram.route((599, 239), (599, 305), (732, 305))
    diagram.route((926, 305), (1125, 305), (1125, 239))
    diagram.label(896, 363, 'PWM 提供小信号环路，PFM 提供稳态结果', 21, color=SIGNAL)
    diagram.voltage_feedback(161, 392, '退磁期间采样', 'FB 分压与线压降补偿',
                             output='辅助绕组反射电压', pickup_x=1144)
    return diagram


def _qr_l6565():
    diagram = _Diagram(424)
    diagram.main_chain(174, (
        ('误差比较', 'Vref − Vfb', 'control'),
        ('电压环补偿', 'COMP → 峰值电流命令', 'control'),
        ('CS 比较与关断', '电流阈值 / VFF 限流', 'control'),
        ('SR 锁存与驱动', 'S 置位 / R 复位', 'control'),
        ('准谐振反激', '退磁 / 漏极振铃', 'plant'),
    ))
    diagram.box(2, 45, '原边 CS 调理', '电流取样 / 前沿消隐', 'sense')
    diagram.box(3, 45, 'ZCD 谷底触发', '检测边沿 / 消隐与延时', 'timing')
    diagram.route((599, 123), (599, 174))
    diagram.route((829, 123), (829, 174))
    diagram.label(848, 147, 'S', 20, color=SIGNAL)
    diagram.route((1156, 213), (1180, 213), (1180, 18), (599, 18), (599, 45))
    diagram.route((1059, 174), (1059, 84), (926, 84))
    diagram.label(1048, 41, '原边电流', color=SIGNAL)
    diagram.label(1050, 68, '绕组电压', color=SIGNAL)
    diagram.voltage_feedback(174, 315, '副边取样与隔离', '主反馈路 Vcap', output='防反前电容端电压')
    return diagram


def _acf_timing():
    diagram = _Diagram(518)
    diagram.main_chain(164, (
        ('SSR 反馈比较', 'Vref − Vfb', 'control'),
        ('电压环补偿', 'Gc(s) → VCOMP', 'control'),
        ('峰值电流比较', 'CS 与有效命令比较', 'control'),
        ('主开关锁存', 'GATE → 主 N-MOS', 'control'),
        ('有源钳位正激', '主辅开关、钳位与输出', 'plant'),
    ))
    diagram.box(2, 44, '原边 CS 调理', 'Rs / 斜坡与消隐', 'sense')
    diagram.box(3, 44, '固定频率时钟', '周期置位 / 导通窗口', 'timing')
    diagram.route((599, 122), (599, 164))
    diagram.route((829, 122), (829, 164))
    diagram.route((1156, 203), (1180, 203), (1180, 17), (599, 17), (599, 44))
    diagram.label(1040, 39, '原边电流', color=SIGNAL)
    diagram.box(3, 286, '互补时序与死区', 'SYNC → 电平移位', 'timing')
    diagram.route((829, 242), (829, 286))
    diagram.route((926, 325), (1125, 325), (1125, 242))
    diagram.label(1044, 348, '辅助 P-MOS', color=SIGNAL)
    diagram.voltage_feedback(164, 411, '副边取样与隔离', '主反馈路 Vcap',
                             output='防反前电容端电压', pickup_x=1144)
    return diagram


def _cot_frequency_pi():
    diagram = _Diagram(410)
    diagram.main_chain(164, (
        ('归一化电压误差', '(Vset − Vcap)/Vset', 'control'),
        ('频率 PI', 'Kp + Ki/s', 'control'),
        ('COT 脉冲调制', '触发频率 f', 'control'),
        ('交错与门极驱动', '各相相隔 T/N', 'control'),
        ('同步 Buck 功率级', '各相电感向同一路供电', 'plant'),
    ))
    diagram.box(2, 33, '导通定时 Ton', '输入前馈 / 固定导通', 'timing')
    diagram.route((599, 111), (599, 164))
    diagram.voltage_feedback(164, 305, '输出电容端取样', '公共电压反馈', output='Vcap')
    return diagram


def _cot_current_feedback():
    diagram = _Diagram(427)
    diagram.main_chain(180, (
        ('归一化电压误差', '(Vset − Vcap)/Vset', 'control'),
        ('频率 PI', 'Kp + Ki/s', 'control'),
        ('频率指令修正', '扣除总电流反馈', 'control'),
        ('逐相 COT 交错', 'Ton,j / 均流修正 ΔDj', 'control'),
        ('同步 Buck 功率级', 'N 相共用输出电容', 'plant'),
    ))
    diagram.box(2, 45, '总电流反馈', '求和 / 一阶低通 / 增益', 'sense')
    diagram.box(3, 45, '相间均流', '平均值减本相 / 限幅滤波', 'sense')
    diagram.box(4, 45, '逐相电流采样', 'Im,j = aj Ij + bj', 'sense')
    diagram.route((1059, 180), (1059, 123))
    diagram.route((1059, 45), (1059, 19), (599, 19), (599, 45))
    diagram.route((829, 19), (829, 45))
    diagram.junction(829, 19)
    diagram.route((599, 123), (599, 180))
    diagram.route((829, 123), (829, 180))
    diagram.label(624, 151, '−', 23, color=SIGNAL)
    diagram.label(855, 151, 'ΔDj', color=SIGNAL)
    diagram.voltage_feedback(180, 322, '输出电容端取样', '公共电压反馈', output='Vcap')
    return diagram


def render_control_figure(key):
    """Return a high-resolution PNG stream positioned at its start."""
    figures = {
        'voltage_pwm': _voltage_pwm,
        'peak_current_pwm': _peak_current_pwm,
        'mp6005_psr': _mp6005_psr,
        'qr_l6565': _qr_l6565,
        'acf_timing': _acf_timing,
        'cot_frequency_pi': _cot_frequency_pi,
        'cot_current_feedback': _cot_current_feedback,
    }
    return figures[key]().png()
