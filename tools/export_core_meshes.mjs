// Build-time exporter only. No network and no runtime application server.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const vendor=path.join(root,'artifacts/transformer-preview-build/node_modules');
const require=createRequire(path.join(vendor,'esbuild/package.json'));
const {build}=require('esbuild');
const output=path.resolve(process.argv[2]||path.join(root,'artifacts/core-mesh-build/raw'));
fs.mkdirSync(output,{recursive:true});
const compiled=path.join(output,'geometry.cjs');
const geometryFile=path.join(root,'resources/transformer_preview/core_geometry.js');
const geometryHash=createHash('sha256').update(fs.readFileSync(geometryFile)).digest('hex');
await build({entryPoints:[geometryFile],
  outfile:compiled,bundle:true,format:'cjs',platform:'node',target:'node18',nodePaths:[vendor]});
const {generateCoreParts}=require(compiled);
const catalogRaw=fs.readFileSync(path.join(root,'resources/core_shapes/catalog.json'));
const catalogHash=createHash('sha256').update(catalogRaw).digest('hex');
const catalog=JSON.parse(catalogRaw.toString('utf8'));
const selected=process.argv[3]?new Set(process.argv[3].split(',')):null;
const manifest=[];
for(const [n,record] of catalog.cores.entries()){
  if(selected&&!selected.has(record.model))continue;
  const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
  const parts=generateCoreParts(record).map((part,i)=>{
    const g=part.geometry,positions=Array.from(g.getAttribute('position').array);
    const normals=g.getAttribute('normal')?Array.from(g.getAttribute('normal').array):null;
    const indices=g.index?Array.from(g.index.array):Array.from({length:positions.length/3},(_,j)=>j);
    const origin=part.position_mm;
    for(let j=0;j<positions.length;j++){const axis=j%3,p=positions[j]+origin[axis];min[axis]=Math.min(min[axis],p);max[axis]=Math.max(max[axis],p);}
    const result={id:part.id||`part-${i+1}`,name:part.name,half:part.half,role:part.role,
      position_mm:origin,positions,indices};
    if(normals)result.normals=normals;
    g.dispose();return result;
  });
  const name=`model-${String(n).padStart(3,'0')}.json`;
  fs.writeFileSync(path.join(output,name),JSON.stringify({schema:'power-core-mesh.v1',model:record.model,
    units:'mm',geometry_state:'nominal_ungapped',parts,bounds_mm:{min,max}}));
  manifest.push({model:record.model,file:name});
}
if(geometryHash!==createHash('sha256').update(fs.readFileSync(geometryFile)).digest('hex'))throw Error('Geometry generator changed during export; retry after edits finish.');
fs.writeFileSync(path.join(output,'export-index.json'),JSON.stringify({catalog_sha256:catalogHash,generator_sha256:geometryHash,models:manifest}));
console.log(`Exported ${manifest.length} nominal core models to ${output}`);
