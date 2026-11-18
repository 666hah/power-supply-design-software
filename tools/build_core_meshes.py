"""Regenerate the complete versioned offline core mesh library from drawings."""
from __future__ import annotations
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core_mesh_library import INDEX_SCHEMA, record_signature, validate_mesh


def encode(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


def main():
    stage = ROOT / 'artifacts/core-mesh-build/raw'
    subprocess.run(['node', str(ROOT / 'tools/export_core_meshes.mjs'), str(stage)], check=True, cwd=ROOT)
    catalog_path = ROOT / 'resources/core_shapes/catalog.json'
    source_bytes = catalog_path.read_bytes()
    catalog = json.loads(source_bytes)
    records = {r['model']: r for r in catalog['cores']}
    exported = json.loads((stage / 'export-index.json').read_text('utf-8'))
    assert hashlib.sha256(source_bytes).hexdigest() == exported['catalog_sha256'], 'Catalogue changed while meshes were being generated'
    generator_hash = hashlib.sha256((ROOT / 'resources/transformer_preview/core_geometry.js').read_bytes()).hexdigest()
    assert generator_hash == exported['generator_sha256'], 'Geometry generator changed during mesh export'
    raw_index = exported['models']
    assert {r['model'] for r in raw_index} == set(records)
    bundles, entries = [], []
    for item in raw_index:
        model = item['model']
        mesh = json.loads((stage / item['file']).read_text('utf-8'))
        signature = record_signature(records[model])
        mesh['source_signature'] = signature
        stats = validate_mesh(mesh, model=model, source_signature=signature)
        decoded = encode(mesh)
        packed = gzip.compress(decoded, compresslevel=9, mtime=0)
        filename = hashlib.sha256(model.encode('utf-8')).hexdigest()[:20] + '.json.gz'
        bundles.append((filename, packed))
        entries.append(dict(model=model, file=filename, source_signature=signature,
            sha256=hashlib.sha256(packed).hexdigest(), decoded_sha256=hashlib.sha256(decoded).hexdigest(),
            compressed_bytes=len(packed), decoded_bytes=len(decoded), **stats))
    index = dict(schema=INDEX_SCHEMA, units='mm', geometry_state='nominal_ungapped',
        catalog_sha256=hashlib.sha256(source_bytes).hexdigest(),
        generator_sha256=generator_hash,
        models=entries)
    target = ROOT / 'resources/core_shapes/meshes'
    target.mkdir(parents=True, exist_ok=True)
    # Validate every model first, then publish deterministic files; index last.
    for filename, content in bundles + [('index.json', encode(index))]:
        path = target / filename
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_bytes(content)
        os.replace(temporary, path)
    print(json.dumps(dict(models=len(entries), compressed_bytes=sum(len(raw) for _, raw in bundles),
        triangles=sum(r['triangles'] for r in entries), directory=str(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
