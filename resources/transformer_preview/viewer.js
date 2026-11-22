import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { buildWindingPaths } from './winding_paths.js';

// A presentation-only mesh. Electrical and FEM inputs are never written here.
const $ = id => document.getElementById(id);
const palette = ['#8b381e','#174c80','#166756','#683b8c','#a77b16','#922b4b','#3f596b','#773e24'];
const state = {payload:null, design:null, mode:'all', auto:false, sectionGroups:[], coreParts:[], insulation:[], leads:[], crossovers:[], windingPaths:null, catalog:[], displayOnly:false, curveSteps:64, tubeSides:12};
let renderer, scene, camera, controls, assembly, grid, renderTimer, autoTimer, orthoHeight=60;
const viewport=$('viewport');
function status(text){$('status').textContent=text;}
function failure(text){$('fatal').hidden=false;$('fatal').textContent=text;$('loading').hidden=true;status(text);}
function queueRender(){if(!renderTimer)renderTimer=requestAnimationFrame(()=>{renderTimer=null;renderer?.render(scene,camera);});}
function resizeViewport(){const w=viewport.clientWidth,h=viewport.clientHeight;if(w&&h){renderer.setSize(w,h,false);if(camera.isOrthographicCamera){camera.left=-orthoHeight*w/h/2;camera.right=-camera.left;camera.top=orthoHeight/2;camera.bottom=-camera.top;}else camera.aspect=w/h;camera.updateProjectionMatrix();}}
function init(){
  scene=new THREE.Scene();scene.background=new THREE.Color('#f5f8fc');
  renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.25;
  viewport.appendChild(renderer.domElement);
  renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();failure('三维显示资源已释放，请关闭并重新打开此窗口。');});
  camera=new THREE.PerspectiveCamera(36,1,.01,10000);camera.up.set(0,0,1);
  controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=false;controls.screenSpacePanning=true;controls.minDistance=.1;controls.maxDistance=10000;controls.addEventListener('change',queueRender);
  scene.add(new THREE.HemisphereLight(0xffffff,0x647484,2.1));
  const key=new THREE.DirectionalLight(0xffffff,3);key.position.set(40,-60,90);scene.add(key);
  const fill=new THREE.DirectionalLight(0xb9d6ff,1.4);fill.position.set(-50,30,25);scene.add(fill);
  assembly=new THREE.Group();scene.add(assembly);
  new ResizeObserver(()=>{resizeViewport();queueRender();}).observe(viewport);
  renderer.domElement.addEventListener('pointermove',hover);renderer.domElement.addEventListener('pointerleave',()=>{$('selection').hidden=true;});
  $('loading').textContent='等待工程结构…';
}
function disposeGroup(group){group.traverse(o=>{o.geometry?.dispose();if(o.material){for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();}});group.clear();}
function mesh(geometry,material,parent=assembly){const m=new THREE.Mesh(geometry,material);parent.add(m);return m;}
function coreMaterial(){return new THREE.MeshStandardMaterial({color:0x6685a4,metalness:.05,roughness:.7,transparent:true,opacity:Number($('opacity').value)/100,depthWrite:false,side:THREE.DoubleSide});}
function cylinder(r,h){const g=new THREE.CylinderGeometry(r,r,h,96,1);g.rotateX(Math.PI/2);return g;}
function addCore(g,x,y,z,half,name){const m=mesh(g,coreMaterial());m.position.set(x,y,z);m.userData={kind:'core',name,half,origin:m.position.clone()};
  const edge=new THREE.LineSegments(new THREE.EdgesGeometry(g,25),new THREE.LineBasicMaterial({color:0x4c657d,transparent:true,opacity:.4,depthTest:true}));m.add(edge);m.userData.edge=edge;state.coreParts.push(m);return m;}
