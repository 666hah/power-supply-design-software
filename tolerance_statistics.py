"""Input distributions and empirical tail statistics for hardware tolerance studies."""

import math
from numbers import Integral, Real

import numpy as np
from scipy.stats import truncnorm


DISTRIBUTIONS = ('bounds', 'uniform', 'triangular', 'normal')
SIGMA_MULTIPLIER = 4
TAIL_PROBABILITY = math.erfc(SIGMA_MULTIPLIER / math.sqrt(2)) / 2
COVERAGE_PROBABILITY = 1 - 2 * TAIL_PROBABILITY
MIN_EXPECTED_TAIL_COUNT = 20


def _number(entry, name, path):
    value = entry.get(name)
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f'{path} 的 {name} 必须为有限数值')
    return float(value)


def _label(value, name):
    if not isinstance(value, str):
        raise ValueError(f'{name} 必须为文本')
    return value.strip()


def normalize_variables(items):
    """Validate absolute SI settings without inferring a distribution or sigma."""
    if not isinstance(items, (list, tuple)):
        raise ValueError('器件容差必须为列表')
    variables = []
    paths = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('每项器件容差必须为对象')
        path = _label(item.get('path', ''), '容差参数路径')
        if not path or path in paths:
            raise ValueError(f'容差参数路径为空或重复：{path}')
        paths.add(path)
        nominal, low, high = (_number(item, key, path) for key in ('nominal', 'low', 'high'))
        width = high - low
        if not low <= nominal <= high or not math.isfinite(width):
            raise ValueError(f'{path} 必须满足下限 ≤ 标称值 ≤ 上限，且范围有限')
        distribution = _label(item.get('distribution', ''), '分布类型').lower()
        if distribution not in DISTRIBUTIONS:
            raise ValueError(f'{path} 请选择硬限值、均匀、三角或截断正态分布')
        sigma = _number(item, 'sigma', path) if distribution == 'normal' else None
        if sigma is not None:
            if sigma <= 0 or not math.isfinite(width / sigma):
                raise ValueError(f'{path} 的正态分布 σ 必须为有限正数并与限值同单位')
            if width and width / sigma < np.finfo(float).eps:
                raise ValueError(f'{path} 的截断范围相对 σ 过窄，无法可靠取样')
        source = _label(item.get('source', ''), '器件公差来源')
        group = _label(item.get('group', ''), '相关组')
        variables.append(dict(path=path, nominal=nominal, low=low, high=high,
                              distribution=distribution, sigma=sigma, source=source, group=group))
    return variables


def _nonnegative_int(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f'{name}必须为非负整数')
    return int(value)


def sample_variables(variables, n, seed):
    """Return one SI sample per unit and variable.

    Ungrouped rows use independent random draws. A named group shares the
    same random percentile across its variables, imposing positive rank
    dependence. Hard-limit enumeration is separate from this convention.
    """
    variables = normalize_variables(variables)
    n = _nonnegative_int(n, '蒙特卡洛样本数')
    seed = _nonnegative_int(seed, '随机种子')
    unsupported = [row['path'] for row in variables if row['distribution'] == 'bounds']
    if unsupported:
        raise ValueError('只有硬限值，尚未指定统计分布：' + '、'.join(unsupported))
    result = np.empty((n, len(variables)), dtype=float)
    rng = np.random.default_rng(seed)
    group_percentiles = {}
    for index, row in enumerate(variables):
        nominal, low, high = row['nominal'], row['low'], row['high']
        width = high - low
        if not width:
            result[:, index] = nominal
            continue
        group = row['group']
        if group:
            if group not in group_percentiles:
                group_percentiles[group] = rng.random(n)
            u = group_percentiles[group]
        else:
            u = rng.random(n)
        distribution = row['distribution']
        if distribution == 'uniform':
            values = low + width * u
        elif distribution == 'triangular':
            split = (nominal - low) / width
            fractions = np.where(u <= split, np.sqrt(u * split),
                                 1 - np.sqrt((1 - u) * (1 - split)))
            values = low + width * fractions
        else:
            sigma = row['sigma']
            a, b = (low - nominal) / sigma, (high - nominal) / sigma
            values = truncnorm.ppf(u, a, b, loc=nominal, scale=sigma)
        if not np.all(np.isfinite(values)):
            raise ValueError(f"{row['path']} 分布取样出现非有限结果")
        result[:, index] = np.clip(values, low, high)
    return result


def summarize_samples(values, attempted):
    """Summarize finite solver outputs and, when supported, empirical tails.

    Mean ±4 sample standard deviations is a descriptive statistic. The
    empirical quantiles use Gaussian-equivalent coverage probabilities even
    when model outputs are not normally distributed. The screening minimum
    expected tail count is a resolution check, not a confidence guarantee.
    """
    attempted = _nonnegative_int(attempted, '尝试样本数')
    sample = np.asarray(values, dtype=float)
    if sample.ndim != 1 or sample.size > attempted:
        raise ValueError('样本必须为一维列表，且数量不超过尝试次数')
    valid = sample[np.isfinite(sample)]
    count = len(valid)
    expected = count * TAIL_PROBABILITY
    mean = std = p05 = median = p95 = None
    histogram = dict(edges=[], counts=[])
    if count:
        constant = np.all(valid == valid[0])
        mean = float(valid[0]) if constant else float(np.mean(valid))
        if count > 1:
            std = 0.0 if constant else float(np.std(valid, ddof=1))
        p05, median, p95 = map(float, np.quantile(valid, (.05, .5, .95)))
        if constant:
            histogram = dict(edges=[mean, mean], counts=[count])
        else:
            counts, edges = np.histogram(valid, bins=min(25, math.ceil(math.sqrt(count))))
            histogram = dict(edges=edges.tolist(), counts=counts.tolist())
    moment_low = mean - SIGMA_MULTIPLIER * std if std is not None else None
    moment_high = mean + SIGMA_MULTIPLIER * std if std is not None else None
    if any(x is not None and not math.isfinite(x) for x in (mean, std, moment_low, moment_high)):
        raise ValueError('输出统计量超出数值范围')
    qlow = qhigh = None
    if not count:
        status = 'no_data'
    elif count != attempted:
        status = 'incomplete'
    elif expected < MIN_EXPECTED_TAIL_COUNT:
        status = 'insufficient_samples'
    else:
        status = 'available'
        qlow, qhigh = map(float, np.quantile(valid, (TAIL_PROBABILITY, 1 - TAIL_PROBABILITY)))
    return dict(count=count, attempted=attempted, missing_count=attempted-count,
                mean=mean, std=std, percentile_05=p05, median=median, percentile_95=p95,
                histogram=histogram, moment_4sigma_low=moment_low, moment_4sigma_high=moment_high,
                quantile_4sigma_low=qlow, quantile_4sigma_high=qhigh, expected_tail_count=expected,
                tail_probability=TAIL_PROBABILITY, coverage_probability=COVERAGE_PROBABILITY,
                tail_status=status)
