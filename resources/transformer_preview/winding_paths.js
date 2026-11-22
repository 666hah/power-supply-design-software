/** Read-only conductor paths in millimetres. No electrical input is modified. */
const TAU = 2 * Math.PI;
const add = (a, b) => a.map((v, i) => v + b[i]);
const sub = (a, b) => a.map((v, i) => v - b[i]);
const times = (a, n) => a.map(v => v * n);
const distance = (a, b) => Math.hypot(...sub(a, b));
const unit = a => times(a, 1 / (Math.hypot(...a) || 1));
const blend = (a, b, f) => a.map((v, i) => v * (1 - f) + b[i] * f);
const angularDistance = (a, b) => Math.abs(Math.atan2(Math.sin(a - b), Math.cos(a - b)));

function roundedRectPoints(info) {
  const w = info.width_mm, h = info.height_mm;
  const r = Math.min(info.corner_radius_mm || 0, w / 2, h / 2);
  const center = info.center_xy_mm || [0, 0], points = [];
  if (!(w > 0 && h > 0)) throw Error('矩形骨架路径尺寸无效');
  for (let corner = 0; corner < 4; corner++) {
    const angle = corner * Math.PI / 2;
    const x = (corner === 0 || corner === 3 ? 1 : -1) * (w / 2 - r);
    const y = (corner < 2 ? 1 : -1) * (h / 2 - r);
    for (let j = 0; j <= 16; j++) {
      const theta = angle + j * Math.PI / 32;
      points.push([center[0] + x + r * Math.cos(theta), center[1] + y + r * Math.sin(theta)]);
    }
  }
  return points;
}

export function makeRoute(placement) {
  if (placement.route_type === 'circular') {
    return (theta, v) => {
      const radius = placement.r0_mm + v;
      return [radius * Math.cos(theta), radius * Math.sin(theta), Math.cos(theta), Math.sin(theta)];
    };
  }
  let path = placement.route_type === 'rounded_rectangle'
    ? roundedRectPoints(placement.rounded_rectangle_mm) : placement.path_xy_mm;
  if (!path || path.length < 3) throw Error('绕组需要已配置的闭合骨架路径');
  path = path.map(p => [...p]);
  if (distance(path[0], path.at(-1)) < 1e-10) path.pop();
  const area = path.reduce((sum, p, i) => {
    const q = path[(i + 1) % path.length];
    return sum + p[0] * q[1] - q[0] * p[1];
  }, 0);
  if (area < 0) path.reverse();
  const normals = path.map((p, i) => {
    const a = path[(i + path.length - 1) % path.length], b = path[(i + 1) % path.length];
    return unit([b[1] - a[1], a[0] - b[0]]);
  });
  const lengths = [0];
  for (let i = 0; i < path.length; i++) {
    lengths.push(lengths.at(-1) + distance(path[i], path[(i + 1) % path.length]));
  }
  return (theta, v) => {
    const target = (((theta / TAU) % 1 + 1) % 1) * lengths.at(-1);
    let i = 0;
    while (i < path.length - 1 && lengths[i + 1] < target) i++;
    const j = (i + 1) % path.length;
    const f = (target - lengths[i]) / (lengths[i + 1] - lengths[i] || 1);
    const normal = unit(blend(normals[i], normals[j], f)), p = blend(path[i], path[j], f);
    return [p[0] + normal[0] * v, p[1] + normal[1] * v, ...normal];
  };
}

function insidePolygon(point, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j];
    if ((a[1] > point[1]) !== (b[1] > point[1]) &&
        point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside;
}

function openingPhase(payload, route, index) {
  const polygons = payload.core?.shape_profile?.returns_xy_mm || [];
  const all = (payload.windings || []).flatMap(w => w.sections.flatMap(s => s.turns));
  const low = Math.min(...all.map(t => t.center_mm[1]));
  const high = Math.max(...all.map(t => t.center_mm[1] + t.height_mm));
  const clear = theta => {
    for (let i = 0; i <= 8; i++) {
      const p = route(theta, low + (high - low) * i / 8);
      if (polygons.some(polygon => insidePolygon(p, polygon))) return false;
    }
    return true;
  };
  // Prefer the front pin opening. Confirm the radial corridor against the
  // actual outer-leg polygons instead of assuming every core opens at ±Y.
  const base = [-Math.PI / 2, Math.PI / 2, 0, Math.PI,
    -Math.PI / 4, -3 * Math.PI / 4, Math.PI / 4, 3 * Math.PI / 4].find(clear) ?? -Math.PI / 2;
  const offset = (Math.ceil(index / 2)) * .18 * (index % 2 ? 1 : -1);
  return clear(base + offset) ? base + offset : base;
}

