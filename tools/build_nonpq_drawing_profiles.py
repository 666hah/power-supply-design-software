"""Rebuild the RM, EP and EFD display outlines from the cited manufacturer views.

Development-only: PyMuPDF/Shapely; the desktop reads the frozen mesh assets.
Dimensioned features use nominal millimetres. Undimensioned draft radii/chamfers
retain the cited view proportions and are explicitly identified as such.
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from shapely.geometry import Point, Polygon, box
import pymupdf

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'artifacts/core-shape-catalog-20261115'
OUT = ROOT / 'artifacts/core-shape-correction-20261115/nonpq-profiles.json'


def ring(poly):
    assert poly.is_valid and poly.area > 0
    return [[round(x, 6), round(y, 6)] for x, y in list(poly.exterior.coords)[:-1]]


def parts(geometry):
    return [geometry] if geometry.geom_type == 'Polygon' else list(geometry.geoms)


def profile(yoke, returns, **extra):
    return dict(yoke_xy_mm=ring(yoke), returns_xy_mm=[ring(p) for p in parts(returns)], **extra)


def rm(record):
    d = record['drawing_dimensions_mm']
    m = record['model']
    I = {'RM6': 8., 'RM8': 10.8, 'RM10': 13.25, 'RM12': 16., 'RM14': 18.7}[m]
    A, F, E = d['A'], d['F'], d['E_min']
    k = A / math.sqrt(2)
    tip = k - F/2
    if m == 'RM6':
        # Fig.3: the side notch reaches the centre line; E spans the corners.
        q = [(0,I/2),(E/2,k-E/2),(F/2,tip)]
        fig = 3
    else:
        # Fig.1 has 45-degree notch sides. Fig.2 angle follows the vector view.
        ratio = 1. if m == 'RM14' else 10.698 / 8.342
        t = (k-I/2-E/2)/(1+ratio)
        q = [(E/2,I/2),(E/2+ratio*t,I/2+t),(F/2,tip)]
        fig = 1 if m == 'RM14' else 2
    pts = q + [(x,-y) for x,y in reversed(q)]
    pts += [(-x,-y) for x,y in q] + [(-x,y) for x,y in reversed(q)]
    yoke = Polygon(pts).buffer(0)
    returns = yoke.difference(Point(0,0).buffer(d['B']/2,quad_segs=64))
    p = profile(yoke, returns, source_method=f'TDK RM p2 Fig.{fig}: A/F/I/E constraints; B circular window',
                undimensioned_features='Fig.2 notch angle follows the vector drawing; clip spring details omitted.')
    return dict(shape_profile=p, dimensions_mm=dict(width=F,depth=yoke.bounds[3]-yoke.bounds[1],lead_opening=E),
                drawing_dimensions_mm=dict(I=I),
                dimension_mapping='F→X全高；A为旋转方形边长；I/E约束收腰；B为窗口直径；C为中柱直径；2D/2为半芯高，2H/2为沟深。')


def sample(items):
    pts=[]
    for i in items:
        if i[0]=='re':
            continue
        if not pts: pts.append(tuple(i[1]))
        if i[0]=='l': pts.append(tuple(i[2]))
        elif i[0]=='c':
            a,b,c,d=i[1:]
            for n in range(1,17):
                t=n/16;u=1-t
                pts.append(tuple(u**3*a[j]+3*u*u*t*b[j]+3*u*t*t*c[j]+t**3*d[j] for j in range(2)))
    return pts


def ep(record):
    d=record['dimensions_mm']; W,D=d['width'],d['depth']
    page=pymupdf.open(INPUT/'tdk-ep.pdf')[3]
    # Outer shell plan: drawing path 138; final rectangle belongs to side view.
    raw=sample(page.get_drawings()[138]['items'][:6])
    x0,x1=46.7670021057,102.9440002441
    y0,y1=128.3319854736,213.3469848633
    cy=170.1979980469;cx=86.0690002441
    # Keep the pillar at the same origin as winding paths.
    transform=lambda q: ((q[1]-cy)*W/(y1-y0),(q[0]-cx)*D/(x1-x0))
    yoke=Polygon([transform(q) for q in raw])
    r=d['window_diameter']/2
    # Semicircular rear cavity continuing into a straight slot at the open side.
    cavity=Point(0,0).buffer(r,quad_segs=64).union(box(-r,0,r,D*2))
    p=profile(yoke,yoke.difference(cavity), center_offset_xy_mm=[0,0],
              source_method='TDK EP p4 vector path 138; nominal A/E, exact B/C circular diameters',
              undimensioned_features='Rear corner radius and pillar setback retain the common drawing proportions.')
    return dict(shape_profile=p,dimension_mapping='A→X宽；E→Y深；中心柱为坐标原点；B/2圆形后腔接前侧直槽；C中柱；2D/2半芯高，2H/2沟深。')


def efd(record):
    m=record['model']
    data={
      'EFD15':('15_8_5',15.,4.65,7.5,5.5,5.3,2.4,11.,-.2,4.775,3.5,1.71,.5),
      'EFD20':('20_10_7',20.,6.65,10.,7.7,8.9,3.6,15.4,.17,6.147,4.762,1.876,.81),
      'EFD25':('25_13_9',25.,9.1,12.5,9.3,11.4,5.2,18.7,.6,6.836,5.297,2.161,.8),
      'EFD30':('30_15_9',30.,9.1,15.,11.2,14.6,4.9,22.4,.75,8.147,6.512,2.148,.82),
    }
    suffix,W,D,H,wh,cw,cd,win,step,nw,nb,nh,ch=data[m]
    # Dimensioned lower offset is taken from each individual TDK plan, not
    # the previous assumption that the centre touches the outer bottom edge.
    cy=D/2-step-cd/2
    centre=Polygon([(-cw/2+ch,-cd/2),(cw/2-ch,-cd/2),(cw/2,-cd/2+ch),
                    (cw/2,cd/2-ch),(cw/2-ch,cd/2),(-cw/2+ch,cd/2),
                    (-cw/2,cd/2-ch),(-cw/2,-cd/2+ch)])
    centre_shift=Polygon([(x,y+cy) for x,y in centre.exterior.coords])
    # Notch and chamfers are undimensioned in these drawings: points scaled
    # from their own plan view; the source and that status remain in metadata.
    main=[(-W/2,D/2),(-W/2,-D/2),(-nw/2,-D/2),(-nb/2,-D/2+nh),
          (nb/2,-D/2+nh),(nw/2,-D/2),(W/2,-D/2),(W/2,D/2),
          (cw/2,D/2),(cw/2-ch,D/2-step),(-cw/2+ch,D/2-step),(-cw/2,D/2)]
    yoke=Polygon(main).union(centre_shift)
    returns=box(-W/2,-D/2,-win/2,D/2).union(box(win/2,-D/2,W/2,D/2))
    p=profile(yoke,returns,center_xy_mm=ring(centre),center_offset_xy_mm=[0,cy],
              source_method=f'TDK EFD {suffix.replace("_","/")} p2: three views with nominal dimensions and centre offset',
              undimensioned_features='Trapezoid lead notch and centre chamfer follow the individual printed plan; not manufacturing tolerances.')
    return dict(shape_profile=p,manufacturer='TDK Electronics',reference_model='EFD '+suffix.replace('_','/'),
      source_url='https://www.tdk-electronics.tdk.com/inf/80/db/fer/efd_'+suffix+'.pdf',source_page='2',
      source_revision='2025-10' if m=='EFD15' else '2022-10',
      dimensions_mm=dict(width=W,depth=D+max(0,-step),body_depth=D,half_height=H,window_height=wh,
           center_width=cw,center_depth=cd,center_offset_y=cy,window_outer_width=win,outer_leg_width=(W-win)/2),
      drawing_dimensions_mm=dict(width=W,depth=D,half_height=H,window_height=wh,center_width=cw,
           center_depth=cd,window_outer_width=win,center_bottom_inset=step),
      dimension_mapping='按TDK逐型号三视图：宽/本体深/半芯高/沟深/柱宽深为标注值；中心柱下缘台阶含正负号；槽口与柱倒角按本型号图示轮廓。')


def main():
    cat=json.loads((ROOT/'resources/core_shapes/catalog.json').read_text(encoding='utf-8'))
    out={}
    for r in cat['cores']:
        fn={'rm':rm,'ep':ep,'efd':efd}.get(r['template'])
        if fn: out[r['model']]=fn(r)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'{len(out)} profiles: {OUT}')


if __name__=='__main__': main()