function buildCore(record, data, gap = 0, gapKind = 'none') {
  if (!record || record.status === 'dimensions_pending') return;
  if (!data || data.error) throw new Error(data?.error || `内置模型库缺少 ${record.model} 的三维网格`);
  if (data.model !== record.model || data.schema !== 'power-core-mesh.v1') throw new Error('磁芯网格与当前型号不匹配');
  const spaced = gapKind === 'spacer';
  for (const part of data.parts) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(part.positions, 3));
    if (part.indices?.length) geometry.setIndex(part.indices);
    if (part.normals?.length) geometry.setAttribute('normal', new THREE.Float32BufferAttribute(part.normals, 3));
    else geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    const origin = [...part.position_mm];
    if (spaced) origin[2] += part.half * gap / 2;
    const m = addCore(geometry, ...origin, part.half, part.name);
    m.userData.role = part.role;
    if (!spaced && gapKind === 'center_leg_ground' && part.role === 'center') {
      const cut = gap / (record.template === 'ei_rect' ? 1 : 2);
      const height = geometry.boundingBox.max.z - geometry.boundingBox.min.z;
      if (cut >= height) throw new Error('声明气隙大于或等于中柱高度，请核对加工尺寸');
      m.scale.z = (height - cut) / height;
      m.position.z += part.half * cut / 2;
      m.userData.origin.copy(m.position);
    }
  }
}

function conductorMaterial(color) {
  return new THREE.MeshStandardMaterial({color, metalness: .28, roughness: .31, side: THREE.DoubleSide});
}