function groupedTracks(section) {
  const tracks = new Map();
  for (const turn of section.turns) {
    const key = `${turn.wire_index || 1}/${turn.sub_bundle_index || turn.bundle_index || 1}`;
    if (!tracks.has(key)) tracks.set(key, []);
    tracks.get(key).push(turn);
  }
  for (const turns of tracks.values()) {
    turns.sort((a, b) => a.turn_index - b.turn_index);
    if (section.axial_start === 'upper') turns.reverse();
  }
  return tracks;
}

function localLift(track, theta, u, obstacles, bins) {
  const shifts = new Map();
  const normalized = ((theta % TAU) + TAU) % TAU;
  const candidates = bins ? bins[Math.floor(normalized / TAU * bins.length) % bins.length] : obstacles;
  for (const obstacle of candidates) {
    if (track.section.layer_index <= obstacle.layer) continue;
    const delta = angularDistance(theta, obstacle.phase);
    if (delta >= obstacle.angularWidth) continue;
    const axialGap = Math.max(obstacle.lower - u, u - obstacle.upper, 0);
    const axialWeight = Math.max(0, 1 - axialGap / obstacle.axialFade);
    const shift = obstacle.shift * Math.cos(delta / obstacle.angularWidth * Math.PI / 2) ** 2 * axialWeight;
    shifts.set(obstacle.layer, Math.max(shifts.get(obstacle.layer) || 0, shift));
  }
  // Every outer layer follows the same insertion offset. Separate insertion
  // layers add; parallel conductors in one insertion layer share the maximum.
  let total = 0;
  for (const shift of shifts.values()) total += shift;
  return total;
}

function liftBins(obstacles) {
  const bins = Array.from({length: 128}, () => []), halfBin = Math.PI / bins.length;
  for (const obstacle of obstacles) {
    for (let i = 0; i < bins.length; i++) {
      if (angularDistance((i + .5) / bins.length * TAU, obstacle.phase) < obstacle.angularWidth + halfBin) {
        bins[i].push(obstacle);
      }
    }
  }
  return bins;
}

function trackSamples(track, placement, route, steps, obstacles, bins) {
  const samples = [], turns = track.turns, direction = track.section.direction === 'cw' ? -1 : 1;
  for (let i = 0; i < turns.length; i++) {
    const turn = turns[i], a = turn.center_mm;
    const b = turns[Math.max(0, i - 1)].center_mm;
    const c = turns[Math.min(turns.length - 1, i + 1)].center_mm;
    for (let j = i ? 1 : 0; j <= steps; j++) {
      const f = j / steps;
      const u = f <= .5 ? (b[0] + a[0]) / 2 + (a[0] - b[0]) * f : a[0] + (c[0] - a[0]) * (f - .5);
      const v = f <= .5 ? (b[1] + a[1]) / 2 + (a[1] - b[1]) * f : a[1] + (c[1] - a[1]) * (f - .5);
      const theta = track.phase + direction * TAU * f;
      const lift = localLift(track, theta, u, obstacles, bins);
      const [x, y, nx, ny] = route(theta, v + lift);
      samples.push({point: [x, y, (placement.z0_mm || 0) + u], normal: [nx, ny, 0],
        width: turn.width_mm, height: turn.height_mm, lift});
    }
  }
  return samples;
}

/** Round only within each corner's incident segments, with no spline overshoot. */
function roundPolyline(points, radius) {
  const raw = points.filter((p, i) => !i || distance(p, points[i - 1]) > 1e-7);
  if (raw.length < 2) return raw;
  const result = [raw[0]];
  for (let i = 1; i < raw.length - 1; i++) {
    const p = raw[i], a = raw[i - 1], b = raw[i + 1];
    const trim = Math.min(radius, distance(a, p) * .32, distance(p, b) * .32);
    const begin = add(p, times(unit(sub(a, p)), trim));
    const end = add(p, times(unit(sub(b, p)), trim));
    result.push(begin);
    for (let j = 1; j <= 8; j++) {
      const f = j / 8;
      result.push(add(add(times(begin, (1 - f) ** 2), times(p, 2 * f * (1 - f))), times(end, f ** 2)));
    }
  }
  result.push(raw.at(-1));
  return result;
}

