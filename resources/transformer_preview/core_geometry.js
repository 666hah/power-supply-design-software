import * as THREE from 'three';

// Build-time geometry only: no DOM, camera, material, or electrical inputs.
// The viewer consumes the serialized output of this module from the built-in
// mesh library, rather than inventing a shape at first use.
const RESOLUTION = 96;

function polygon(points) {
  if (!Array.isArray(points) || points.length < 3) throw new Error('磁芯截面轮廓少于三个点');
  const shape = new THREE.Shape();
  points.forEach((p, i) => {
    if (p.length !== 2 || !p.every(Number.isFinite)) throw new Error('磁芯轮廓坐标无效');
    if (i === 0) shape.moveTo(p[0], p[1]); else shape.lineTo(p[0], p[1]);
  });
  shape.closePath();
  return shape;
}

function circle(radius, hole = 0) {
  if (!(radius > hole && hole >= 0)) throw new Error('磁芯圆截面直径无效');
  const shape = new THREE.Shape();
  shape.absarc(0, 0, radius, 0, Math.PI * 2, false);
  if (hole) {
    const path = new THREE.Path();
    path.absarc(0, 0, hole, 0, Math.PI * 2, true);
    shape.holes.push(path);
  }
  return shape;
}

function extrude(shape, height) {
  if (!(height > 0)) throw new Error('磁芯挤出高度无效');
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: height, steps: 1, bevelEnabled: false, curveSegments: RESOLUTION / 2,
  });
  geometry.translate(0, 0, -height / 2);
  return geometry;
}

function box(width, depth, height) {
  if (![width, depth, height].every(x => x > 0 && Number.isFinite(x))) throw new Error('磁芯矩形尺寸无效');
  return new THREE.BoxGeometry(width, depth, height);
}

function racetrack(width, depth) {
  const r = Math.min(width, depth) / 2;
  const shape = new THREE.Shape();
  if (width >= depth) {
    shape.absarc(width / 2 - r, 0, r, -Math.PI / 2, Math.PI / 2, false);
    shape.absarc(-width / 2 + r, 0, r, Math.PI / 2, 3 * Math.PI / 2, false);
  } else {
    shape.absarc(0, depth / 2 - r, r, 0, Math.PI, false);
    shape.absarc(0, -depth / 2 + r, r, Math.PI, 2 * Math.PI, false);
  }
  shape.closePath();
  return shape;
}

function withHoles(shape, holes) {
  for (const points of holes || []) {
    const hole = new THREE.Path();
    points.forEach((p, i) => i ? hole.lineTo(...p) : hole.moveTo(...p));
    hole.closePath();
    shape.holes.push(hole);
  }
  return shape;
}

/** @returns {{id:string,name:string,role:string,half:number,position_mm:number[],geometry:THREE.BufferGeometry}[]} */
export function generateCoreParts(record) {
  const d = record.dimensions_mm;
  if (!d || record.status === 'dimensions_pending') throw new Error(`${record.model} 尚无已核对的外形尺寸`);
  const parts = [];
  const add = (geometry, position, half, role, name) => {
    parts.push({ id: `${role}_${half}_${parts.length + 1}`, name, role, half, position_mm: position, geometry });
  };
  const t = record.template;
  if (t === 'toroid') {
    add(extrude(circle(d.outer_diameter / 2, d.inner_diameter / 2), d.height), [0, 0, 0], 0, 'body', '环形磁芯');
    return parts;
  }
  const W = d.width, D = d.depth, H = d.half_height, wh = d.window_height, plate = H - wh;
  if (!(W > 0 && D > 0 && plate > 0 && wh > 0)) throw new Error(`${record.model} 的半芯尺寸不完整`);
  const profile = record.shape_profile;
  if (['pq', 'rm', 'ep', 'efd', 'epc', 'pot', 'e_round'].includes(t) && !profile) {
    throw new Error(`${record.model} 尚未录入三视图轮廓；不使用通用外形代替`);
  }
  const yoke = () => {
    if (profile) return extrude(withHoles(polygon(profile.yoke_xy_mm), profile.yoke_holes_xy_mm), plate);
    return box(W, D, plate);
  };
  const center = height => {
    if (profile?.center_xy_mm) return extrude(withHoles(polygon(profile.center_xy_mm), profile.center_holes_xy_mm), height);
    if (d.center_diameter) return extrude(circle(d.center_diameter / 2, (d.hole_diameter || 0) / 2), height);
    if (t === 'epc') return extrude(racetrack(d.center_width, d.center_depth), height);
    return box(d.center_width, d.center_depth, height);
  };
  const appendHalf = sign => {
    add(yoke(), [0, 0, sign * (wh + plate / 2)], sign, 'yoke', '磁芯底轭');
    if (profile) {
      for (const [index, points] of profile.returns_xy_mm.entries()) {
        const shape = withHoles(polygon(points), profile.returns_holes_xy_mm?.[index]);
        add(extrude(shape, wh), [0, 0, sign * wh / 2], sign, 'return', '磁芯外柱');
      }
    } else {
      if (!(d.outer_leg_width > 0)) throw new Error(`${record.model} 缺少外柱宽度`);
      for (const x of [-W / 2 + d.outer_leg_width / 2, W / 2 - d.outer_leg_width / 2]) {
        add(box(d.outer_leg_width, D, wh), [x, 0, sign * wh / 2], sign, 'return', t === 'u' ? 'U 磁芯柱' : '磁芯外柱');
      }
    }
    if (t !== 'u') {
      const offset = profile?.center_offset_xy_mm || [d.center_offset_x || 0, d.center_offset_y || 0];
      add(center(wh), [...offset, sign * wh / 2], sign, 'center', '磁芯中柱');
    }
  };
  if (t === 'ei_rect') {
    appendHalf(-1);
    add(box(W, D, d.i_height), [0, 0, d.i_height / 2], 1, 'yoke', 'I 磁芯');
  } else {
    appendHalf(-1);
    appendHalf(1);
  }
  return parts;
}
