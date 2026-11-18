"""Extract EPC model-specific profiles from TDK orthographic vector drawings.

Developer tool; original PDF is not distributed. Unspecified corner transitions
are drawing-derived preview geometry, not a production tolerance specification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pymupdf

from extract_tdk_pq_profiles import path_points

PAGES = {"EPC13": 9, "EPC17": 12, "EPC25": 18}


def interpolate(value, source, target):
    sign = -1 if value < 0 else 1
    v = abs(value)
    for i in range(1, len(source)):
        if v <= source[i] + 1e-8:
            t = (v - source[i-1]) / (source[i] - source[i-1])
            return sign * (target[i-1] + t*(target[i]-target[i-1]))
    raise ValueError("PDF outline exceeds calibration anchors")


def racetrack(width, depth):
    radius = depth / 2
    points = []
    for center, start in ((width/2-radius, -math.pi/2), (-width/2+radius, math.pi/2)):
        points.extend([[center+radius*math.cos(start+i*math.pi/48), radius*math.sin(start+i*math.pi/48)] for i in range(49)])
    return points


def generate(pdf_path, catalog_path):
    pdf = pymupdf.open(pdf_path)
    rows = json.loads(catalog_path.read_text(encoding="utf-8"))["cores"]
    sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    result = {}
    for record in rows:
        model = record["model"]
        if model not in PAGES:
            continue
        page = PAGES[model]
        paths = pdf[page-1].get_drawings()
        left, right = (path_points(paths[i]["items"]) for i in (101,102))
        # First five items cover notch shoulder, round outer corners and side;
        # joining them across the bottom and lead notch yields the bottom yoke.
        outer_left = path_points(paths[101]["items"][:5])
        outer_right = path_points(paths[102]["items"][:5])
        yoke = outer_left + list(reversed(outer_right))
        u0, u1 = min(p[0] for p in left), max(p[0] for p in right)
        v0 = min(p[1] for p in left+right)
        v1 = max(p[1] for p in left+right)
        uc = (u0+u1)/2
        e = (right[0][0]-left[0][0])/2
        b = (paths[102]["items"][5][2].x-paths[101]["items"][5][2].x)/2
        d = record["dimensions_mm"]
        source = [0,e,b,(u1-u0)/2]
        target = [0,d["lead_opening"]/2,d["window_outer_width"]/2,d["width"]/2]
        if source != sorted(source) or target != sorted(target):
            raise ValueError(f"Non-monotonic horizontal dimensions in {model}")
        def transform(points):
            return [[round(interpolate(u-uc,source,target),6),
                     round((v1-v)*d["depth"]/(v1-v0)-d["center_depth"]/2,6)] for u,v in points]
        yoke_xy = transform(yoke)
        returns_xy = [transform(left), transform(right)]
        center_xy = [[round(x,6),round(y,6)] for x,y in racetrack(d["center_width"],d["center_depth"])]
        # Keep source closure offsets below print precision from changing F.
        for points in [yoke_xy,*returns_xy]:
            for point in points:
                if abs(point[1]+d["center_depth"]/2)<0.01:
                    point[1]=-d["center_depth"]/2
        result[model] = {
            "shape_profile": {"yoke_xy_mm":yoke_xy,"returns_xy_mm":returns_xy,
                              "center_xy_mm":center_xy,"center_offset_xy_mm":[0,0]},
            "shape_evidence": {
                "kind":"manufacturer_orthographic_vector",
                "source_url":record["source_url"], "source_page":page,
                "source_pdf_sha256":sha,"pdf_path_indices":[100,101,102],
                "pdf_contour_bbox_pt":[u0,v0,u1,v1],
                "pdf_axes_to_model":"X calibrated piecewise at A/E/B; Y=(v_bottom-v)*F/height-C2/2; origin at center post",
                "curve_samples_per_cubic":16,
                "construction":"逐型号三视图原始外柱曲线及引线凹口；A/F外包络、B/E最小开口逐项校准，C1×C2跑道中柱底边与底轭齐平；轴向厚度采用D、H。",
                "limits":"未标注圆角和过渡采用原图轮廓，仅作结构预览；不作为制造公差或场解CAD。"
            },
            "source_page":f"尺寸总表 {4 if model != 'EPC25' else 5}；本型号三视图 {page}",
            "dimension_mapping":"A→X宽；F→Y总深；B/E→外柱底部窗口/引线开口最小宽度；C1/C2→跑道中柱宽/深；D/H→半芯高/沟深。坐标原点在中柱中心，外包络沿Y偏心。",
            "notes":["按本型号三视图保留底轭凹口、曲线外柱及偏置跑道中柱；中柱原点与绕组路径一致。",
                     "A、F、C1、C2、D、H采用标称值，B与E采用图纸最小值；未标注过渡沿原图采样。",
                     "机械模型与电气材料、Ae、Ve独立；微小倒角、骨架与引脚未纳入制造几何。"]
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf",type=Path)
    parser.add_argument("--catalog",type=Path,default=Path("resources/core_shapes/catalog.json"))
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    rows=generate(args.pdf,args.catalog)
    args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"Extracted {len(rows)} EPC profiles")
