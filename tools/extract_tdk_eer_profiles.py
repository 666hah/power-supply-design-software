"""Extract each EER/ER plan and pole curve from its own TDK drawing."""
from pathlib import Path
import hashlib
import json
import pymupdf
from shapely.geometry import Polygon
from build_nonpq_drawing_profiles import sample, ring

ROOT=Path(__file__).resolve().parents[1]
PDF=ROOT/'artifacts/core-shape-catalog-20261115/tdk-e.pdf'


def main():
    doc=pymupdf.open(PDF)
    records={r['model']:r for r in json.loads((ROOT/'resources/core_shapes/catalog.json').read_text('utf-8'))['cores']}
    out={}
    for model,page,yoke_index,curve_index in [('ER28',35,102,104),('EER28L',37,102,104),('ER35',39,118,69),('EER40',41,118,69)]:
        d=records[model]['dimensions_mm'];draw=doc[page-1].get_drawings()
        src=draw[yoke_index];raw=sample(src['items']);bounds=src['rect']
        W,D,E=d['width'],d['depth'],d['window_outer_width']
        sx=D/bounds.width;sy=W/bounds.height
        cx=(bounds.x0+bounds.x1)/2;cy=(bounds.y0+bounds.y1)/2
        poly=Polygon([((y-cy)*sy,(x-cx)*sx) for x,y in raw])
        inner=sample(draw[curve_index]['items']); ymin=min(y for x,y in inner)
        # E constrains the deepest points of the two opposing pole arcs.
        curve=[(-E/2+(y-ymin)*sy,(x-cx)*sx) for x,y in inner]
        cut=Polygon(curve+[(-W,curve[-1][1]),(-W,curve[0][1])])
        left=poly.intersection(cut)
        right=Polygon([(-x,y) for x,y in left.exterior.coords])
        assert left.is_valid and right.is_valid
        out[model]=dict(shape_profile=dict(yoke_xy_mm=ring(poly),returns_xy_mm=[ring(left),ring(right)],
              source_method=f'TDK EER catalogue p{page}: nominal A/C/E, own vector yoke and pole arcs',
              undimensioned_features='Pole curvature and corner/waist fillets follow the individual drawing; not manufacturing tolerances.'),
          shape_evidence=dict(kind='manufacturer_orthographic_vector_dimension_constrained',
              source_url=records[model]['source_url'],source_page=page,source_pdf_sha256=hashlib.sha256(PDF.read_bytes()).hexdigest(),
              yoke_vector_index=yoke_index,return_vector_index=curve_index,
              limits='未标注的内侧圆弧及圆角按本型号原图提取；A/C/E采用名义尺寸；显示模型不代替制造公差图。'),
          source_page=str(page),
          notes=['底轭轮廓和弧形外柱来自本型号TDK三视图；保留中柱附近的侧壁收口。',
                 '未注尺寸的曲线采用图示轮廓；材料、Ae、Ve及物理气隙仍沿用当前工程。'])
    target=ROOT/'artifacts/core-shape-correction-20261115/eer-profiles.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(target)


if __name__=='__main__':main()
