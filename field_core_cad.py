"""Closed nominal ferrite CAD derived from the 3D preview's mechanical catalog."""
import math
from pathlib import Path

from core_shape_catalog import get_core_shape


# The preview source samples vector Bezier curves densely. OCC reference faces
# need a moderate contour resolution to avoid sub-micrometre polygon edges.
OUTLINE_TOLERANCE_MM = .025


def catalog_field_core(name):
    """Return a reference solid definition for a centered round middle leg."""
    core = get_core_shape(name)
    if not core or core['status'] not in ('datasheet_nominal', 'reference_variant'):
        return None
    if core['template'] not in ('pq', 'rm', 'e_round', 'pot'):
        return None
    dimensions = core.get('dimensions_mm') or {}
    profile = core.get('shape_profile') or {}
    offset = profile.get('center_offset_xy_mm') or [dimensions.get('center_offset_x', 0), dimensions.get('center_offset_y', 0)]
    radius = dimensions.get('center_diameter', 0) / 2
    hole = dimensions.get('hole_diameter', 0) / 2
    if (not profile.get('yoke_xy_mm') or not profile.get('returns_xy_mm') or profile.get('center_xy_mm')
            or any(offset) or radius <= hole or not 0 < dimensions.get('window_height', 0) < dimensions.get('half_height', 0)):
        return None
    return core


def _wire(occ, contour, z):
    # Source paths sampled from vector drawings can contain duplicate endpoints.
    points = []
    for point in contour:
        if not points or max(abs(a - b) for a, b in zip(point, points[-1])) > 1e-6:
            points.append(point)
    if max(abs(a - b) for a, b in zip(points[0], points[-1])) <= 1e-6:
        points.pop()
    tags = [occ.addPoint(x, y, z) for x, y in points]
    return occ.addWire([occ.addLine(start, end) for start, end in zip(tags, tags[1:] + tags[:1])], checkClosed=True)


def _outline(contour):
    """Bound chord deviation from the reference contour without moving its vertices."""
    points = [tuple(point) for point in contour]
    if points[0] == points[-1]:
        points.pop()
    second = max(range(1, len(points)), key=lambda index: math.dist(points[0], points[index]))

    def simplify(path):
        a, b = path[0], path[-1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx*dx + dy*dy
        if len(path) < 3 or not length_sq:
            return path
        def distance(point):
            amount = min(1., max(0., ((point[0]-a[0])*dx + (point[1]-a[1])*dy) / length_sq))
            return math.dist(point, (a[0]+amount*dx, a[1]+amount*dy))
        far = max(range(1, len(path)-1), key=lambda index: distance(path[index]))
        if distance(path[far]) <= OUTLINE_TOLERANCE_MM:
            return [a, b]
        return simplify(path[:far+1])[:-1] + simplify(path[far:])

    result = simplify(points[:second+1])[:-1] + simplify(points[second:] + [points[0]])[:-1]
    return result if len(result) >= 3 else points


def _extrusion(occ, contour, holes, z, height):
    surface = occ.addPlaneSurface([_wire(occ, p, z) for p in (contour, *holes)])
    return next(entity for entity in occ.extrude([(2, surface)], 0, 0, height) if entity[0] == 3)


def write_catalog_core(name, destination, *, gap_mm, spacer=False):
    """Build assembled nominal OCC ferrite in mm, centered on the mating plane."""
    import gmsh

    core = catalog_field_core(name)
    if core is None:
        raise ValueError('该磁芯暂无可自动生成实体的三视图和圆中柱尺寸，请选择已有磁芯实体')
    profile = core['shape_profile']
    dim = core['dimensions_mm']
    height, window, radius = dim['half_height'], dim['window_height'], dim['center_diameter'] / 2
    if not 0 <= gap_mm < 2 * window:
        raise ValueError('气隙必须小于中柱两端之间的机械窗口高度')
    gmsh.initialize(['field-core-cad', '-nopopup'])
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add('nominal-ferrite')
        occ = gmsh.model.occ
        shift = gap_mm / 2 if spacer else 0.
        yoke_holes = [_outline(points) for points in profile.get('yoke_holes_xy_mm') or []]
        yoke_outline = _outline(profile['yoke_xy_mm'])
        yokes = [_extrusion(occ, yoke_outline, yoke_holes, z, height-window)
                 for z in (-height-shift, window+shift)]
        leg_holes = profile.get('returns_holes_xy_mm') or [[] for _ in profile['returns_xy_mm']]
        leg_z_height = [(-window-shift, window), (shift, window)] if shift else [(-window, 2*window)]
        legs = [_extrusion(occ, _outline(contour), [_outline(points) for points in holes or []], z, length)
                for contour, holes in zip(profile['returns_xy_mm'], leg_holes, strict=True)
                for z, length in leg_z_height]
        center_length = window if spacer else window-gap_mm/2
        center = []
        for z in (-window-shift, gap_mm/2):
            volume = [(3, occ.addCylinder(0, 0, z, 0, 0, center_length, radius))]
            if dim.get('hole_diameter'):
                cut = occ.addCylinder(0, 0, z, 0, 0, center_length, dim['hole_diameter'] / 2)
                volume, _ = occ.cut(volume, [(3, cut)])
            center.extend(volume)
        solids, _ = occ.fuse(yokes[:1], yokes[1:] + legs + center)
        solids = [entity for entity in solids if entity[0] == 3]
        occ.synchronize()
        expected = 2 if shift else 1
        if (len(solids) != expected or any(occ.getMass(*entity) <= 0 for entity in solids)
                or set(gmsh.model.getEntities(3)) != set(solids)):
            raise ValueError('三视图标称外形无法生成有效装配实体，请使用登记的磁芯实体')
        from transformer_field_runtime.meshing import remove_unused
        remove_unused()
        gmsh.write(str(Path(destination).resolve()))
    finally:
        gmsh.finalize()
