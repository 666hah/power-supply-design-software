// Run from the repository root after installing these pinned packages into
// artifacts/transformer-preview-build (see README). No network at runtime.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import fs from 'node:fs';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const vendor=path.join(root,'artifacts/transformer-preview-build/node_modules');
const require=createRequire(path.join(vendor,'esbuild/package.json'));
const {build}=require('esbuild');
await build({entryPoints:[path.join(here,'viewer.js')],outfile:path.join(here,'viewer.bundle.js'),bundle:true,format:'iife',platform:'browser',target:'es2020',minify:true,legalComments:'eof',nodePaths:[vendor]});
fs.copyFileSync(path.join(vendor,'three/LICENSE'),path.join(here,'THREE-LICENSE.txt'));
console.log('Built offline transformer preview');
