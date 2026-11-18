"""Fill catalogue provenance for dimensioned primitives and traced sections."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def apply():
    target=Path('resources/core_shapes/catalog.json')
    data=json.loads(target.read_text(encoding='utf8'))
    base=Path('artifacts/core-shape-catalog-20261115')
    source_files={
        'RM':('tdk-rm.pdf',2),'EP':('tdk-ep.pdf',4),
        'EFD15':('tdk-efd-15_8_5.pdf',2),'EFD20':('tdk-efd-20_10_7.pdf',2),
        'EFD25':('tdk-efd-25_13_9.pdf',2),'EFD30':('tdk-efd-30_15_9.pdf',2),
    }
    primitive_constructions={
        'e_rect':'按机械图的总宽、深、半芯高、沟深、中心柱和外柱尺寸建立矩形E截面；底轭与三柱独立挤出。',
        'ei_rect':'按E芯机械尺寸建立底轭与三柱，再建立图示厚度的独立I板；不是两块E芯配对。',
        'u':'按总宽、深、半高、窗口外宽和沟深建立U形底轭及两个端柱。',
        'toroid':'按原厂外径、内径和整体高度建立轴向贯通的圆环。',
    }
    for row in data['cores']:
        profile=row.get('shape_profile',{})
        if row['model'] in source_files or row['family'] in ('RM','EP'):
            filename,page=source_files.get(row['model'],source_files.get(row['family']))
            source=base/filename
            evidence=row.setdefault('shape_evidence',{})
            evidence.update(kind='manufacturer_orthographic_dimensioned', source_url=row['source_url'],source_page=page,
                construction=profile.get('source_method',row['dimension_mapping']),
                limits=profile.get('undimensioned_features','未标注的局部过渡采用原图约束，不作为制造公差。'))
            if source.exists():
                evidence['source_pdf_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        if 'shape_evidence' not in row:
            designation=row['status']=='designation_nominal'
            row['shape_evidence']={
                'kind':'designation_dimensions' if designation else 'manufacturer_dimensioned_primitives',
                'source_url':row['source_url'],'source_page':row['source_page'],
                'construction':primitive_constructions.get(row['template'],row['dimension_mapping']),
                'limits':'未绑定原厂型号，按名称的三维尺寸建立磁环。' if designation else '主尺寸来自所列厂家；未标小圆角、微小倒角、夹具、骨架和引脚不计入本参考实体。',
            }
    data['geometry_revision']='2026-11-15-orthographic-contours'
    data['profile_semantics']={
        'yoke_xy_mm':'底轭闭合二维外轮廓，程序沿Z挤出；第一个点无需在末尾重复。',
        'returns_xy_mm':'每个外柱的闭合二维轮廓；与底轭分别挤出，不能用圆包络替代开口。',
        'center_xy_mm':'可选中央柱截面；缺省按尺寸中的圆或矩形建立。',
        'center_offset_xy_mm':'可选中央柱相对底轭的X/Y偏心，保留原图定位基准。',
        'shape_evidence':'每个型号的原厂出处、标注约束、图示采样方法与未细化特征；不代表制造CAD认证。',
    }
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Provenance completed:',len(data['cores']),'models;',sum(bool(r.get('shape_profile')) for r in data['cores']),'explicit profiles')


if __name__=='__main__':
    apply()