function conductorGeometry(samples) {
  const vertices = [], normals = [], indices = [], sides = state.tubeSides;
  const point = i => new THREE.Vector3(...samples[i].point);
  for (let i = 0; i < samples.length; i++) {
    const sample = samples[i], center = point(i);
    const tangent = point(Math.min(samples.length - 1, i + 1))
      .sub(point(Math.max(0, i - 1))).normalize();
    let radial = new THREE.Vector3(...sample.normal);
    radial.addScaledVector(tangent, -radial.dot(tangent));
    if (radial.lengthSq() < 1e-10) {
      radial = new THREE.Vector3(Math.abs(tangent.x) < .8 ? 1 : 0, Math.abs(tangent.x) < .8 ? 0 : 1, 0);
      radial.addScaledVector(tangent, -radial.dot(tangent));
    }
    radial.normalize();
    const axial = new THREE.Vector3().crossVectors(tangent, radial).normalize();
    const r = Math.max(sample.height / 2, 1e-8), z = Math.max(sample.width / 2, 1e-8);
    for (let side = 0; side < sides; side++) {
      const angle = side / sides * 2 * Math.PI, c = Math.cos(angle), s = Math.sin(angle);
      const position = center.clone().addScaledVector(radial, r * c).addScaledVector(axial, z * s);
      const normal = radial.clone().multiplyScalar(c / r).addScaledVector(axial, s / z).normalize();
      vertices.push(...position.toArray());
      normals.push(...normal.toArray());
      if (i < samples.length - 1) {
        const a = i * sides + side, b = i * sides + (side + 1) % sides;
        indices.push(a, b, a + sides, b, b + sides, a + sides);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setIndex(indices);
  geometry.computeBoundingSphere();
  return geometry;
}

function buildWindings(payload) {
  const total = (payload.windings || []).reduce((n, w) => n + w.sections.reduce((s, l) => s + l.turns.length, 0), 0);
  if (total > 12000) throw Error(`当前共有 ${total.toLocaleString()} 个线束截面，超过单次 3D 预览的 12,000 个上限；请减少预览工程规模，计算数据未删减。`);
  state.curveSteps = total > 2000 ? 20 : total > 1000 ? 32 : total > 300 ? 48 : 64;
  state.tubeSides = total > 300 ? 8 : 12;
  if (!total) return;
  const placement = payload.placement;
  if (!placement) throw Error('当前工程未给出绕组路径');
  const paths = buildWindingPaths(payload, state.curveSteps);
  state.windingPaths = paths;
  const groups = new Map();
  for (let wi = 0; wi < payload.windings.length; wi++) {
    const winding = payload.windings[wi], color = winding.color || palette[wi % palette.length];
    for (const section of winding.sections) {
      const group = new THREE.Group();
      assembly.add(group);
      group.userData = {id: section.id, winding: winding.id, enabled: true,
        origin: group.position.clone(), kind: 'winding', layer: section.layer_index};
      state.sectionGroups.push(group);
      groups.set(section.id, group);
      if (section.insulation_before_mm > 0 && section.turns.length && placement.route_type === 'circular') {
        const turns = section.turns;
        const u0 = Math.min(...turns.map(t => t.center_mm[0] - t.width_mm / 2));
        const u1 = Math.max(...turns.map(t => t.center_mm[0] + t.width_mm / 2));
        const radius = placement.r0_mm + Math.min(...turns.map(t => t.center_mm[1] - t.height_mm / 2)) - section.insulation_before_mm / 2;
        if (radius > 0) {
          const sheet = mesh(cylinder(radius, u1 - u0), new THREE.MeshStandardMaterial({
            color: 0xd7ac54, transparent: true, opacity: .12, side: THREE.DoubleSide, depthWrite: false}));
          sheet.position.z = (placement.z0_mm || 0) + (u0 + u1) / 2;
          sheet.userData = {layer: section.layer_index, origin: sheet.position.clone()};
          state.insulation.push(sheet);
        }
      }
    }
    for (const track of paths.tracks.filter(t => t.winding === winding)) {
      const m = mesh(conductorGeometry(track.samples), conductorMaterial(color), groups.get(track.section.id));
      m.userData = {kind: 'winding', name: `${winding.name || winding.id} · ${track.section.id} · ${track.turns.length} 匝 · 线束 ${track.key}`,
        section: track.section.id, track: track.key};
    }
    for (const link of paths.links.filter(l => l.winding === winding)) {
      const m = mesh(conductorGeometry(link.samples), conductorMaterial(color));
      const type = link.connection.kind === 'pin_return' ? '针脚侧回线' : link.connection.kind === 'declared' ? '已声明跨层引线' : '相邻层折返';
      m.userData = {kind: 'crossover', winding: winding.id, sections: [link.from.section.id, link.to.section.id],
        name: `${winding.name || winding.id} · ${link.from.section.id} → ${link.to.section.id} · ${type} · 线束 ${link.key}`};
      state.crossovers.push(m);
    }
  }
  for (const lead of payload.leads || []) {
    if (!lead.path_xyz_mm || lead.path_xyz_mm.length < 2) continue;
    const points = lead.path_xyz_mm.map(p => new THREE.Vector3(...p));
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({color: 0x624a33}));
    line.userData = {kind: 'lead', name: `已声明引线 ${lead.node}`};
    assembly.add(line);
    state.leads.push(line);
  }
}
function addGrid(){
  if(grid){scene.remove(grid);grid.geometry.dispose();grid.material.dispose();}
  const bounds=new THREE.Box3().setFromObject(assembly),size=bounds.getSize(new THREE.Vector3()),span=Math.max(size.x,size.y,size.z,10);
  grid=new THREE.GridHelper(Math.ceil(span*1.8/10)*10,20,0xc4d4e4,0xe2eaf3);grid.rotation.x=Math.PI/2;grid.position.z=bounds.isEmpty()?-20:bounds.min.z-span*.06;grid.visible=$('grid').checked;scene.add(grid);
  $('scale').textContent=`尺寸 / mm · 网格 ${(Math.ceil(span*1.8/10)*10/20).toFixed(1)} mm`;
}
function fitView(kind='perspective'){
  const b=new THREE.Box3();for(const item of [...state.coreParts,...state.sectionGroups,...state.leads,...state.crossovers])if(item.visible)b.expandByObject(item);if(b.isEmpty()){b.min.set(-15,-15,-15);b.max.set(15,15,15);}
  const aspect=viewport.clientWidth/viewport.clientHeight||1;
  const center=b.getCenter(new THREE.Vector3()),size=b.getSize(new THREE.Vector3()),r=Math.max(size.x,size.y,size.z,5),dist=r/(2*Math.tan(THREE.MathUtils.degToRad(18)))*Math.max(1,1/aspect)*1.45;
  if(kind==='perspective')camera=new THREE.PerspectiveCamera(36,aspect,.01,dist*100);
  else {orthoHeight=r*Math.max(1,1/aspect)*1.35;camera=new THREE.OrthographicCamera(-orthoHeight*aspect/2,orthoHeight*aspect/2,orthoHeight/2,-orthoHeight/2,.01,dist*100);}
  camera.up.set(0,kind==='top'?1:0,kind==='top'?0:1);controls.object=camera;
  const direction=kind==='front'?new THREE.Vector3(0,-1,0):kind==='top'?new THREE.Vector3(0,0,1):kind==='side'?new THREE.Vector3(1,0,0):new THREE.Vector3(1.05,-1.5,.95);
  camera.position.copy(center).add(direction.normalize().multiplyScalar(dist));camera.near=Math.max(.001,dist/1000);camera.far=dist*100;camera.updateProjectionMatrix();controls.target.copy(center);controls.update();
  for(const id of ['perspective','front','top','side'])$(id).classList.toggle('active',id===kind);queueRender();
}
function applyVisibility(){
  $('selection').hidden=true;$('selection').textContent='';
  const opacity=Number($('opacity').value)/100,explode=Number($('explode').value)/100;
  const d=state.payload?.core?.dimensions_mm,span=d?.half_height||20;
  const half=$('coreHalf').value;
  for(const m of state.coreParts){m.visible=state.mode!=='windings'&&(opacity>0||$('edges').checked)&&(m.userData.half===0||half==='both'||(half==='lower'?m.userData.half<0:m.userData.half>0));const transparent=opacity<.999;if(m.material.transparent!==transparent){m.material.transparent=transparent;m.material.depthWrite=!transparent;m.material.needsUpdate=true;}m.material.opacity=opacity;m.material.visible=opacity>0;m.userData.edge.visible=$('edges').checked;m.userData.edge.material.opacity=.32+.5*opacity;m.position.copy(m.userData.origin);m.position.z+=m.userData.half*explode*span*1.1;}
  for(const group of state.sectionGroups){group.visible=state.mode!=='core'&&group.userData.enabled;group.position.copy(group.userData.origin);group.position.x+=explode*(group.userData.layer-1)*span*.55;}
  for(const connector of state.crossovers){connector.visible=state.mode!=='core'&&explode===0&&connector.userData.sections.every(id=>state.sectionGroups.some(group=>group.userData.id===id&&group.userData.enabled));}
  for(const m of state.insulation){const owner=state.sectionGroups.find(g=>g.userData.layer===m.userData.layer);m.visible=$('insulation').checked&&state.mode!=='core'&&(owner?.userData.enabled??true);m.position.copy(m.userData.origin);m.position.x+=explode*(m.userData.layer-1)*span*.55;}
  if(grid)grid.visible=$('grid').checked;
  for(const lead of state.leads)lead.visible=state.mode!=='core';
  $('opacityValue').textContent=`${$('opacity').value}%`;$('explodeValue').textContent=`${$('explode').value}%`;queueRender();
}
function labelNode(tag,text,className=''){const e=document.createElement(tag);e.textContent=text;if(className)e.className=className;return e;}
function layerUI(payload){
  const root=$('layers');root.replaceChildren();
  for(let wi=0;wi<(payload.windings||[]).length;wi++){
    const w=payload.windings[wi],card=labelNode('div','','winding'),head=labelNode('label','','winding-head'),toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=true;
    const swatch=labelNode('span','','swatch');swatch.style.background=w.color||palette[wi%palette.length];const name=labelNode('span',w.name||w.id,'winding-name');name.title=w.name||w.id;head.append(toggle,swatch,name,labelNode('small',`${w.sections.length} 层`));card.append(head);
    toggle.addEventListener('change',()=>{for(const g of state.sectionGroups)if(g.userData.winding===w.id)g.userData.enabled=toggle.checked;card.querySelectorAll('input').forEach(i=>i.checked=toggle.checked);applyVisibility();});
    for(const s of w.sections){const row=labelNode('label','','layer'),cb=document.createElement('input');cb.type='checkbox';cb.checked=true;cb.dataset.section=s.id;row.title=`物理段 ${s.id}`;row.append(cb,labelNode('span',`第 ${s.layer_index} 层 · ${w.id}`,'layer-name'),labelNode('small',`${s.turn_count??new Set(s.turns.map(t=>t.turn_index)).size} 匝`));card.append(row);cb.addEventListener('change',()=>{const g=state.sectionGroups.find(g=>g.userData.id===s.id);if(g)g.userData.enabled=cb.checked;toggle.checked=[...card.querySelectorAll('[data-section]')].every(i=>i.checked);applyVisibility();});}
    root.append(card);
  }
  if(!root.children.length)root.append(labelNode('p',state.displayOnly?'磁芯库浏览 · 未带入当前工程绕组':'当前尚无可显示的绕组结构','muted'));
}
function showInfo(core){
  const el=$('coreInfo');el.replaceChildren();if(!core)return;
  const pending=core.status==='dimensions_pending',named=core.status==='designation_nominal',variant=core.status==='reference_variant',d=core.dimensions_mm;
  el.append(labelNode('span',pending?'机械尺寸待补齐':named?'型号名义尺寸 · 待核规格':variant?'规格书参考变体':'规格书名义尺寸',`tag${pending||named||variant?' pending':''}`));
  const dl=document.createElement('dl');const row=(k,v)=>{dl.append(labelNode('dt',k),labelNode('dd',v||'—'));};
  row('型号',core.reference_model||core.model);row('厂家',core.manufacturer);if(d?.width&&d?.depth)row('外形 / mm',`${d.width} × ${d.depth} × ${d.height??d.full_height??(core.template==='ei_rect'?d.half_height+d.i_height:2*d.half_height)}`);
  if(d?.center_diameter)row('中柱 / mm',`Ø ${d.center_diameter}`);if(d?.window_height)row('沟深 / mm',`${d.window_height}${core.template==='ei_rect'?'（E 芯）':'（半芯）'}`);if(core.source_page)row('来源页',String(core.source_page));el.append(dl);
  if(core.source_url&&/^https:\/\//.test(core.source_url)){const a=labelNode('a','查看尺寸来源 ↗');a.href=core.source_url;a.target='_blank';a.rel='noopener noreferrer';el.append(a);}
}
function showNotes(payload){const el=$('notes');el.replaceChildren();for(const n of [...(payload.notes||[]),...(payload.core?.notes||[]),...(state.windingPaths?.notes||[])]){const text=typeof n==='string'?n:n.text||n.message||JSON.stringify(n);el.append(labelNode('p',text,n.severity==='warning'?'warning':''));}if(payload.core?.status==='dimensions_pending')el.prepend(labelNode('p','该型号机械尺寸尚待核对，当前不生成磁芯外形。','warning'));if(state.curveSteps<64)el.append(labelNode('p',`当前线束较多，曲面每匝采用 ${state.curveSteps} 段显示；全部匝数和原截面尺寸保留。`));if(state.crossovers.length)el.append(labelNode('p','层间跨线按串联接线显示，分解装配时暂时隐藏；回线附近的局部撑高为装配示意。'));if(payload.leads?.length)el.append(labelNode('p','分解装配时，已声明外部引线保留原始坐标。'));}
function catalogUI(catalog){
  state.catalog=catalog||[];const select=$('catalog');select.replaceChildren(new Option('当前工程磁芯',''));let families=new Map();
  for(const record of state.catalog){
    if(!families.has(record.family)){const group=document.createElement('optgroup');group.label=record.family;select.append(group);families.set(record.family,group);}
    families.get(record.family).append(new Option(`${record.model}${record.status==='dimensions_pending'?' · 尺寸待补':record.status==='designation_nominal'?' · 待核规格':record.status==='reference_variant'?' · 参考变体':''}`,record.model));
  }
}
function showPayload(payload,{keepView=false}={}){
  if(!renderer)return;state.payload=payload;$('fatal').hidden=true;$('loading').hidden=true;
  disposeGroup(assembly);state.coreParts=[];state.sectionGroups=[];state.insulation=[];state.leads=[];state.crossovers=[];state.windingPaths=null;
  try{buildCore(payload.core,payload.core_mesh,payload.gap_mm||0,payload.gap_kind);buildWindings(payload);}
  catch(e){failure(e.message);}
  layerUI(payload);showInfo(payload.core);showNotes(payload);addGrid();applyVisibility();
  $('coreHalf').disabled=payload.core?.template==='toroid';
  $('subtitle').textContent=payload.stale?'上一有效计算 · 等待重新计算':payload.title||'绕组结构与磁芯装配';$('subtitle').style.color=payload.stale?'#f2c77b':'';$('identity').textContent=`${payload.core?.model||'自定义磁芯'}${payload.gap_mm>0?' · 声明气隙 '+payload.gap_mm.toFixed(3)+' mm':''}${state.displayOnly?' · 模型库':''}${payload.stale?' · 上一有效计算':''}`;
  if(!keepView)fitView();
  const layers=state.sectionGroups.length,turns=(payload.windings||[]).reduce((n,w)=>n+w.sections.reduce((m,s)=>m+s.turns.length,0),0);
  if($('fatal').hidden)status(state.displayOnly?'模型库仅用于查看，不更改工程的磁芯选型':`${layers} 个物理层 · ${turns} 个线束截面 · ${payload.stale?'上一有效计算，重新计算后更新绕组':'当前输入的三维结构预览'}`);
  renderer.render(scene,camera);$('meshStatus').textContent=`${Math.round(renderer.info.render.triangles/1000)}k 三角面 · GPU`;
}
window.updateScene=function(payload){
  if(!payload||typeof payload!=='object')return;
  libraryRequest++;
  state.design=payload;state.displayOnly=false;$('returnDesign').hidden=true;catalogUI(payload.catalog||state.catalog);
  showPayload(payload,{keepView:Boolean(state.payload&&payload.core?.model===state.payload.core?.model)});
};
let lastHover=0;
function hover(event){if(event.buttons||performance.now()-lastHover<50)return;lastHover=performance.now();const rect=renderer.domElement.getBoundingClientRect(),pointer=new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2);const ray=new THREE.Raycaster();ray.setFromCamera(pointer,camera);const candidates=state.crossovers.filter(m=>m.visible);for(const g of state.sectionGroups)if(g.visible)g.traverse(o=>{if(o.isMesh)candidates.push(o);});const hit=ray.intersectObjects(candidates,false)[0];$('selection').hidden=!hit;if(hit)$('selection').textContent=hit.object.userData.name;}
function animate(time){autoTimer=null;if(state.auto){controls.autoRotate=true;controls.autoRotateSpeed=.65;controls.update();renderer.render(scene,camera);autoTimer=requestAnimationFrame(animate);}else controls.autoRotate=false;}
for(const id of ['perspective','front','top','side'])$(id).onclick=()=>fitView(id);
$('reset').onclick=()=>{$('explode').value='0';applyVisibility();fitView();};
$('rotate').onclick=()=>{state.auto=!state.auto;$('rotate').classList.toggle('active',state.auto);$('rotate').textContent=state.auto?'暂停旋转':'自动旋转';if(state.auto&&!autoTimer)autoTimer=requestAnimationFrame(animate);else controls.autoRotate=false;};
for(const id of ['opacity','explode','insulation','edges','grid'])$(id).addEventListener('input',applyVisibility);
$('coreHalf').addEventListener('change',()=>{applyVisibility();fitView(document.querySelector('.toolbar .segmented button.active')?.id||'perspective');});
function setMode(mode){state.mode=mode;document.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('active',x.dataset.mode===mode));applyVisibility();}
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$('allLayers').onclick=()=>{for(const g of state.sectionGroups)g.userData.enabled=true;$('layers').querySelectorAll('input').forEach(i=>i.checked=true);applyVisibility();};
let libraryRequest=0;
$('catalog').onchange=async()=>{
  const request=++libraryRequest,model=$('catalog').value;
  if(!model){state.displayOnly=false;$('returnDesign').hidden=true;setMode('all');showPayload(state.design);return;}
  const core=state.catalog.find(r=>r.model===model);if(!core)return;
  state.displayOnly=true;$('returnDesign').hidden=false;setMode('core');
  status(`正在读取内置模型 ${model}…`);
  try{
    const core_mesh=state.design?.core?.model===model?state.design.core_mesh:await window.pywebview?.api?.core_mesh(model);
    if(request!==libraryRequest)return;
    showPayload({core,core_mesh,windings:[],title:`磁芯模型库 · ${core.model}`,notes:['当前为单独磁芯预览。选择型号不会更改电气计算和当前工程绕制。']});
  }catch(error){if(request===libraryRequest)failure('无法读取内置磁芯模型：'+error.message);}
};
$('returnDesign').onclick=()=>{$('catalog').value='';$('catalog').onchange();};
$('capture').onclick=async()=>{
  if(!renderer)return;const url=window.previewScreenshot();
  try{if(window.pywebview?.api?.save_png){const r=await window.pywebview.api.save_png(url);status(r.saved?'已保存当前三维视图：'+r.path:r.error||'已取消保存');}else{const a=document.createElement('a');a.download='变压器三维结构.png';a.href=url;a.click();status('已导出当前三维视图');}}
  catch(e){status('图片保存失败：'+e.message);}
};
try{init();window.previewReady=true;}catch(e){failure('无法初始化三维显示：'+e.message);}
window.previewScreenshot=()=>{resizeViewport();renderer.render(scene,camera);return renderer.domElement.toDataURL('image/png');};
// Read-only diagnostics for automated integration checks.
window.previewDiagnostics=(options={})=>{
  const bounds=new THREE.Box3();for(const part of state.coreParts)bounds.expandByObject(part);
  const windingBounds=new THREE.Box3();for(const group of state.sectionGroups)windingBounds.expandByObject(group);
  const result={ready:!!renderer,coreParts:state.coreParts.length,layers:state.sectionGroups.length,triangles:renderer?.info.render.triangles,drawCalls:renderer?.info.render.calls,renderedBundleCount:(state.payload?.windings||[]).reduce((n,w)=>n+w.sections.reduce((s,l)=>s+l.turns.length,0),0),displayedCoreModel:state.payload?.core?.model,meshBacked:state.payload?.core_mesh?.schema==='power-core-mesh.v1',meshModel:state.payload?.core_mesh?.model,meshSchema:state.payload?.core_mesh?.schema,camera:camera?.position.toArray(),projection:camera?.isOrthographicCamera?'orthographic':'perspective',visibleLayers:state.sectionGroups.filter(g=>g.visible).length,coreOpacity:Number($('opacity').value)/100,explode:Number($('explode').value)/100,coreBounds:bounds.isEmpty()?null:{min:bounds.min.toArray(),max:bounds.max.toArray(),size:bounds.getSize(new THREE.Vector3()).toArray()},windingBounds:windingBounds.isEmpty()?null:{min:windingBounds.min.toArray(),max:windingBounds.max.toArray()},fatal:$('fatal').hidden?null:$('fatal').textContent,mode:state.mode,displayOnly:state.displayOnly,signature:state.design?.signature};
  if(options.parts)result.parts=state.coreParts.map(part=>{const b=new THREE.Box3().setFromObject(part);return{role:part.userData.role,half:part.userData.half,visible:part.visible,min:b.min.toArray(),max:b.max.toArray()};});
  const paths=state.windingPaths;
  result.crossovers=state.crossovers.length;
  result.visibleCrossovers=state.crossovers.filter(m=>m.visible).length;
  if(paths){
    result.conductorTracks=paths.tracks.length;
    result.localLiftMax_mm=paths.tracks.reduce((n,t)=>t.samples.reduce((m,s)=>Math.max(m,s.lift),n),0);
    result.connectionKinds=paths.links.map(link=>link.connection.kind);
    if(options.paths){
      result.conductorPaths=paths.tracks.map(t=>({section:t.section.id,winding:t.winding.id,track:t.key,
        turnIds:t.turns.map(turn=>turn.id),phase:t.phase,start_mm:t.samples[0].point,end_mm:t.samples.at(-1).point,
        liftMax_mm:t.samples.reduce((n,s)=>Math.max(n,s.lift),0)}));
      result.connections=paths.links.map(link=>({winding:link.winding.id,track:link.key,
        from:link.from.section.id,to:link.to.section.id,kind:link.connection.kind,
        start_mm:link.samples[0].point,end_mm:link.samples.at(-1).point,
        minimumZ_mm:link.samples.reduce((n,s)=>Math.min(n,s.point[2]),Infinity),
        pointCount:link.samples.length,
        endGap_mm:Math.max(new THREE.Vector3(...link.samples[0].point).distanceTo(new THREE.Vector3(...link.from.samples.at(-1).point)),
          new THREE.Vector3(...link.samples.at(-1).point).distanceTo(new THREE.Vector3(...link.to.samples[0].point)))}));
    }
  }
  return result;
};