function connectionSamples(link, from, to, route, placement) {
  const start = from.samples.at(-1), finish = to.samples[0];
  const width = Math.max(start.width, finish.width), height = Math.max(start.height, finish.height);
  const reach = Math.max(width * .6, height * .8, .18);
  const tangentOut = unit(sub(start.point, from.samples.at(-2).point));
  const tangentIn = unit(sub(to.samples[1].point, finish.point));
  let points;
  if (link.connection.kind === 'declared') {
    const via = link.connection.path_xyz_mm;
    if (!via?.length || via.some(p => p.length !== 3 || !p.every(Number.isFinite))) {
      throw Error(`已声明的层间引线 ${link.connection.node || ''} 缺少有效毫米坐标`);
    }
    points = [start.point, ...via, finish.point];
  } else if (link.connection.kind === 'pin_return') {
    const obstacle = link.obstacle, phase = from.phase;
    const [x, y] = route(phase, obstacle.v);
    const targetV = to.turns[0].center_mm[1] + finish.lift;
    const [tx, ty] = route(to.phase, targetV);
    const lowZ = (placement.z0_mm || 0) + obstacle.lower;
    points = [start.point, add(start.point, times(tangentOut, reach)),
      [x, y, start.point[2]], [x, y, lowZ], [tx, ty, lowZ],
      sub(finish.point, times(tangentIn, reach)), finish.point];
  } else {
    points = [start.point, add(start.point, times(tangentOut, reach)),
      sub(finish.point, times(tangentIn, reach)), finish.point];
  }
  const rounded = roundPolyline(points, reach * .75), result = [];
  for (let i = 0; i < rounded.length - 1; i++) {
    const steps = Math.max(1, Math.ceil(distance(rounded[i], rounded[i + 1]) / .35));
    for (let j = i ? 1 : 0; j <= steps; j++) {
      const f = j / steps, point = blend(rounded[i], rounded[i + 1], f);
      const normal = unit(blend(start.normal, finish.normal, (i + f) / (rounded.length - 1)));
      result.push({point, normal, width, height, lift: 0});
    }
  }
  return result;
}

export function buildWindingPaths(payload, steps = 64) {
  const placement = payload.placement, route = makeRoute(placement);
  const tracks = [], trackMap = new Map(), links = [], obstacles = [], notes = [];
  for (const [index, winding] of payload.windings.entries()) {
    const phase = openingPhase(payload, route, index);
    const keys = [...new Set(winding.sections.flatMap(section => [...groupedTracks(section).keys()]))].sort();
    for (const section of winding.sections) {
      for (const [key, turns] of groupedTracks(section)) {
        const track = {section, key, winding, turns,
          phase: phase + (keys.indexOf(key) - (keys.length - 1) / 2) * Math.min(.1, .6 / keys.length)};
        tracks.push(track);
        trackMap.set(`${winding.id}:${section.id}:${key}`, track);
      }
    }
    for (const connection of winding.crossovers || []) {
      for (const key of keys) {
        const from = trackMap.get(`${winding.id}:${connection.from_section}:${key}`);
        const to = trackMap.get(`${winding.id}:${connection.to_section}:${key}`);
        if (!from || !to) { notes.push(`${winding.name || winding.id} 的 ${key} 路线束缺少配对层，保留独立显示。`); continue; }
        links.push({connection, from, to, winding, key});
      }
    }
  }
  links.sort((a, b) => a.from.section.layer_index - b.from.section.layer_index);
  const sectionsByLayer = new Map(tracks.map(track => [track.section.layer_index, track.section]));
  const layerNumbers = [...sectionsByLayer.keys()].sort((a, b) => a - b);
  for (const link of links) {
    if (link.connection.kind !== 'pin_return') continue;
    const from = link.from, end = from.turns.at(-1);
    const u = end.center_mm[0], v = end.center_mm[1];
    const priorLift = localLift(from, from.phase, u, obstacles);
    const height = end.height_mm;
    const nextLayer = layerNumbers.find(layer => layer > from.section.layer_index);
    const above = sectionsByLayer.get(nextLayer)?.turns || [];
    const sourceTop = Math.max(...from.section.turns.map(t => t.center_mm[1] + t.height_mm / 2));
    const existingGap = above.length ? Math.min(...above.map(t => t.center_mm[1] - t.height_mm / 2)) - sourceTop : height;
    const [x, y] = route(from.phase, v);
    const maxWidth = Math.max(end.width_mm, ...above.map(t => t.width_mm));
    const obstacle = {layer: from.section.layer_index, phase: from.phase, width: end.width_mm, height,
      shift: Math.max(0, height + .08 - existingGap),
      angularWidth: Math.max(.08, (maxWidth + end.width_mm) * .85 / Math.max(Math.hypot(x, y), 1)),
      axialFade: Math.max(maxWidth, .1),
      v: v + priorLift + height + .04, lower: -Math.max(end.width_mm * .65, .2), upper: u};
    link.obstacle = obstacle;
    obstacles.push(obstacle);
  }
  const bins = liftBins(obstacles);
  for (const track of tracks) track.samples = trackSamples(track, placement, route, steps, obstacles, bins);
  for (const link of links) link.samples = connectionSamples(link, link.from, link.to, route, placement);
  return {tracks, links, obstacles, notes};
}
