"""Build PQ plan contours from each part's TDK orthographic vector drawing.

Developer-only: requires PyMuPDF and Shapely, never used at application runtime. Source PDF
is intentionally not distributed; pass an independently downloaded TDK PDF.
Contours contain drawing-derived unannotated transitions, not production CAD.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pymupdf
from shapely.geometry import Polygon


# Page numbers are one based; path indices refer to PyMuPDF get_drawings().
DRAWINGS = {
    "PQ20-16": (6, [88, 90, 83, 85]),
    "PQ20-20": (9, [88, 90, 83, 85]),
    "PQ26-20": (12, [139, 140, 137, 138]),
    "PQ26-25": (15, [141, 142, 139, 140]),
    "PQ32-30": (21, [126, 127, 122, 124]),
    "PQ35-35": (24, [125, 127, 121, 123]),
    "PQ40-40": (27, [121, 122, 123, 125]),
    "PQ50-50": (30, [125, 127, 121, 123]),
}


def path_points(items):
    points = []
    for item in items:
        kind, *p = item
        if kind == "l":
            values = [tuple(p[0]), tuple(p[1])]
        elif kind == "c":
            values = []
            for j in range(17):
                t = j / 16
                values.append(tuple((1-t)**3*p[0][k] + 3*(1-t)**2*t*p[1][k]
                                    + 3*(1-t)*t*t*p[2][k] + t**3*p[3][k]
                                    for k in range(2)))
        else:
            raise ValueError(f"Unsupported drawing command {kind}")
        points.extend(values if not points else values[1:])
    return points


def concatenate(paths):
    """Order four perimeter pieces by adjacent endpoints, preserving curves."""
    result = paths.pop(0)
    while paths:
        candidates = [(math.dist(result[-1], p[0]), i, False) for i, p in enumerate(paths)]
        candidates += [(math.dist(result[-1], p[-1]), i, True) for i, p in enumerate(paths)]
        distance, index, reverse = min(candidates)
        if distance > 0.5:
            raise ValueError(f"Discontinuous plan perimeter: {distance} PDF points")
        p = paths.pop(index)
        result.extend(reversed(p) if reverse else p)
    if math.dist(result[0], result[-1]) > 0.5:
        raise ValueError("Open perimeter")
    return result


def circular_returns(poly, radius):
    """Intersect the two outer lobes with the exterior of the window circle.

    Each resulting pole shoe closes along the shorter circular window arc.
    Linear-segment intersections are solved analytically, no geometry package
    is needed in the catalogue build or the shipped application.
    """
    segments = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        delta = [b[i] - a[i] for i in range(2)]
        qa = sum(x*x for x in delta)
        if qa < 1e-14:
            continue
        qb = 2 * sum(a[i] * delta[i] for i in range(2))
        qc = sum(x*x for x in a) - radius*radius
        disc = qb*qb - 4*qa*qc
        ts = [0., 1.]
        if disc > 0:
            ts.extend(t for t in ((-qb-math.sqrt(disc))/(2*qa), (-qb+math.sqrt(disc))/(2*qa)) if 1e-9 < t < 1-1e-9)
        ts.sort()
        for ta, tb in zip(ts, ts[1:]):
            mid = [a[i] + (ta+tb)*0.5*delta[i] for i in range(2)]
            if sum(x*x for x in mid) > radius*radius:
                segments.append(([a[i]+ta*delta[i] for i in range(2)], [a[i]+tb*delta[i] for i in range(2)]))
    chains = []
    for a, b in segments:
        if chains and math.dist(chains[-1][-1], a) < 1e-6:
            chains[-1].append(b)
        else:
            chains.append([a, b])
    if len(chains) > 1 and math.dist(chains[-1][-1], chains[0][0]) < 1e-6:
        chains[0] = chains[-1] + chains[0][1:]
        chains.pop()
    if len(chains) != 2:
        raise ValueError(f"Expected two return poles; got {len(chains)}")
    for chain in chains:
        first = math.atan2(chain[-1][1], chain[-1][0])
        last = math.atan2(chain[0][1], chain[0][0])
        delta = (last-first+math.pi) % (2*math.pi)-math.pi
        count = max(16, math.ceil(abs(delta)*64))
        chain.extend([[radius*math.cos(first+delta*j/count), radius*math.sin(first+delta*j/count)] for j in range(1, count)])
    return chains


def rounded(points):
    return [[round(x, 6), round(y, 6)] for x, y in points]


def extract(pdf_path, catalog_path):
    pdf = pymupdf.open(pdf_path)
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    for row in catalog["cores"]:
        if row["model"] not in DRAWINGS:
            continue
        page_number, indices = DRAWINGS[row["model"]]
        paths = pdf[page_number-1].get_drawings()
        raw = concatenate([path_points(paths[i]["items"]) for i in indices])
        u0, u1 = min(p[0] for p in raw), max(p[0] for p in raw)
        v0, v1 = min(p[1] for p in raw), max(p[1] for p in raw)
        dims = row["dimensions_mm"]
        sx, sy = dims["width"]/(v1-v0), dims["depth"]/(u1-u0)
        poly = [[((v0+v1)/2-v)*sx, (u-(u0+u1)/2)*sy] for u, v in raw]
        # Printed strokes are independent paths: some endpoints overlap by a
        # fraction of the drawing line width. Remove only those microscopic
        # closed slivers before tessellation, with an explicit bounded audit.
        original = Polygon(poly)
        healed = original if original.is_valid else original.buffer(0)
        area_change = abs(healed.area-original.area)
        if healed.geom_type != 'Polygon' or area_change > original.area*1e-5:
            raise ValueError(f"{row['model']}: contour junction repair too large")
        poly = list(healed.exterior.coords)[:-1]
        returns = circular_returns(poly, dims["window_diameter"]/2)
        row["shape_profile"] = {
            "yoke_xy_mm": rounded(poly),
            "returns_xy_mm": [rounded(p) for p in returns],
        }
        row["shape_evidence"] = {
            "kind": "manufacturer_orthographic_vector",
            "source_url": row["source_url"],
            "source_pdf_sha256": sha,
            "source_page": page_number,
            "pdf_path_indices": indices,
            "pdf_contour_bbox_pt": [round(v, 6) for v in (u0, v0, u1, v1)],
            "pdf_axes_to_model": "X=(v_center-v)*scale_x; Y=(u-u_center)*scale_y",
            "scale_x_mm_per_pt": sx,
            "scale_y_mm_per_pt": sy,
            "curve_samples_per_cubic": 16,
            "junction_repair_area_mm2": area_change,
            "construction": "按本型号俯视矢量外轮廓形成收腰底轭；底轭投影减B直径窗口圆形成两个外柱；C直径中央圆柱。底轭厚=(2D-2H)/2，外柱高=2H/2。",
            "limits": "总宽/深、柱径、窗口径及轴向尺寸采用标称尺寸；未标注的轮廓转折/圆角沿该型号原图采样，属于图示约束，不作为制造公差或场解CAD。",
        }
        row["source_page"] = f"尺寸总表 {2 if page_number <= 15 else 3}；本型号三视图 {page_number}"
        row["dimension_mapping"] = "A1/A2→X宽/Y深；B→窗口圆直径；C→中心柱径；2D/2→半芯高；E最小值→X向外侧引线口肩间距；2H/2→半芯沟深。"
        row["notes"] = [
            "底轭使用本型号三视图的收腰轮廓，中央裸露圆弧与两侧引线口保留；不使用通用八边形包络。",
            "未标注的过渡轮廓由原图采样；微小倒角、夹具、骨架及引脚未作为精密制造几何。",
            "机械模型与工程材料、Ae、Ve及气隙独立；电磁提取使用联合仿真配置的CAD。",
        ]
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Extracted {len(DRAWINGS)} independent TDK PQ plan contours")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--catalog", type=Path, default=Path("resources/core_shapes/catalog.json"))
    args = parser.parse_args()
    extract(args.pdf, args.catalog)
