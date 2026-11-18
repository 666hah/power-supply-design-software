"""Generate passive synthetic sweeps and the bundled 24 W Buck example."""

import cmath
import csv
import json
import math
from pathlib import Path


EXAMPLES = Path(__file__).resolve().parents[1] / 'examples'
REFERENCE_HZ = 100_000
SWEEP_MIN_HZ = 100
SWEEP_MAX_HZ = 20_000_000
SWEEP_POINTS = 91
CAPACITORS = {
    # Name, capacitance, inductance, R∞, relaxation R and fc, fixture Rθ.
    'input_capacitors': (
        ('input-c1', 220e-6, 5e-9, 0.020, 0.058, 42e3, 35),
        ('input-c2', 10e-6, 2e-9, 0.004, 0.008, 160e3, 80),
    ),
    'output_capacitors': (
        ('output-c1', 220e-6, 5e-9, 0.017, 0.048, 42e3, 40),
        ('output-c2', 47e-6, 2e-9, 0.010, 0.015, 65e3, 55),
        ('output-c3', 10e-6, 0.8e-9, 0.003, 0.005, 210e3, 95),
    ),
}


def impedance(frequency_hz, capacitance, inductance, r_infinity, relaxation_r, relaxation_hz):
    omega = math.tau * frequency_hz
    return (r_infinity + 1j * omega * inductance + 1 / (1j * omega * capacitance)
            + relaxation_r / (1 + 1j * frequency_hz / relaxation_hz))


def build():
    sweep_dir = EXAMPLES / 'capacitor_impedance_curves'
    sweep_dir.mkdir(exist_ok=True)
    example = json.loads((EXAMPLES / '24W_BUCK_VM_TPS40200.json').read_text(encoding='utf-8'))
    source = '合成示例 · 被动 RLC 与并联 RC 色散项 · 非实测'
    frequencies = {SWEEP_MIN_HZ, SWEEP_MAX_HZ, REFERENCE_HZ, example['f_sw']}
    frequencies.update(SWEEP_MIN_HZ * (SWEEP_MAX_HZ / SWEEP_MIN_HZ) ** (i / (SWEEP_POINTS - 1))
                       for i in range(1, SWEEP_POINTS - 1))
    for bank, definitions in CAPACITORS.items():
        example[bank] = []
        for name, capacitance, inductance, r_infinity, relaxation_r, relaxation_hz, thermal in definitions:
            model = (capacitance, inductance, r_infinity, relaxation_r, relaxation_hz)
            points = []
            for frequency in sorted(frequencies):
                z = impedance(frequency, *model)
                points.append([float(f'{frequency:.10g}'), float(f'{abs(z):.10g}'),
                               float(f'{math.degrees(cmath.phase(z)):.10g}')])
            with (sweep_dir / f'{name}.csv').open('w', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(('frequency_hz', 'magnitude_ohm', 'phase_deg'))
                writer.writerows(points)
            example[bank].append(dict(C=capacitance, ESL=inductance,
                ESR=impedance(REFERENCE_HZ, *model).real, thermal_resistance_K_per_W=thermal,
                impedance_curve=dict(source=f'{source} ({name})', points=points)))
    items = example.get('component_management', {}).get('items', {})
    for name in list(items):
        if name.startswith(('C_IN', 'C_O')):
            items.pop(name)
    example['__example_note'] = '并联电容扫频和热阻为合成教学数据。固定 ESR 取同一模型在 100 kHz 的实部。'
    (EXAMPLES / '24W_BUCK_CAP_IMPEDANCE.json').write_text(
        json.dumps(example, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    build()
