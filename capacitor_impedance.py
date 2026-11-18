"""Passive capacitor impedance sweeps and AC parallel-bank response."""

import math
from numbers import Real

import numpy as np


MAX_CURVE_POINTS = 10_000
CURVE_FIELD = 'impedance_curve'
MODE_FIELD = 'impedance_mode'
THERMAL_FIELD = 'thermal_resistance_K_per_W'


def validate_curve(curve):
    """Return an owned, frequency-sorted SI curve for project storage."""
    if not isinstance(curve, dict) or set(curve) - {'points', 'source'}:
        raise ValueError('阻抗曲线需要 points，可附 source')
    points = curve.get('points')
    if not isinstance(points, (list, tuple)) or not 2 <= len(points) <= MAX_CURVE_POINTS:
        raise ValueError(f'阻抗曲线需要 2–{MAX_CURVE_POINTS} 个频点')
    result = []
    for index, point in enumerate(points, 1):
        if (not isinstance(point, (list, tuple)) or len(point) != 3
                or any(isinstance(x, bool) or not isinstance(x, Real)
                       or not math.isfinite(x) for x in point)):
            raise ValueError(f'曲线第 {index} 点需要有限的频率 Hz、阻抗 Ω、相位 °')
        frequency, magnitude, phase = map(float, point)
        if frequency <= 0 or magnitude <= 0 or not -90 <= phase <= 90:
            raise ValueError(f'曲线第 {index} 点的频率和阻抗需为正，相位需在 −90° 至 +90° 内')
        result.append([frequency, magnitude, phase])
    result.sort(key=lambda row: row[0])
    if any(left[0] == right[0] for left, right in zip(result, result[1:])):
        raise ValueError('阻抗曲线有重复频率')
    normalized = {'points': result}
    if 'source' in curve:
        source = curve['source']
        if not isinstance(source, str) or len(source) > 256:
            raise ValueError('阻抗曲线来源需为不超过 256 字符的文字')
        if source.strip():
            normalized['source'] = source.strip()
    return normalized


def active_curve(cap):
    """Resolve the enabled sweep, including older rows that store only a sweep."""
    return cap.get(CURVE_FIELD) if cap.get(MODE_FIELD, 'curve') == 'curve' else None


def impedance(frequencies, cap, *, return_coverage=False):
    """Evaluate a normalized capacitor at positive AC frequencies in Hz.

    Interpolate Re(Z) and Im(Z) on log frequency within the measured band.
    Outside the band or in fixed mode, use the nominal C/ESR/ESL series model.
    """
    frequency = np.asarray(frequencies, dtype=float)
    omega = 2 * np.pi * frequency
    nominal = np.asarray(cap['ESR'] + 1j * (omega * cap['ESL'] - 1 / (omega * max(cap['C'], 1e-30))))
    curve = active_curve(cap)
    inside = np.zeros(frequency.shape, dtype=bool)
    result = nominal
    if curve:
        samples, magnitude, phase = np.asarray(curve['points'], dtype=float).T
        # An FFT bin mathematically equal to an endpoint can differ by a few ULPs.
        tolerance = 8 * np.finfo(float).eps
        inside = (frequency >= samples[0] * (1 - tolerance)) & (frequency <= samples[-1] * (1 + tolerance))
        if np.any(inside):
            sample_log = np.log(samples)
            query_log = np.log(frequency[inside])
            angle = np.deg2rad(phase)
            real = magnitude * np.cos(angle)
            real[np.abs(phase) == 90] = 0.
            measured = (np.interp(query_log, sample_log, real)
                        + 1j * np.interp(query_log, sample_log, magnitude * np.sin(angle)))
            result = nominal.copy()
            result[inside] = measured
    return (result, inside) if return_coverage else result


def parallel_response(impedances):
    """Return bank impedance and branch current ratios for each frequency."""
    if len(impedances) == 1:
        return impedances[0], np.ones_like(impedances)
    shorts = impedances == 0
    number_short = shorts.sum(axis=0)
    no_short = number_short == 0
    admittances = np.divide(1., impedances, out=np.zeros_like(impedances), where=~shorts)
    total = admittances.sum(axis=0)
    if np.any(no_short & (np.abs(total) < 1e-30)):
        raise ValueError('并联电容阻抗奇异：同一频率上各支路导纳相消')
    equivalent = np.divide(1., total, out=np.zeros_like(total), where=no_short)
    ratios = admittances * equivalent
    # When ideal branches have zero impedance at the same bin, use equal sharing
    # among those branches, the limit for equal infinitesimal series resistances.
    if np.any(~no_short):
        ratios[:, ~no_short] = shorts[:, ~no_short] / number_short[~no_short]
    return equivalent, ratios


def bank_uses_curves(caps):
    return any(active_curve(cap) for cap in caps or ())
