"""Apply reviewed component substitutions to the built-in isolated examples."""

from copy import deepcopy
from functools import lru_cache
import json
import math

from app_resources import resource_path


LOW_VOLTAGE_EXAMPLES = frozenset({
    '33W_3OUT_ACF_MP6005_COMPACT.json',
    '40W_CCM_3OUT_FLYBACK.json',
    '40W_CCM_FLYBACK.json',
})
QR_REFERENCE_EXAMPLE = '90W_QR_L6565_252_442V_REFERENCE.json'
_INPUT_FIELDS = (('Cin1', 'Rcin1', 'ESLin1'), ('Cin2', 'Rcin2', 'ESLin2'))


@lru_cache(maxsize=2)
def _catalog(kind):
    path = resource_path(f'resources/components/example_{kind}_parts.json')
    return json.loads(path.read_text(encoding='utf-8'))['parts']


def _replace_input_bank(config, old_models, new_models):
    bank = config.get('input_capacitors') or ()
    items = config['component_management']['items']
    for i, (old, new) in enumerate(zip(old_models, new_models)):
        ref = f'C_IN{i + 1}'
        item = items.get(ref, {})
        if i >= len(bank) or item.get('model') != old:
            continue
        part = _catalog('passive')[new]
        cap = part['calculation']
        nominal = bank[i].get('C')
        if nominal is None or not math.isclose(nominal, cap['C'], rel_tol=1e-8):
            continue
        bank[i].update(cap)
        config.update(zip(_INPUT_FIELDS[i], (cap['C'], cap['ESR'], cap['ESL'])))
        item.update({key: part[key] for key in ('manufacturer', 'model', 'package', 'conditions',
                                                'voltage_V', 'ripple_A', 'capacitor_type')})
        item['note'] = part['note'] + ' ' + part['sources'][0]['url']
        config.get('__real_parts', {}).get('selections', {}).get(ref, {}).update(key=new)


def personal_qr_with_margin(config):
    """Return an updated QR example in memory when its previous parts are present."""
    items = (config.get('component_management') or {}).get('items', {})
    if config.get('topology') != 'QR-FLYBACK' or not items:
        return config
    updated = deepcopy(config)
    q1 = updated['component_management']['items'].get('Q1', {})
    if q1.get('model') == 'STP80N340K6':
        part = _catalog('semiconductor')['STP15N95K5']
        params = part['calculator_parameters']
        updated.update(params, mos_manual_events={})
        q1.update({key: part[key] for key in ('manufacturer', 'model', 'package', 'voltage_V')})
        source = part['parameters']
        q1['conditions'] = (f"{part['source_document']}。Rds(on) 最大值条件为 {source['Rds_condition']}。"
                            f"栅电荷典型值条件为 {source['gate_charge_condition']}。")
        q1['note'] = part['note'] + ' ' + part['source_url']
        updated.setdefault('spice_config', {})['qr_cds_pf'] = params['Coss'] * 1e12
        if isinstance(updated.get('parasitic_config'), dict):
            updated['parasitic_config']['coss'] = params['Coss']
        updated.get('__real_parts', {}).get('selections', {}).get('Q1', {}).update(key=part['model'])
    _replace_input_bank(updated, ('B32774D4106K000',) * 2, ('B32774P6106K000',) * 2)
    return updated


def isolated_low_voltage_with_margin(config):
    """Replace the curated 330 µF/100 µF input pair with its 63 V equivalents."""
    updated = deepcopy(config)
    _replace_input_bank(updated, ('EEUFR1H331L', 'EEUFR1H101'),
                        ('EEUFR1J331', 'EEH-AZS1J101B'))
    return updated
