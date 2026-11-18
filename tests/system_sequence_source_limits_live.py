"""Real LTspice I-V sweep of source limit bounds and reverse-current policy.

The stiff output sweep is a controlled test fixture, not a power-tree example.
No production equations or simulator tolerances are changed by this test.
"""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from system_sequence_behavior import protected_source
from spice_runtime import TransientRaw, _run, find_ltspice, read_log


def main():
    folder = ROOT/'artifacts/sequence-v2-core/iv-sweep'
    folder.mkdir(parents=True, exist_ok=True)
    lines = ['Declared source CV/CC curve verification',
             '.options method=gear reltol=.001 plotwinsize=0 numdgt=15',
             'VOUT out 0 PWL(0 0 .0001 0 .0011 10)']
    for name, mode, sink, voltage in (
            ('CC', 'cc', False, 5.), ('SINK', 'cc', True, 5.),
            ('FOLD', 'foldback', False, 5.), ('OFF', 'cc', False, 0.)):
        lines.append(f'V{name} {name}_raw 0 PWL(0 0 .0001 {voltage})')
        protected_source(lines, name, name+'_raw', 'out', dict(
            protection_mode=mode, resistance_ohm=1., current_limit_A=1.,
            foldback_short_A=.2, sink_current=sink), None)
    lines.extend(['.save V(out) V(CC_raw) I(VCC) I(VSINK) I(VFOLD) I(VOFF)',
                  '.tran 0 .0011 0 2u uic', '.end'])
    (folder/'Flyback.cir').write_text('\n'.join(lines)+'\n', encoding='utf8')
    wall = _run(find_ltspice(), folder, 60, lambda: False)
    _, _, errors, warnings = read_log(folder/'Flyback.log')
    assert not errors and not warnings, (errors, warnings)
    raw = TransientRaw(folder/'Flyback.raw')
    output = np.asarray(raw.trace('v(out)'), dtype=float)
    source = np.asarray(raw.trace('v(cc_raw)'), dtype=float)
    demand = source-output
    receipt = dict(scope='real-LTspice controlled I-V fixture; not hardware validation',
        wall_s=wall, end_s=float(raw.time[-1]), points=len(raw.time), errors=errors,
        warnings=warnings, cases={}, behavior_sha256=hashlib.sha256(
            (ROOT/'system_sequence_behavior.py').read_bytes()).hexdigest())
    for name, sink in [('CC', False), ('SINK', True), ('FOLD', False)]:
        actual = -np.asarray(raw.trace('i(v'+name.lower()+')'), dtype=float)
        ceiling = .2+.8*np.clip(output/np.maximum(source,.001), 0, 1) if name == 'FOLD' else np.ones_like(output)
        ideal = np.clip(demand, -ceiling if sink else 0., ceiling)
        relative_error = np.abs(actual-ideal)/ceiling
        assert np.max(np.abs(actual)/ceiling) <= 1.000001, name
        assert np.max(relative_error) <= .001001, (name, np.max(relative_error))
        if not sink:
            assert np.min(actual) >= -1e-9, name
            assert np.max(np.abs(actual[output >= source])) < 1e-8, name
        else:
            assert np.min(actual) < -.99
            assert np.max(np.diff(actual[raw.time >= .0001])) < 1e-6  # monotone I-V, no negative-R artifact
        # Passive pass element: voltage drop times current cannot generate energy.
        assert np.min(demand*actual) >= -1e-8, name
        receipt['cases'][name] = dict(min_A=float(np.min(actual)),
            max_A=float(np.max(actual)), max_relative_clamp_error=float(np.max(relative_error)))
    off = -np.asarray(raw.trace('i(voff)'), dtype=float)
    assert np.max(np.abs(off)) < 1e-8
    receipt['cases']['OFF'] = dict(max_absolute_A=float(np.max(np.abs(off))))
    raw.close()
    (folder/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
