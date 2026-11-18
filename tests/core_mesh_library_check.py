"""Bounded shipped meshes, catalogue identity and data-isolation checks."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import core_mesh_library as lib


def encoded(value):
    return json.dumps(value,separators=(',',':'),sort_keys=True).encode('utf-8')


class MeshBoundaryChecks(unittest.TestCase):
    def setUp(self):
        base=ROOT/'artifacts/core-mesh-qa';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base)
        self.base=Path(self.temp.name)
        self.source={'model':'E-TEST','dimensions_mm':{'width':1},'source_url':'https://example.invalid/qa'}
        self.mesh={'schema':lib.MESH_SCHEMA,'model':'E-TEST','units':'mm',
            'source_signature':lib.record_signature(self.source),
            'parts':[{'id':'half-a','name':'QA triangle','half':-1,'role':'body',
                'position_mm':[0,0,0],'positions':[0,0,0,1,0,0,0,1,0],'indices':[0,1,2]}],
            'bounds_mm':{'min':[0,0,0],'max':[1,1,0]}}
        self.catalog={'cores':[self.source]}
        self.write_fixture()
        self.mapping=patch.object(lib,'resource_path',lambda p:self.base/p)
        self.mapping.start();lib.clear_mesh_cache()

    def tearDown(self):
        lib.clear_mesh_cache();self.mapping.stop();self.temp.cleanup()

    def write_fixture(self):
        catalog_bytes=encoded(self.catalog)
        path=self.base/lib.CATALOG_RESOURCE;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(catalog_bytes)
        decoded=encoded(self.mesh);packed=gzip.compress(decoded,mtime=0)
        stats=lib.validate_mesh(self.mesh,model='E-TEST',source_signature=lib.record_signature(self.source))
        self.entry={'model':'E-TEST','file':'core.json.gz','source_signature':lib.record_signature(self.source),
            'sha256':hashlib.sha256(packed).hexdigest(),'decoded_sha256':hashlib.sha256(decoded).hexdigest(),
            'compressed_bytes':len(packed),'decoded_bytes':len(decoded),**stats}
        self.index={'schema':lib.INDEX_SCHEMA,'catalog_sha256':hashlib.sha256(catalog_bytes).hexdigest(),'models':[self.entry]}
        self.index_path=self.base/lib.INDEX_RESOURCE;self.index_path.parent.mkdir(parents=True,exist_ok=True)
        self.index_path.write_bytes(encoded(self.index));self.index_path.with_name('core.json.gz').write_bytes(packed)

    def test_exact_model_lookup_and_cached_copy_are_isolated(self):
        mesh=lib.get_core_mesh(' e-test ');mesh['parts'][0]['positions'][0]=999
        self.assertEqual(lib.get_core_mesh('E-TEST')['parts'][0]['positions'][0],0)
        for unknown in ('../core.json.gz','core.json.gz','https://example.invalid',None):
            with self.subTest(model=unknown),self.assertRaises(ValueError):lib.get_core_mesh(unknown)

    def test_corrupt_compressed_file_is_rejected(self):
        self.index_path.with_name('core.json.gz').write_bytes(b'not the shipped mesh')
        with self.assertRaisesRegex(ValueError,'校验失败'):lib.get_core_mesh('E-TEST')

    def test_catalogue_bytes_and_per_model_source_identity_are_checked(self):
        self.source['dimensions_mm']['width']=2
        source_bytes=encoded(self.catalog)
        (self.base/lib.CATALOG_RESOURCE).write_bytes(source_bytes)
        with self.assertRaisesRegex(ValueError,'版本不同'):lib.get_core_mesh('E-TEST')
        self.index['catalog_sha256']=hashlib.sha256(source_bytes).hexdigest()
        self.index_path.write_bytes(encoded(self.index));lib.clear_mesh_cache()
        with self.assertRaisesRegex(ValueError,'来源.*指纹'):lib.get_core_mesh('E-TEST')

    def test_index_cannot_escape_resource_directory(self):
        for bad in ('../core.json.gz','sub/core.json.gz','C:/core.json.gz','..\\core.json.gz'):
            self.index['models'][0]['file']=bad;self.index_path.write_bytes(encoded(self.index));lib.clear_mesh_cache()
            with self.subTest(path=bad),self.assertRaisesRegex(ValueError,'路径'):lib.get_core_mesh('E-TEST')

    def test_bad_triangle_semantics_and_nonfinite_vertices_are_rejected(self):
        for key,value in (('indices',[0,1,99]),('positions',[float('nan'),0,0,1,0,0,0,1,0]),
                          ('half',True),('role','unknown')):
            mesh=copy.deepcopy(self.mesh);mesh['parts'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):lib.validate_mesh(mesh)

    def test_decompression_has_independent_output_limit(self):
        decoded=b' '*4096
        packed=gzip.compress(decoded,mtime=0)
        self.entry.update(sha256=hashlib.sha256(packed).hexdigest(),compressed_bytes=len(packed),decoded_bytes=500)
        self.index_path.write_bytes(encoded(self.index));self.index_path.with_name('core.json.gz').write_bytes(packed)
        with patch.object(lib,'MAX_MESH_BYTES',1024),self.assertRaisesRegex(ValueError,'解压大小'):
            lib.get_core_mesh('E-TEST')


class ShippedMeshChecks(unittest.TestCase):
    def test_every_electrical_model_has_a_verified_independent_mesh(self):
        import magnetics
        lib.clear_mesh_cache()
        index=lib._index()
        self.assertEqual(set(index),{name.casefold() for name in magnetics.CORE_DB})
        for model in magnetics.CORE_DB:
            with self.subTest(model=model):
                mesh=lib.get_core_mesh(model)
                self.assertEqual(mesh['model'],model)
                self.assertTrue(mesh['parts'])
                self.assertEqual(mesh['geometry_state'],'nominal_ungapped')


if __name__=='__main__':unittest.main()
