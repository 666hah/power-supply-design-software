"""Build the two non-TDK PQ references from their own manufacturer drawings.

All coordinates below are millimetres. The unlabelled shoulder transitions are
digitised from the named projection; they are recorded as drawing-derived,
not as dimensioned production surfaces. No neighbouring TDK contour is reused.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from extract_tdk_pq_profiles import circular_returns, rounded


def waist_outline(width, depth, radius, neck_half_width, shoulder_x, shoulder_y,
                  external_radius=0.0):
    """Two lobe perimeter, top/bottom circular centre-pole exposed segments."""
    nx = neck_half_width
    ny = math.sqrt(radius*radius - nx*nx)
    theta = math.atan2(ny, nx)
    # Start upper left inner shoulder; move around top of central cylinder.
    points = [[-shoulder_x, depth/2], [-shoulder_x, shoulder_y], [-nx, ny]]
    points += [[radius*math.cos(math.pi-theta-(math.pi-2*theta)*j/32),
                radius*math.sin(math.pi-theta-(math.pi-2*theta)*j/32)] for j in range(1,33)]
    points += [[shoulder_x, shoulder_y], [shoulder_x, depth/2], [width/2-external_radius, depth/2]]
    if external_radius:
        points += [[width/2-external_radius+external_radius*math.cos(math.pi/2-j*math.pi/32),
                    depth/2-external_radius+external_radius*math.sin(math.pi/2-j*math.pi/32)] for j in range(1,17)]
    else:
        points.append([width/2,depth/2])
    points.append([width/2,-depth/2+external_radius])
    if external_radius:
        points += [[width/2-external_radius+external_radius*math.cos(-j*math.pi/32),
                    -depth/2+external_radius+external_radius*math.sin(-j*math.pi/32)] for j in range(1,17)]
    else:
        points.append([width/2,-depth/2])
    points += [[shoulder_x,-depth/2], [shoulder_x,-shoulder_y], [nx,-ny]]
    points += [[radius*math.cos(-theta-(math.pi-2*theta)*j/32),
                radius*math.sin(-theta-(math.pi-2*theta)*j/32)] for j in range(1,33)]
    points += [[-shoulder_x,-shoulder_y], [-shoulder_x,-depth/2], [-width/2+external_radius,-depth/2]]
    if external_radius:
        points += [[-width/2+external_radius+external_radius*math.cos(-math.pi/2-j*math.pi/32),
                    -depth/2+external_radius+external_radius*math.sin(-math.pi/2-j*math.pi/32)] for j in range(1,17)]
    else:
        points.append([-width/2,-depth/2])
    points.append([-width/2,depth/2-external_radius])
    if external_radius:
        points += [[-width/2+external_radius+external_radius*math.cos(math.pi-j*math.pi/32),
                    depth/2-external_radius+external_radius*math.sin(math.pi-j*math.pi/32)] for j in range(1,17)]
    else:
        points.append([-width/2,depth/2])
    return points


def apply(catalog_path=Path("resources/core_shapes/catalog.json")):
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_model = {row["model"]: row for row in data["cores"]}
    row = by_model["PQ32-25"]
    row.update(manufacturer="DMEGC 东磁", reference_model="PQ32/25",
               source_url="https://irp.cdn-website.com/eb58f5fe/files/uploaded/PQ_CORES.pdf",
               source_page="15", source_revision="旧版 PQ 系列原厂目录，未标日期",
               source_host_kind="manufacturer_authored_mirror")
    d = row["dimensions_mm"]
    d.update(width=32., depth=22., half_height=12.5, window_height=8.1,
             center_width=13.45, center_depth=13.45, center_diameter=13.45,
             window_outer_width=27.5, window_diameter=27.5,
             outer_leg_width=2.25, lead_opening=19.75)
    row["drawing_dimensions_mm"] = {"width":32.,"depth":22.,"half_height":12.5,
        "window_half_height":8.1,"window_diameter":27.5,"center_diameter":13.45,
        "lead_opening_min":19.75,"neck_outer_width":6.8,"neck_inner_width":5.2,
        "reference_shoulder_depth":19.,"outer_corner_radius":0.5,
        "shoulder_radius":0.8,"local_edge_radius":0.2}
    row["dimension_mapping"] = "东磁PQ32/25半芯：外宽32、深22、高12.5、沟深8.1；中心柱Φ13.45、窗口Φ27.5；X向引线口最小肩距19.75。"
    poly = waist_outline(32.,22.,6.725,3.4,9.875,9.5,0.5)
    row["shape_profile"] = {"yoke_xy_mm":rounded(poly),
                            "returns_xy_mm":[rounded(p) for p in circular_returns(poly,13.75)]}
    pdf = Path("artifacts/core-shape-catalog-20261115/dmegc-pq-legacy.pdf")
    row["shape_evidence"] = {
        "kind":"manufacturer_orthographic_dimensioned_raster",
        "source_url":row["source_url"], "source_page":15,
        "source_pdf_sha256":hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.exists() else "",
        "source_host_kind":"manufacturer_authored_mirror",
        "source_figure":"PQ32/25 正视图与俯视图；原厂图为嵌入位图",
        "pdf_figure_bbox_pt":[356.4,108.6,562.4,379.3],
        "construction":"按32×22外廓、Φ13.45中央柱、Φ27.5窗口、19.75最小肩距和6.8颈宽重建收腰；原图(19)深度约束斜边肩位置；两个极靴为底轭外廓减窗口圆。",
        "limits":"未独立展开5.2/6.8颈部之间的局部过渡、R0.8及R0.2；R0.5外角已建立。直线过渡依照本型号原图，非厂家制造CAD。"
    }
    row["notes"] = ["明确选择东磁PQ32/25参考版本：外宽32 mm；替换此前Ferroxcube的33 mm参考外形。",
        "原厂目录由镜像托管；型号、尺寸与机械图保留原厂归属。",
        "收腰底轭和圆弧极靴按本型号三视图重建；局部小圆角与颈部过渡未细化。",
        "仅调整机械参考外形，不改工程Ae、Ve、DMR44材料或电气求解。"]

    row = by_model["PQ20-17"]
    d = row["dimensions_mm"]
    # Fig.1 is explicitly assigned to PQ20/17 by ACORE's size table.
    # Neck x is sampled from Fig.1, while diameter and shoulder minimum are
    # taken from the PQ20/17 row, not from that generic image's visual scale.
    poly = waist_outline(d["width"],d["depth"],4.4,2.75,6.65,6.0)
    row["shape_profile"] = {"yoke_xy_mm":rounded(poly),
                            "returns_xy_mm":[rounded(p) for p in circular_returns(poly,9.)]}
    row["source_page"] = "PQ20/17尺寸行及Fig.1三视图"
    row["shape_evidence"] = {
        "kind":"manufacturer_orthographic_dimensioned_raster",
        "source_url":row["source_url"],
        "source_image_url":"https://koss.iyong.com/swift/v1/iyong_public/iyong_2501387125244416/image/20180407/1523064124393085683.jpg",
        "source_figure":"Fig.1，厂家明确分配给PQ20/17",
        "source_contour_bbox_px":[260,87,335,195],
        "dimension_constraints_mm":{"A":20.5,"C":14.,"D1":18.,"D2_min":13.3,"E":8.8},
        "drawing_sampled_mm":{"neck_half_width":2.75,"shoulder_half_depth":6.0},
        "construction":"本型号A/B/C/D1/D2/E/F行约束总尺寸、中心柱及窗口；按所分配Fig.1收腰俯视图确定未标转折。",
        "limits":"该型号未找到TDK或东磁同型，保持ACORE原厂参考；颈部转折由低分辨率系列图采样，微小圆角未细化。"
    }
    row["notes"] = ["PQ20/17保留安磁原厂参考；未改成TDK的PQ20/16或PQ20/20。",
        "收腰轮廓按厂家指定Fig.1与PQ20/17尺寸行重建；未标注的颈部转折为图示采样。",
        "中心柱E=8.8 mm按图纸名义值，公差+0.15/-0.30 mm；预览不做机械公差叠加。",
        "机械与工程Ae、Ve、材料、气隙独立；局部小圆角、夹具、骨架及引脚未细化。"]
    catalog_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Completed independent DMEGC PQ32/25 and ACORE PQ20/17 references")


if __name__ == "__main__":
    apply()
