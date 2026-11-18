"""Import impedance magnitude and phase sweeps without keeping file dependencies."""
from __future__ import annotations

import csv
import io
import json
import math
import re

from capacitor_impedance import validate_curve


MAX_BYTES = 2_000_000
_COLUMNS = (
    (('frequency', 'freq', 'f', '频率'),
     (('mhz', 1e6), ('khz', 1e3), ('hz', 1.), ('', 1.))),
    (('impedancemagnitude', 'magnitude', 'impedance', 'zmag', 'magz', 'absz', 'z',
      '阻抗幅值', '阻抗模值', '阻抗', '幅值'),
     (('megaohms', 1e6), ('megaohm', 1e6), ('megaω', 1e6), ('kohms', 1e3),
      ('kohm', 1e3), ('kω', 1e3), ('mohms', 1e-3), ('mohm', 1e-3), ('mω', 1e-3),
      ('ohms', 1.), ('ohm', 1.), ('ω', 1.), ('', 1.))),
    (('phaseangle', 'phase', 'theta', '相位角', '相位', '角度'),
     (('degrees', 1.), ('degree', 1.), ('deg', 1.), ('°', 1.), ('度', 1.),
      ('radians', 180 / math.pi), ('radian', 180 / math.pi),
      ('rad', 180 / math.pi), ('弧度', 180 / math.pi), ('', 1.))),
)


def _decode(data):
    if isinstance(data, str):
        if len(data.encode('utf-8')) > MAX_BYTES:
            raise ValueError('阻抗曲线文件不得超过 2 MB')
        return data.lstrip('\ufeff')
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise ValueError('阻抗曲线文件不得超过 2 MB')
    encodings = ('utf-16',) if data.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError('无法读取字符编码，请导出 UTF-8 CSV 或 JSON')


def _column(cell):
    # Match only named columns and known engineering prefixes. Preserve mega
    # before folding the remaining text so MΩ and mΩ cannot be confused.
    cell = re.sub(r'M(?=\s*(?:Ω|Ω|[Oo][Hh][Mm]))', 'mega', cell)
    word = re.sub(r'[^a-z0-9ω°\u4e00-\u9fff]', '',
                  cell.casefold().replace('θ', 'theta').replace('φ', 'phase'))
    for index, (names, units) in enumerate(_COLUMNS):
        for suffix, scale in units:
            if any(word == name + suffix for name in names) or (suffix and word == suffix):
                return index, scale
    return None


def _header(row):
    matching = {}
    for column, cell in enumerate(row):
        field = _column(cell)
        if field is not None:
            index, scale = field
            if index in matching:
                return None
            matching[index] = column, scale
    if len(matching) == 3:
        return [matching[i] for i in range(3)]
    return None


def _rows(text):
    # A machine can write preamble rows before its headers, so don't require
    # csv.Sniffer to infer a single column count from the whole file.
    for delimiter in (',', '\t', ';'):
        reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
        try:
            rows = [(reader.line_num, row) for row in reader
                    if any(cell.strip() for cell in row) and not row[0].lstrip().startswith('#')]
        except csv.Error:
            continue
        if not rows:
            continue
        for index, (_, row) in enumerate(rows):
            columns = _header(row)
            if columns is not None:
                return rows[index + 1:], columns, False
        # A headerless sweep is always exactly three columns, in the stated
        # SI/degree order. Require a numeric first row to avoid accepting a
        # recognized format with unsupported column names or units.
        first = rows[0][1]
        if len(first) == 3:
            try:
                tuple(float(value) for value in first)
            except ValueError:
                continue
            return rows, [(0, 1.), (1, 1.), (2, 1.)], True
    raise ValueError('请提供频率、阻抗幅值和相位三列，如 f_Hz,Z_ohm,phase_deg')


def parse_curve(data: str | bytes, *, name: str = '') -> dict:
    """Read a CSV/TSV/semicolon sweep or an embedded-curve JSON object.

    Headerless data uses frequency in Hz, |Z| in ohms, phase in degrees.
    Labeled columns support the documented unit conversions. The name is an
    optional display label, and its directory is discarded.
    """
    text = _decode(data).strip()
    label = re.split(r'[/\\]', name)[-1].strip()[:256]
    if text.startswith(('{', '[')):
        try:
            raw = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise ValueError('阻抗曲线 JSON 格式不正确') from exc
        if isinstance(raw, list):
            raw = {'points': raw}
        if not isinstance(raw, dict):
            raise ValueError('阻抗曲线 JSON 必须包含 points 数组')
        if label and 'source' not in raw:
            raw['source'] = label
        return validate_curve(raw)

    rows, columns, headerless = _rows(text)
    points = []
    for line, row in rows:
        try:
            if headerless and len(row) != 3:
                raise ValueError('无列标题时需要恰好三列')
            points.append([float(row[column]) * scale for column, scale in columns])
        except (IndexError, ValueError) as exc:
            raise ValueError(f'第 {line} 行需要三个有效数值，数值使用小数点') from exc
    result = {'points': points}
    if label:
        result['source'] = label
    return validate_curve(result)


def load_curve(path):
    """Read a bounded selected file and use its basename as the display label."""
    from pathlib import Path

    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    return parse_curve(data, name=path.name)
