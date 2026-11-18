"""Extract seven ETD pole-shoe contours from their own TDK plan drawings."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import pymupdf
from extract_tdk_pq_profiles import path_points, rounded

BASE = Path("artifacts/core-shape-catalog-20261115")
PARTS = {
    'ETD29': ('tdk-e.pdf',48,103,[105],False),
    'ETD34': ('tdk-e.pdf',49,100,[109,110],True),
    'ETD39': ('tdk-e.pdf',50,100,[109,110],True),
    'ETD44': ('tdk-e.pdf',51,88,[90],False),
    'ETD49': ('tdk-e.pdf',52,103,[105],False),
    'ETD54': ('tdk-etd-54_28_19.pdf',2,44,[131,132],False),
    'ETD59': ('tdk-etd-59_31_22.pdf',2,57,[130,131],False),
}


def dash_centers(items):
    result=[]
    for index in range(0,len(items),4):
        q=[tuple(item[1]) for item in items[index:index+4]]
        result.extend([[(q[0][k]+q[3][k])/2 for k in range(2)],
                       [(q[1][k]+q[2][k])/2 for k in range(2)]])
    return result


def apply():
    target=Path('resources/core_shapes/catalog.json')
    data=json.loads(target.read_text(encoding='utf8'))
    for row in data['cores']:
        model=row['model']
        if model not in PARTS:
            continue
        filename,page,outer_id,inner_ids,dashed=PARTS[model]
        source=BASE/filename
        pdf=pymupdf.open(source)
        drawings=pdf[page-1].get_drawings()
        d=row['dimensions_mm']
        if model in ('ETD54','ETD59'):
            is54=model=='ETD54'
            d.update(width=54.5 if is54 else 59.8, depth=18.9 if is54 else 21.65,
                     center_width=18.9 if is54 else 21.65, center_depth=18.9 if is54 else 21.65,
                     center_diameter=18.9 if is54 else 21.65,half_height=27.6 if is54 else 31.,
                     window_height=20.0 if is54 else 22.45,window_outer_width=41.2 if is54 else 44.7,
                     outer_leg_width=6.65 if is54 else 7.55)
            part='54_28_19' if is54 else '59_31_22'
            row.update(manufacturer='TDK Electronics',reference_model='ETD 54/28/19 B66395' if is54 else 'ETD 59/31/22 B66397',
                       source_url=f'https://www.tdk-electronics.tdk.com/inf/80/db/fer/etd_{part}.pdf',
                       source_page='2',source_revision='2022-10' if is54 else '2024-10')
            row['drawing_dimensions_mm']={
                'width_nominal':d['width'],'depth_upper_limit':19.3 if is54 else 22.1,
                'depth_minus_tolerance':0.8 if is54 else 0.9,
                'half_height_upper_limit':27.8 if is54 else 31.2,'half_height_minus_tolerance':0.4,
                'window_height_lower_limit':19.6 if is54 else 22.,
                'window_height_plus_tolerance':0.8 if is54 else 0.9,
                'window_width_lower_limit':40.1 if is54 else 43.6,'window_width_plus_tolerance':2.2}
            row['dimension_selection']='尺寸区间取中点：单边公差按上下限的中点建立参考模型，不将最大外形或最小窗口混为同一批标称尺寸。'
        raw=path_points(drawings[outer_id]['items'])
        u0,u1=min(p[0] for p in raw),max(p[0] for p in raw)
        v0,v1=min(p[1] for p in raw),max(p[1] for p in raw)
        rotated=filename=='tdk-e.pdf'
        def convert(p):
            u,v=p
            if rotated:
                return [((v0+v1)/2-v)*d['width']/(v1-v0),(u-(u0+u1)/2)*d['depth']/(u1-u0)]
            return [(u-(u0+u1)/2)*d['width']/(u1-u0),((v0+v1)/2-v)*d['depth']/(v1-v0)]
        yoke=[convert(p) for p in raw]
        if len(inner_ids)==1:
            items=drawings[inner_ids[0]]['items']
            count=len(items)//2
            curves=[path_points(items[:count]),path_points(items[count:])]
        else:
            curves=[dash_centers(drawings[i]['items']) if dashed else path_points(drawings[i]['items']) for i in inner_ids]
        returns=[]
        for curve in curves:
            points=[convert(p) for p in curve]
            side=1 if sum(p[0] for p in points)>0 else -1
            # E is the measured maximum span between the two curved windows.
            scale=(d['window_outer_width']/2)/max(abs(p[0]) for p in points)
            points=[[x*scale,y] for x,y in points]
            points.sort(key=lambda p:p[1])
            # Drawing line endpoints may stop a stroke width short of the
            # outer contour; they lie on the same nominal boundary in the part.
            points[0][1]=-d['depth']/2
            points[-1][1]=d['depth']/2
            outer=[p for p in yoke if side*p[0]>0]
            outer.sort(key=lambda p:math.atan2(p[1],side*p[0]),reverse=True)
            returns.append(rounded(points+outer))
        row['shape_profile']={'yoke_xy_mm':rounded(yoke),'returns_xy_mm':returns}
        row['shape_evidence']={
            'kind':'manufacturer_orthographic_vector', 'source_url':row['source_url'],
            'source_pdf_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'source_page':page,
            'pdf_yoke_path_index':outer_id,'pdf_window_path_indices':inner_ids,
            'pdf_contour_bbox_pt':[u0,v0,u1,v1],
            'construction':'本型号俯视外廓形成底轭；两外柱内壁使用本型号弧形窗口曲线，按总宽/深与最大窗口宽校准；中心柱独立采用图纸直径。',
            'limits':'未注过渡圆角由本型号原图采样；ETD34/39窗口虚线为填充小片，取各片中心线并连接空隙。非制造公差模型。',
            'curve_method':'outlined_dash_centerline' if dashed else 'original_cubic_bezier',
        }
        row['source_page']=str(page)
        row['dimension_mapping']='宽/深为底轭总外廓；中心柱为圆柱；窗口外宽为弧形内壁在Y=0附近的最大间距；半芯高和沟深均为单件尺寸。'
        row['notes']=['底轭与中心柱齐深，没有额外推定的中部凸台；外柱内壁使用本型号弧形轮廓。',
                      row.get('dimension_selection','按对应型号图纸名义值选择主尺寸；局部过渡取自原图。'),
                      '机械参考与Ae、Ve、DMR44材料及电气求解独立，未改变工程绕组与磁路输入。']
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('ETD seven independent profiles saved')


if __name__=='__main__':
    apply()
