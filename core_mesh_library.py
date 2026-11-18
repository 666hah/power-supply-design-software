"""Bounded, verified reads from the shipped magnetic-core triangle library.

No input is interpreted as a path. Meshes are selected by the exact model names
in the bundled catalogue, verified against its bytes, and returned as independent
JSON values. Units and geometry remain separate from electrical Ae/Ve inputs.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import gzip
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath

from app_resources import resource_path

INDEX_RESOURCE = 'resources/core_shapes/meshes/index.json'
CATALOG_RESOURCE = 'resources/core_shapes/catalog.json'
INDEX_SCHEMA = 'power-core-mesh-library.v1'
MESH_SCHEMA = 'power-core-mesh.v1'
MAX_INDEX_BYTES = 1024 * 1024
MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_COMPRESSED_BYTES = 8 * 1024 * 1024
MAX_MESH_BYTES = 32 * 1024 * 1024
MAX_VERTICES = 500000
MAX_INDICES = 3000000


def _json(raw):
    def reject(value):
        raise ValueError('网格数据存在非有限数值：' + value)
    return json.loads(raw.decode('utf-8-sig'), parse_constant=reject)


def _bounded_read(path, maximum):
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('内置模型资源超过大小限制：' + Path(path).name)
    return raw


def record_signature(record):
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_mesh(mesh, *, model=None, source_signature=None):
    """Validate the data boundary; this is not a manufacturing/CAD approval."""
    if not isinstance(mesh, dict) or mesh.get('schema') != MESH_SCHEMA or mesh.get('units') != 'mm':
        raise ValueError('磁芯网格格式或单位错误。')
    if model is not None and mesh.get('model') != model:
        raise ValueError('磁芯网格型号与目录不一致。')
    if source_signature is not None and mesh.get('source_signature') != source_signature:
        raise ValueError('磁芯网格与规格目录的来源指纹不一致，请重新生成内置模型库。')
    parts = mesh.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 512:
        raise ValueError('磁芯部件列表无效。')
    ids = set()
    vertex_count = index_count = 0
    low, high = [math.inf] * 3, [-math.inf] * 3
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError('磁芯部件格式无效。')
        ident = part.get('id')
        if not isinstance(ident, str) or not ident or len(ident) > 100 or ident in ids:
            raise ValueError('磁芯部件标识为空或重复。')
        ids.add(ident)
        if part.get('role') not in ('center', 'return', 'yoke', 'body'):
            raise ValueError('磁芯部件角色无效。')
        if type(part.get('half')) is not int or part['half'] not in (-1, 0, 1):
            raise ValueError('磁芯半芯标识无效。')
        origin = part.get('position_mm')
        if not isinstance(origin, list) or len(origin) != 3 or not all(_number(v) for v in origin):
            raise ValueError('磁芯部件定位无效。')
        vertices, indices, normals = part.get('positions'), part.get('indices'), part.get('normals')
        if not isinstance(vertices, list) or len(vertices) < 9 or len(vertices) % 3:
            raise ValueError('磁芯顶点数组无效。')
        if not all(_number(v) for v in vertices):
            raise ValueError('磁芯顶点存在非有限数值。')
        count = len(vertices) // 3
        if not isinstance(indices, list) or len(indices) < 3 or len(indices) % 3:
            raise ValueError('磁芯三角面索引无效。')
        if not all(type(i) is int and 0 <= i < count for i in indices):
            raise ValueError('磁芯三角面索引越界。')
        if normals is not None and (not isinstance(normals, list) or len(normals) != len(vertices)
                                    or not all(_number(v) for v in normals)):
            raise ValueError('磁芯法线数据无效。')
        vertex_count += count
        index_count += len(indices)
        if vertex_count > MAX_VERTICES or index_count > MAX_INDICES:
            raise ValueError('磁芯网格规模超过加载上限。')
        for axis in range(3):
            low[axis] = min(low[axis], min(vertices[axis::3]) + origin[axis])
            high[axis] = max(high[axis], max(vertices[axis::3]) + origin[axis])
    bounds = mesh.get('bounds_mm')
    if bounds is not None:
        if not isinstance(bounds, dict):
            raise ValueError('磁芯包络格式无效。')
        for key, expected in (('min', low), ('max', high)):
            values = bounds.get(key)
            if not isinstance(values, list) or len(values) != 3 or not all(_number(v) for v in values):
                raise ValueError('磁芯包络数据无效。')
            if any(abs(a - b) > 1e-5 for a, b in zip(values, expected)):
                raise ValueError('磁芯顶点包络与文件声明不一致。')
    return {'parts': len(parts), 'vertices': vertex_count, 'triangles': index_count // 3,
            'bounds_mm': {'min': low, 'max': high}}


@lru_cache(maxsize=1)
def _index():
    path = resource_path(INDEX_RESOURCE)
    index = _json(_bounded_read(path, MAX_INDEX_BYTES))
    if not isinstance(index, dict) or index.get('schema') != INDEX_SCHEMA:
        raise ValueError('内置磁芯网格目录版本无效。')
    catalog_bytes = _bounded_read(resource_path(CATALOG_RESOURCE), MAX_CATALOG_BYTES)
    if hashlib.sha256(catalog_bytes).hexdigest() != index.get('catalog_sha256'):
        raise ValueError('磁芯网格库与规格目录版本不同，请更新完整程序包。')
    catalog = _json(catalog_bytes)
    sources = {r['model']: r for r in catalog['cores']}
    entries = index.get('models')
    if not isinstance(entries, list) or len(entries) != len(sources):
        raise ValueError('内置磁芯网格目录没有覆盖全部型号。')
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('内置磁芯目录条目格式无效。')
        model = entry.get('model')
        if not isinstance(model, str) or model not in sources or model.casefold() in result:
            raise ValueError('内置磁芯网格存在未知或重复型号。')
        relative = entry.get('file', '')
        if not isinstance(relative, str):
            raise ValueError('磁芯网格路径格式无效。')
        safe = PurePosixPath(relative)
        if (not relative or '\\' in relative or ':' in relative or safe.is_absolute()
                or len(safe.parts) != 1 or safe.name in ('.', '..') or not relative.endswith('.json.gz')):
            raise ValueError('磁芯网格路径不在内置模型库中。')
        if entry.get('source_signature') != record_signature(sources[model]):
            raise ValueError('磁芯规格来源与网格指纹不一致：' + model)
        for key, cap in (('compressed_bytes', MAX_COMPRESSED_BYTES), ('decoded_bytes', MAX_MESH_BYTES)):
            value = entry.get(key)
            if type(value) is not int or not 0 < value <= cap:
                raise ValueError('磁芯网格大小声明无效。')
        result[model.casefold()] = entry
    return result


@lru_cache(maxsize=8)
def _load(model_key):
    entry = _index().get(model_key)
    if entry is None:
        raise ValueError('该型号不在内置磁芯模型库中。')
    root = resource_path(INDEX_RESOURCE).parent.resolve()
    path = (root / entry['file']).resolve()
    if path.parent != root:
        raise ValueError('磁芯网格路径越过内置模型目录。')
    raw = _bounded_read(path, MAX_COMPRESSED_BYTES)
    if len(raw) != entry['compressed_bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('磁芯网格文件校验失败：' + entry['model'])
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            decoded = stream.read(MAX_MESH_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise ValueError('磁芯网格压缩格式错误。') from exc
    if len(decoded) != entry['decoded_bytes'] or len(decoded) > MAX_MESH_BYTES:
        raise ValueError('磁芯网格解压大小与目录不符。')
    if hashlib.sha256(decoded).hexdigest() != entry['decoded_sha256']:
        raise ValueError('磁芯网格内容校验失败。')
    mesh = _json(decoded)
    stats = validate_mesh(mesh, model=entry['model'], source_signature=entry['source_signature'])
    for key in ('parts', 'vertices', 'triangles'):
        if stats[key] != entry[key]:
            raise ValueError('磁芯网格统计与目录不一致。')
    return mesh


def get_core_mesh(model):
    """Select a catalogue model, never a filesystem path; return an owned copy."""
    if not isinstance(model, str) or not model.strip() or len(model) > 100:
        raise ValueError('请选择有效的内置磁芯型号。')
    return copy.deepcopy(_load(model.strip().casefold()))


def clear_mesh_cache():
    _load.cache_clear()
    _index.cache_clear()
