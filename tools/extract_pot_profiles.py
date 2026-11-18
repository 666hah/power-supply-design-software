"""Build PM/PT preview contours from manufacturer dimensioned drawings.

Developer-only extraction. PDFs remain in artifacts; no third-party document is
bundled with the application. PM is a raster drawing with numeric constraints;
PT18 and the explicitly selected P22/13 reference use native PDF vectors.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

import pymupdf
from shapely.geometry import Polygon, Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from extract_tdk_pq_profiles import path_points


def rounded(points):
    return [[round(float(x), 6), round(float(y), 6)] for x, y in points]


def circle(radius, n=192):
    return [[radius*math.cos(i*2*math.pi/n), radius*math.sin(i*2*math.pi/n)] for i in range(n)]


def return_poles(outer, diameter):
    cut = Polygon(outer).difference(Point(0, 0).buffer(diameter/2, quad_segs=96))
    polygons = list(cut.geoms) if cut.geom_type == 'MultiPolygon' else [cut]
    assert len(polygons) == 2, (len(polygons), diameter)
    return [rounded(p.exterior.coords[:-1]) for p in polygons]


def shape(poly, returns, hole):
    p = Polygon(poly)
    assert p.is_valid and p.area > 0
    for r in returns:
        q = Polygon(r)
        assert q.is_valid and q.area > 0
        assert q.difference(p).area < 1e-5
    return dict(yoke_xy_mm=rounded(poly), returns_xy_mm=returns,
                yoke_holes_xy_mm=[rounded(circle(hole/2))])


def evidence(path, page, kind, **extra):
    return dict(kind=kind, source_pdf_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                source_page=page, **extra)


def pm_contour(A, B, I, D):
    # Source Fig.1 raster XObject 1393: outer circle centre (222,430),
    # radius 117 px, central waist y=377 px. The dimensioned I is the
    # chord between window-circle / lead-opening intersections, not an angle.
    R, r, half = A/2, B/2, D/2
    xend = math.sqrt(R*R-half*half)
    xi, yi = I/2, math.sqrt(r*r-(I/2)**2)
    waist = A*53/234
    # Symmetric quartic passes through both marked edge/chord anchors and the
    # unannotated raster waist; it does not invent a free sector opening angle.
    x2, e2 = xi*xi, xend*xend
    c4 = ((half-waist)/e2-(yi-waist)/x2)/(e2-x2)
    c2 = (yi-waist)/x2-c4*x2
    top = [[x, waist+c2*x*x+c4*x**4] for x in [-xend+2*xend*j/80 for j in range(81)]]
    theta = math.asin(half/R)
    right = [[R*math.cos(t), R*math.sin(t)] for t in [theta-2*theta*j/96 for j in range(1,97)]]
    bottom = [[x, -y] for x,y in reversed(top[:-1])]
    left = [[R*math.cos(t), R*math.sin(t)] for t in [math.pi+theta-2*theta*j/96 for j in range(1,97)]]
    return top+right+bottom+left[:-1]


def main():
    folder = ROOT/'artifacts/core-shape-correction-20261115'
    dm = ROOT/'artifacts/core-shape-catalog-20261115/dmegc-mnzn-2025.pdf'
    fx = folder/'ferroxcube-2005.pdf'
    td = folder/'tdk-p22-13.pdf'
    result = {}
    for model,A,B,C,I,D,H in [('PM50/39',50,39,20,25.4,50*174/234,5.4),('PM62/49',62,48.8,25.5,30,46,5.4)]:
        poly = pm_contour(A,B,I,D)
        result[model] = dict(shape_profile=shape(poly,return_poles(poly,B),H),
            dimensions_update=dict(width=A,depth=D,lead_opening=I),
            dimension_mapping='A→母圆直径；B→窗口圆径；C→中心柱径；D→上下轮廓端点间距；I→窗口圆与引线口交点弦宽；2E/2→外柱高；2F/2→半芯高；H→贯穿中心孔。',
            shape_evidence=evidence(dm,42,'manufacturer_raster_dimension_constrained',
                source_url='https://www.dmegc.com.cn/uploads/20250515/%E9%94%B0%E9%94%8C%E7%9B%AE%E5%BD%95.pdf.pdf',
                source_xobject=1393, source_raster_circle_center_px=[222,430],source_raster_circle_radius_px=117,
                source_raster_waist_px=[222,377],
                construction='由 A 外圆、B 窗口圆、I 开口弦宽和 D 截边高约束蝴蝶型底轭；凹口中心位置按原图像素比例，连续曲线通过标注交点。外柱为底轭轮廓减去 B 窗口圆。',
                limits=('PM50/39A 的 D 在规格表未标注，按原图 174/234×A 取图示高度；' if model=='PM50/39' else '')+'未标注凹弧与过渡圆角属于图示插值；不作为制造公差或场解CAD。'),
            notes=['保留蝴蝶型底轭、两侧圆弧外柱及贯穿中心孔；I 是开口弦宽，不是扇形角度。',
                   '未标注凹口曲线按规格图约束插值，完整机械交货图仍用于制造。',
                   '机械预览与工程材料、Ae、Ve及物理气隙分别保存。'])

    ds = pymupdf.open(fx)[655].get_drawings()
    items = ds[15]['items']
    left, right = path_points(items[:12]), path_points(items[13:25])
    raw = left+right
    # Plan view marks 18.0 horizontally and 11.94 between the two flat lips.
    cx,cy=(364.90899658203125+435.9809875488281)/2,(229.9639892578125+279.11700439453125)/2
    sx,sy=18/(435.9809875488281-364.90899658203125),11.94/(279.11700439453125-229.9639892578125)
    poly=[[(x-cx)*sx,(cy-y)*sy] for x,y in raw]
    result['PT18']=dict(shape_profile=shape(poly,return_poles(poly,15.15),3.1),
        dimensions_update=dict(width=18,depth=max(y for x,y in poly)-min(y for x,y in poly),lead_opening=10.5),
        dimension_mapping='18.0→平面横向宽；11.94→上下平口间距；15.15→窗口圆径；7.4→中柱径；10.6/2→半芯高；7.4/2→外柱高；3.1→贯穿中心孔。',
        shape_evidence=evidence(fx,656,'manufacturer_orthographic_vector',source_url='https://www.farnell.com/datasheets/62793.pdf',
            pdf_path_indices=[15],pdf_item_ranges=[[0,12],[13,25]],
            scale_x_mm_per_pt=sx,scale_y_mm_per_pt=sy,curve_samples_per_cubic=16,
            construction='本型号平面矢量外轮廓，保留四个绕线口凸耳及上下平口；窗口圆将底轭分成两片外柱。',
            limits='旧库名称PT18按已声明的PT18/11参考；未标注耳端曲线沿图采样，标注主尺寸独立约束。'),
        notes=['PT18 未带高度后缀，使用明确参考 PT18/11。保留图中四个凸耳与上下平口。',
               '中心孔贯穿中柱和底轭；不使用圆罐轮廓替代。','机械模型与工程材料、Ae、Ve及物理气隙独立。'])

    ds=pymupdf.open(td)[2].get_drawings()
    paths={i:path_points(ds[i]['items']) for i in [54,55,56,57,62,63]}
    raw=(path_points(ds[54]['items'][:6])+paths[62]+list(reversed(path_points(ds[57]['items'][:6])))+
         path_points(ds[56]['items'][:6])+list(reversed(paths[63]))+list(reversed(path_points(ds[55]['items'][:6]))))
    cx,cy=468.2750244140625,(157.04598999023438+230.29299926757812)/2
    scale=22/(230.29299926757812-157.04598999023438)
    convert=lambda p:[[(x-cx)*scale,(cy-y)*scale] for x,y in p]
    poly=convert(raw)
    poles=[convert(paths[54]+list(reversed(paths[55]))),convert(paths[56]+list(reversed(paths[57])))]
    result['PT22']=dict(shape_profile=shape(poly,[rounded(p) for p in poles],4.4),
        dimensions_update=dict(width=max(x for x,y in poly)-min(x for x,y in poly),depth=22),
        dimension_mapping='明确参考 P22/13：22→平面母圆直径；17.9→内窗直径；13.9→左右引出凹口底间距；3.9→凹口宽；9.4→中柱径；4.4→中心通孔；13.6/2→半芯高；9.2/2→外柱高。',
        shape_evidence=evidence(td,3,'manufacturer_orthographic_vector',source_url='https://www.tdk-electronics.tdk.com/inf/80/db/fer/p_22_13.pdf',
            pdf_path_indices=[54,55,56,57,62,63],curve_samples_per_cubic=16,scale_mm_per_pt=scale,
            construction='直接采样上下两片外柱与左右引出凹口；底轭沿外柱外圆和凹口底边闭合，中心孔穿透底轭。',
            limits='PT22 是旧库短名，当前仍明确采用 P22/13 参考版本，不声称两个料号相同；未建螺纹套、微小轴向台阶。'),
        notes=['旧库 PT22 缺少厂家料号，沿用已明确选择的 TDK P22/13 (B65661) 参考。',
               '保留上下两片环形外柱、左右引出凹口和中心通孔；未建调节螺纹套。','机械模型与工程材料、Ae、Ve及物理气隙独立。'])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'pot-profiles.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Independent plan overlays expose contour mistakes before mesh generation.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(9,9))
    for ax,(name,row) in zip(axes.flat,result.items()):
        prof=row['shape_profile'];p=prof['yoke_xy_mm']
        ax.fill(*zip(*p),color='#c2d2da');ax.plot(*zip(*(p+[p[0]])),color='#264557')
        for r in prof['returns_xy_mm']:ax.fill(*zip(*r),color='#526f82')
        for h in prof['yoke_holes_xy_mm']:ax.fill(*zip(*h),color='white')
        ax.set_title(name);ax.set_aspect('equal');ax.grid(True,alpha=.2)
    fig.tight_layout();fig.savefig(folder/'pot-plan-profiles.png',dpi=150);plt.close(fig)
    print('Exported four independently traced/constrained PM/PT profiles')


if __name__=='__main__':main()
