# -*- coding: utf-8 -*-
"""声明式零件建模，单位 mm，坐标直接对应 SolidWorks 世界 X/Y/Z。

Python 描述经 C# Interop 早期绑定执行。v0.3 支持三轴圆柱、绕 Y 旋转
闭合多边形、按源实体 tag 对全部边圆角/45°倒角。合并后的实体采用最后
一个构成实体的颜色；精细面级分色可另外调用 colors.apply_rules。
"""
from __future__ import annotations

import base64
import json

from ._compat import temp_dir
from ._editable_dimensions import CS as _EDITABLE_CS, PROFILE_KINDS
from ._helical_native import CS as _HELICAL_CS
from ._native_features import CS as _NATIVE_FEATURES_CS, NativePartFeatures, evidence as _native_evidence
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass

__all__ = ["PartBuilder", "BuildResult", "Material", "COLORS"]
MM = 0.001


class Material:
    SILVER = (0.86, 0.88, 0.90)
    STEEL = (0.62, 0.66, 0.72)
    YELLOW = (1.00, 0.82, 0.08)
    BROWN = (0.55, 0.28, 0.10)
    BLACK = (0.10, 0.10, 0.11)
    BLUE = (0.52, 0.74, 0.90)
    GREEN = (0.16, 0.70, 0.34)
    RED = (0.86, 0.22, 0.22)
    ORANGE = (0.95, 0.55, 0.15)
    GRAY = (0.55, 0.55, 0.58)


COLORS = {name.lower(): value for name, value in vars(Material).items()
          if name.isupper()}


@dataclass
class BuildResult:
    ok: bool
    path: str
    bodies: int = 0
    features_ok: int = 0
    features_failed: int = 0
    elapsed_s: float = 0.0
    bbox_mm: tuple | str = ()  # 保留 v0.2 的包络摘要字符串
    log: str = ""
    error: str = ""
    color_coverage: float = 0.0  # 逐面写入且回读 RGB 一致的比例
    color_faces: int = 0
    paint_error: str = ""
    # ---- v0.5：物理材料与质量属性
    material_requested: str = ""
    material_applied: str = ""   # 从 SW 回读的材质名，空表示没赋上
    material_error: str = ""
    mass_kg: float = 0.0
    volume_mm3: float = 0.0
    # ---- 1.9.1：弹簧体积校验结果（tag -> verify() 返回）
    spring_checks: object = None
    auger_checks: object = None
    native_features: object = None
    output_semantics: str = "native_features"
    native_history: bool = True


@dataclass
class _Box:
    tag: str
    y0: float
    h: float
    x0: float
    x1: float
    z0: float
    z1: float
    rgb: tuple | None


def _number(value, name, positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{name}: 必须为有限数值")
    try:
        value = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name}: 必须为有限数值") from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name}: 必须为{'正的' if positive else ''}有限数值")
    return value


def _color(color):
    if color is None:
        return None
    if isinstance(color, str):
        if color not in COLORS:
            raise ValueError(f"未知颜色 {color!r}；可用：{', '.join(COLORS)}")
        return COLORS[color]
    if not isinstance(color, (list, tuple)) or len(color) != 3:
        raise ValueError("color 必须为配色名、3 个 0~1 的 RGB 数值或 None")
    rgb = tuple(_number(c, "RGB") for c in color)
    if any(c < 0 or c > 1 for c in rgb):
        raise ValueError("RGB 必须在 0~1 之间")
    return rgb


def _cs_string(value):
    # JSON 与 C# 的基本字符串转义相同；额外转义 C# 不允许的原始换行符。
    return json.dumps(str(value), ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _cs_num(value):
    return format(float(value), ".17g") + (".0" if float(value).is_integer() and abs(value) < 1e16 else "")


def _edge_rule(rule):
    if rule is None:
        return {}
    if not isinstance(rule,dict) or set(rule)-{'axis','min_length_mm','max_length_mm'}:
        raise ValueError('edges_rule 只支持 axis/min_length_mm/max_length_mm')
    result=dict(rule)
    if 'axis' in result and result['axis'] not in ('x','y','z'):
        raise ValueError('edges_rule.axis 必须为 x/y/z')
    for key in ('min_length_mm','max_length_mm'):
        if key in result:
            result[key]=_number(result[key],key,True)
    if result.get('min_length_mm',0)>result.get('max_length_mm',float('inf')):
        raise ValueError('选边最小长度不能大于最大长度')
    return result


def preview_edges(part_path,tag,edges_rule=None):
    """Read-only edge selection preview; filtered rules select straight edges only."""
    from .session import get_session,_value
    from .colors import _part_document
    rule=_edge_rule(edges_rule)
    md=_part_document(get_session().sw(),part_path)
    rows=[]
    body=next((b for b in md.GetBodies2(0,False) or [] if str(b.Name)==tag),None)
    if body is None:
        raise ValueError(f'找不到实体 tag: {tag}')
    for index,edge in enumerate(_value(body,'GetEdges') or []):
        curve=_value(edge,'GetCurve')
        linear=bool(_value(curve,'IsLine'))
        row={'index':index,'linear':linear,'selected':not bool(rule)}
        if linear:
            start,end=_value(edge,'GetStartVertex'),_value(edge,'GetEndVertex')
            if start is not None and end is not None:
                a,b=list(_value(start,'GetPoint')),list(_value(end,'GetPoint'))
                delta=[abs(y-x)*1000 for x,y in zip(a,b)]
                length=math.sqrt(sum(d*d for d in delta))
                selected=rule.get('min_length_mm',0)-1e-6<=length<=rule.get('max_length_mm',float('inf'))+1e-6
                if 'axis' in rule:
                    selected=selected and abs(delta['xyz'.index(rule['axis'])]-length)<1e-6
                row.update(length_mm=length,start_mm=[x*1000 for x in a],end_mm=[x*1000 for x in b],selected=selected)
        rows.append(row)
    return {'ok':True,'tag':tag,'edges':rows,'selected_count':sum(r['selected'] for r in rows),
            'dry_run':True,'rule':rule}


class PartBuilder(NativePartFeatures):
    """建模声明，不在添加形体时连接 SW。所有 tag 在单个构建器中唯一。"""

    def __init__(self, path: str, material: str = "Q235", merge: bool = False, material_db: str | None = None,
                 log: str | None = None, feature_strategy: str = "compact", *, editable_dimensions: bool = True):
        if feature_strategy not in ('compact', 'legacy'):
            raise ValueError('feature_strategy 必须为 compact 或 legacy')
        self.feature_strategy = feature_strategy
        self.editable_dimensions = bool(editable_dimensions)
        self.path = os.path.abspath(path)
        self.material = material
        # 材质库路径：None 表示自动（GB 牌号用生成的库，其它交给 SW 默认库）
        self.material_db = material_db
        self.merge = bool(merge)
        self.log_path = os.path.abspath(log or os.path.splitext(self.path)[0] + ".buildlog.txt")
        self._boxes: list[_Box] = []
        self._shapes = []
        self._finishes = []
        self._cuts = []
        self._native_ops = []
        self._tags = set()
        self._augers = {}
        self._springs = {}          # tag -> (SpringSpec, 解析值)

    def _add(self, tag, kind, values, color):
        tag = str(tag)
        if not tag.strip() or tag in self._tags:
            raise ValueError(f"tag 必须非空且唯一：{tag!r}")
        rgb = _color(color)
        self._tags.add(tag)
        self._shapes.append((kind, tag, values, rgb))
        return rgb

    def _compact_tube(self,tag,axis,values,color):
        values=tuple(_number(v,'tube coordinate/size') for v in values)
        self._add(tag,'Tube',(axis,)+values,color)

    def box(self, tag, x0, x1, y0, y1, z0, z1, color="silver"):
        vals = tuple(_number(v, n) for n, v in zip(
            ("x0", "x1", "y0", "y1", "z0", "z1"), (x0, x1, y0, y1, z0, z1)))
        x0, x1, y0, y1, z0, z1 = vals
        if x1 <= x0 or y1 <= y0 or z1 <= z0:
            raise ValueError(f"{tag}: 三轴尺寸必须为正")
        rgb = self._add(tag, "Box", vals, color)
        self._boxes.append(_Box(str(tag), y0, y1-y0, x0, x1, z0, z1, rgb))
        return self

    def plate(self, tag, x0, x1, y0, y1, z0, z1, color="steel"):
        return self.box(tag, x0, x1, y0, y1, z0, z1, color)

    def cylinder(self, tag, axis="y", x=0, y=0, z=0, r=10, h=10, color="silver"):
        """起点 (x,y,z)、半径 r、高度 h，沿世界正 axis 拉伸。"""
        axis = str(axis).lower()
        if axis not in ("x", "y", "z"):
            raise ValueError("cylinder.axis 必须为 x/y/z")
        vals = (axis,) + tuple(_number(v, n) for n, v in zip(("x", "y", "z"), (x, y, z)))
        vals += (_number(r, "r", True), _number(h, "h", True))
        self._add(tag, "Cylinder", vals, color)
        return self

    def helix_spring(self, tag, *, wire_diameter, mean_diameter, height, turns,
                     clockwise=False, color="steel"):
        """圆柱螺旋压缩弹簧（等螺距、开放端、圆线截面）。

        参数
        ----
        wire_diameter : 线径 d (mm)
        mean_diameter : 中径 D (mm)
        height        : **中心线轴向高度** H (mm)，不是自由高度
        turns         : 圈数 n
        clockwise     : True=右旋，False=左旋

        几何限制（超出直接抛 ValueError，不静默生成错误模型）：:

            1 <= n <= 20      0.1 <= d <= 50 mm      D <= 500 mm      H <= 2000 mm
            D >= 4d           1.25d <= 螺距 <= 0.5D

        建完由 ``build()`` 用解析体积校验；体积验不出旋向，旋向在 C# 侧回读螺旋线定义。
        """
        from .spring import SpringSpec, validate

        spec = SpringSpec(
            wire_diameter_mm=wire_diameter,
            mean_diameter_mm=mean_diameter,
            height_mm=height,
            turns=turns,
            clockwise=clockwise,
        )
        calc = validate(spec)
        tag = str(tag)
        if tag in self._tags:
            raise ValueError(f"tag 必须唯一：{tag!r}")
        self._add(tag, "HelixSpring",
                  (calc["mean_diameter_mm"], calc["wire_diameter_mm"],
                   calc["height_mm"], calc["turns"], calc["clockwise"]), color)
        spec = SpringSpec(calc["wire_diameter_mm"], calc["mean_diameter_mm"],
                          calc["height_mm"], calc["turns"], calc["clockwise"])
        self._springs[tag] = (spec, calc)
        return calc

    def auger_flight(self, tag, *, inner_diameter, outer_diameter, pitch, turns,
                     thickness, clockwise=True, color="steel"):
        """Add one native single-start flight. Diameters describe the midsurface."""
        from .auger import flight_geometry

        calc = flight_geometry(inner_diameter, outer_diameter, pitch, turns, thickness, clockwise)
        values = tuple(calc[key] for key in (
            "inner_diameter_mm", "outer_diameter_mm", "pitch_mm", "turns", "thickness_mm"))
        radial, axial, _ = calc["spans_mm"]
        self._add(tag, "AugerFlight", values+(1 if clockwise else -1, calc["area_mm2"],
                  calc["volume_mm3"], radial, axial), color)
        self._augers[str(tag)] = calc
        return self

    def revolve(self, tag, profile_pts, axis="y", angle=360, color="silver", x=0, y=0, z=0):
        """闭合多边形 [(径向, 轴向), ...] 绕指定正轴旋转，角度为度。

        轮廓首尾自动闭合；半径不得为负或跨轴，不支持自交。x/y/z 为轴原点。
        v0.6 支持 x/y/z 三轴；轮廓用 (径向, 轴向) 两个分量描述。
        """
        axis = str(axis).lower()
        if axis not in ("x", "y", "z"):
            raise ValueError("revolve.axis 必须为 x/y/z")
        angle = _number(angle, "angle", True)
        if angle > 360:
            raise ValueError("angle 必须在 (0,360] 度")
        try:
            pts = [tuple(_number(v, "轮廓坐标") for v in p) for p in profile_pts]
        except TypeError as exc:
            raise ValueError("profile_pts 必须为二维坐标列表") from exc
        if pts and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3 or any(len(p) != 2 for p in pts):
            raise ValueError("profile_pts 至少需要 3 个二维顶点")
        if any(p[0] < 0 for p in pts) or not any(p[0] > 0 for p in pts):
            raise ValueError("旋转轮廓半径须非负且至少一项大于零")
        if any(a == b for a, b in zip(pts, pts[1:] + pts[:1])):
            raise ValueError("轮廓不得包含零长度边")
        area = sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(pts, pts[1:]+pts[:1]))
        if abs(area) < 1e-10:
            raise ValueError("旋转轮廓面积必须大于零")
        def cross(a, b, c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        edges = list(zip(pts, pts[1:]+pts[:1]))
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i+1 or (i == 0 and j == len(edges)-1):
                    continue
                if max(min(a[0],b[0]),min(c[0],d[0])) > min(max(a[0],b[0]),max(c[0],d[0])):
                    continue
                if max(min(a[1],b[1]),min(c[1],d[1])) > min(max(a[1],b[1]),max(c[1],d[1])):
                    continue
                if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0:
                    raise ValueError("旋转轮廓不得自交或自接触")
        origin = tuple(_number(v, n) for n, v in zip(("x", "y", "z"), (x,y,z)))
        self._add(tag, "Revolve", (tuple(pts), axis, angle) + origin, color)
        return self

    def stepped_shaft(self, tag, steps, axis='y', x=0, y=0, z=0, color='silver'):
        """一个回转特征生成连续台阶轴；steps 按轴向给 length/diameter。"""
        if not isinstance(steps,list) or not 1<=len(steps)<=50:
            raise ValueError('steps 必须为 1~50 项 length/diameter 对象')
        profile=[(0,0)];position=0
        for step in steps:
            if not isinstance(step,dict) or set(step)!={'length','diameter'}:
                raise ValueError('每个台阶只接受 length/diameter')
            length=_number(step['length'],'length',True);radius=_number(step['diameter'],'diameter',True)/2
            if profile[-1] != (radius,position):profile.append((radius,position))
            position+=length;profile.append((radius,position))
        profile.append((0,position))
        return self.revolve(tag,profile,axis=axis,x=x,y=y,z=z,color=color)

    def fillet(self, tag, r, edges_rule=None):
        """对源 tag 所属实体的全部边倒圆角。过大的半径构建失败，不保存半成品。"""
        return self._finish(tag, "Fillet", _number(r, "r", True),edges_rule)

    def cut_box(self, tag, target, x0, x1, y0, y1, z0, z1, axis="y"):
        """从明确指定的实体切除轴对齐长方体；范围和坐标均为 mm。"""
        if target not in self._tags:
            raise ValueError(f"找不到切除目标 tag: {target}")
        if axis not in ('x', 'y', 'z'):
            raise ValueError('cut_box.axis 必须为 x/y/z')
        values=tuple(_number(v,n) for n,v in zip(('x0','x1','y0','y1','z0','z1'),(x0,x1,y0,y1,z0,z1)))
        if any(values[i+1]<=values[i] for i in (0,2,4)):
            raise ValueError('切除范围三轴尺寸必须为正')
        self._cut_add(tag, 'CutBox', (str(target), axis)+values)
        return self

    def _cut_add(self, tag, kind, values):
        tag=str(tag)
        if not tag.strip() or tag in self._tags:
            raise ValueError(f'tag 必须非空且唯一: {tag!r}')
        self._tags.add(tag)
        self._cuts.append((kind,tag,values))

    def hole(self, tag, target, *, axis='y', x=0, y=0, z=0, diameter=10,
             depth=None, through_all=False, direction=1,
             counterbore_diameter=None, counterbore_depth=None):
        """真实圆孔；孔口(x,y,z)、轴与正负方向明确，通孔/盲孔/平底沉孔。

        through_all=True 时不传 depth；否则 depth 为正 mm。只切 target 实体。
        沉孔需同时给出直径和深度，二者均为明确设计参数。
        """
        if target not in self._tags:
            raise ValueError(f'找不到孔目标 tag: {target}')
        if axis not in ('x','y','z') or isinstance(direction,bool) or direction not in (-1,1):
            raise ValueError('hole.axis 必须为 x/y/z，direction 必须为 1 或 -1')
        if not isinstance(through_all,bool):
            raise ValueError('through_all 必须为布尔值')
        point=tuple(_number(v,n) for n,v in zip(('x','y','z'),(x,y,z)))
        diameter=_number(diameter,'diameter',True)
        if through_all and depth is not None or not through_all and depth is None:
            raise ValueError('通孔只设 through_all=True；盲孔必须给 depth')
        depth=0.0 if through_all else _number(depth,'depth',True)
        if (counterbore_diameter is None)!=(counterbore_depth is None):
            raise ValueError('沉孔必须同时指定 counterbore_diameter/depth')
        cb=counterbore_diameter is not None
        if cb:
            counterbore_diameter=_number(counterbore_diameter,'counterbore_diameter',True)
            counterbore_depth=_number(counterbore_depth,'counterbore_depth',True)
            if counterbore_diameter<=diameter or not through_all and counterbore_depth>=depth:
                raise ValueError('沉孔直径须大于主孔，沉孔深度须小于盲孔总深度')
        tags=[str(tag)]+([str(tag)+'_counterbore'] if cb else [])
        if any(not t.strip() or t in self._tags for t in tags):
            raise ValueError('孔 tag 必须非空且唯一（含沉孔后缀）')
        self._cut_add(tag,'Hole',(str(target),axis)+point+(diameter,depth,int(through_all),direction))
        if cb:
            self._cut_add(tags[1],'Hole',(str(target),axis)+point+(counterbore_diameter,counterbore_depth,0,direction))
        return self

    def hole_grid(self, tag, target, *, rows=1, columns=1, pitch_u=20, pitch_v=20, **hole):
        """规则孔网格：compact 用原生草图阵列与单切除；X→YZ、Y→XZ、Z→XY。

        单一组 tag；沉孔保留两个切除并关联阵列参数。legacy 保留逐孔 tag。
        """
        if any(isinstance(n,bool) or not isinstance(n,int) or n<1 for n in (rows,columns)) or rows*columns>200:
            raise ValueError('孔阵列行列必须为正整数，一次最多200孔')
        pitch_u=_number(pitch_u,'pitch_u',True);pitch_v=_number(pitch_v,'pitch_v',True)
        axis=hole.get('axis','y')
        if axis not in ('x','y','z'):
            raise ValueError('孔阵列 axis 必须为 x/y/z')
        u,v={'x':('y','z'),'y':('x','z'),'z':('x','y')}[axis]
        # 先在独立声明中验证整批，防止非法的后续孔留下半批规格。
        check=PartBuilder(self.path);check._tags=set(self._tags)
        for row in range(rows):
            for col in range(columns):
                args=dict(hole)
                args[u]=_number(hole.get(u,0),u)+col*pitch_u
                args[v]=_number(hole.get(v,0),v)+row*pitch_v
                check.hole(f'{tag}_r{row+1}c{col+1}',target,**args)
        if self.feature_strategy == 'legacy':
            self._tags=check._tags;self._cuts.extend(check._cuts)
        else:
            # One native sketch pattern and one cut per depth, not one cut per hole.
            first=check._cuts[0][2]
            max_diameter=max(c[2][5] for c in check._cuts)
            if columns>1 and pitch_u<=max_diameter or rows>1 and pitch_v<=max_diameter:
                raise ValueError('紧凑孔网格的孔不得相交或相切')
            pending=[(str(tag), first)]
            if hole.get('counterbore_diameter') is not None:
                pending.append((str(tag)+'_counterbore',check._cuts[1][2]))
            if any(not t.strip() or t in self._tags for t,_ in pending):
                raise ValueError('孔组 tag 必须非空且唯一')
            for group,values in pending:
                self._cut_add(group,'HoleGrid',values+(rows,columns,pitch_u,pitch_v,
                    str(tag) if group!=str(tag) else ''))
        return self

    def chamfer(self, tag, d, edges_rule=None):
        """对源 tag 所属实体的全部边作 d×45° 倒角。"""
        return self._finish(tag, "Chamfer", _number(d, "d", True),edges_rule)

    def _finish(self, tag, kind, size, edges_rule=None):
        tag = str(tag)
        if tag not in self._tags:
            raise ValueError(f"找不到源实体 tag：{tag!r}")
        rule=_edge_rule(edges_rule)
        self._finishes.append((kind, tag, size,rule))
        return self

    @staticmethod
    def _tube_check(length, a, b, wall, inset):
        length, a, b, wall = tuple(_number(v, n, True) for n, v in
                                   zip(("长度", "截面宽", "截面高", "wall"), (length,a,b,wall)))
        inset = _number(inset, "inset")
        if inset != 0:
            raise ValueError("v0.3 不支持 inset；管材两端保持开放")
        if 2*wall >= min(a,b):
            raise ValueError("wall 必须小于截面短边的一半")

    def tube(self, *args, **kwargs):
        raise NotImplementedError("请使用 tube_x / tube_y / tube_z")

    def tube_y(self, tag, y0, y1, cx, cz, sx, sz, wall=6.3, color="yellow", inset=0.0):
        self._tube_check(y1-y0, sx, sz, wall, inset)
        if self.feature_strategy == 'compact':
            self._compact_tube(tag,'y',(cx,y0,cz,sx,sz,wall,y1-y0),color)
            return self
        x0,x1,z0,z1 = cx-sx/2,cx+sx/2,cz-sz/2,cz+sz/2
        self.box(tag+"_前",x0,x1,y0,y1,z0,z0+wall,color)
        self.box(tag+"_后",x0,x1,y0,y1,z1-wall,z1,color)
        self.box(tag+"_左",x0,x0+wall,y0,y1,z0+wall,z1-wall,color)
        self.box(tag+"_右",x1-wall,x1,y0,y1,z0+wall,z1-wall,color)
        return self

    def tube_z(self, tag, z0, z1, cx, cy, sx, sy, wall=6.3, color="yellow", inset=0.0):
        self._tube_check(z1-z0, sx, sy, wall, inset)
        if self.feature_strategy == 'compact':
            self._compact_tube(tag,'z',(cx,cy,z0,sx,sy,wall,z1-z0),color)
            return self
        x0,x1,y0,y1 = cx-sx/2,cx+sx/2,cy-sy/2,cy+sy/2
        self.box(tag+"_下",x0,x1,y0,y0+wall,z0,z1,color)
        self.box(tag+"_上",x0,x1,y1-wall,y1,z0,z1,color)
        self.box(tag+"_左",x0,x0+wall,y0+wall,y1-wall,z0,z1,color)
        self.box(tag+"_右",x1-wall,x1,y0+wall,y1-wall,z0,z1,color)
        return self

    def tube_x(self, tag, x0, x1, cy, cz, sy, sz, wall=6.3, color="yellow", inset=0.0):
        self._tube_check(x1-x0, sy, sz, wall, inset)
        if self.feature_strategy == 'compact':
            self._compact_tube(tag,'x',(x0,cy,cz,sy,sz,wall,x1-x0),color)
            return self
        y0,y1,z0,z1 = cy-sy/2,cy+sy/2,cz-sz/2,cz+sz/2
        self.box(tag+"_下",x0,x1,y0,y0+wall,z0,z1,color)
        self.box(tag+"_上",x0,x1,y1-wall,y1,z0,z1,color)
        self.box(tag+"_前",x0,x1,y0+wall,y1-wall,z0,z0+wall,color)
        self.box(tag+"_后",x0,x1,y0+wall,y1-wall,z1-wall,z1,color)
        return self

    @property
    def box_count(self):
        return len(self._boxes)

    @property
    def shape_count(self):
        return len(self._shapes)

    @property
    def feature_count(self):
        return len(self._shapes) + len(self._cuts) + len(self._finishes) + len(self._native_ops)

    def render_cs(self, *, paint=True, _log_path=None, keep_open=True, max_documents=8):
        if isinstance(max_documents, bool) or not isinstance(max_documents, int) or max_documents < 0:
            raise ValueError("max_documents 必须为非负整数（0 表示不允许再建文档）")
        calls = []
        for kind, tag, vals, rgb in self._shapes:
            args = [_cs_string(tag)]
            if kind == "HelixSpring":
                mean, wire, hgt, turns, cw = vals
                args.extend(_cs_num(v) for v in (mean, wire, hgt, turns))
                args.append("true" if cw else "false")
            elif kind == "LoftFeature":
                axis, points = vals
                args.extend((_cs_string(axis), "new double[]{" + ",".join(_cs_num(v) for v in points) + "}"))
            elif kind == "Revolve":
                pts, axis, angle, x, y, z = vals
                args.append("new double[]{" + ",".join(_cs_num(v) for p in pts for v in p) + "}")
                args.append(_cs_string(axis))
                args.extend(_cs_num(v) for v in (angle,x,y,z))
            else:
                args.extend(_cs_string(v) if isinstance(v,str) else _cs_num(v) for v in vals)
            args.append("null" if rgb is None or not paint else
                        "new double[]{" + ",".join(_cs_num(v) for v in rgb) + "}")
            calls.append("        " + kind + "(" + ",".join(args) + ");")
        for kind,tag,values in self._cuts:
            args=[_cs_string(tag)]+[_cs_string(v) if isinstance(v,str) else _cs_num(v) for v in values]
            calls.append('        '+kind+'('+','.join(args)+');')
        for kind, tag, size,rule in self._finishes:
            calls.append(f"        Finish({_cs_string(tag)},{_cs_num(size)},{str(kind == 'Fillet').lower()},"
                         f"{_cs_string(rule.get('axis',''))},{_cs_num(rule.get('min_length_mm',-1))},"
                         f"{_cs_num(rule.get('max_length_mm',-1))});")
        if self._native_ops:
            # API calls that use the current selection list require normal sketch mode.
            calls.append("        md.SketchManager.AddToDB=false;")
            for kind, tag, values in self._native_ops:
                args = [_cs_string(tag)] + [_cs_string(v) if isinstance(v,str) else _cs_num(v) for v in values]
                calls.append("        " + kind + "(" + ",".join(args) + ");")
        profiles = [(tag, PROFILE_KINDS[kind])
                    for kind, tag, *_ in self._shapes + self._cuts if kind in PROFILE_KINDS]
        dimension_pass = ""
        geometry_only = bool(self._springs or self._augers)
        if self.editable_dimensions and profiles and not geometry_only:
            tags, kinds = zip(*profiles)
            cs_tags = ",".join(_cs_string(tag) for tag in tags)
            cs_kinds = ",".join(_cs_string(kind) for kind in kinds)
            dimension_pass = f"AddEditableDimensions(new string[]{{{cs_tags}}},new string[]{{{cs_kinds}}});"
        # v0.5：GB 牌号自动指向生成的材质库；库外牌号交给 SW 默认库（DB 传空）
        mat_db = self.material_db
        if mat_db is None:
            try:
                from .gb_materials import lookup as _gb_lookup, ensure_library as _gb_ensure
                mat_db = _gb_ensure() if _gb_lookup(self.material) else ""
            except Exception:                            # noqa: BLE001
                mat_db = ""
        self.material_db = mat_db
        replacements = {"__CLASS__": "Bld_" + uuid.uuid4().hex,
                        "__OUT__": _cs_string(self.path),
                        "__LOG__": _cs_string(_log_path or self.log_path),
                        "__MERGE__": str(self.merge).lower(),
                        "__KEEP_OPEN__": str(bool(keep_open)).lower(),
                        "__MAX_DOCUMENTS__": str(max_documents),
                        "__MATERIAL__": _cs_string(self.material),
                        "__MATERIAL_DB__": _cs_string(self.material_db or ""),
                        "__BODY__": "\n".join(calls),
                        "__EDITABLE_PASS__": dimension_pass}
        src = _CS_TEMPLATE.replace("__NATIVE_FEATURES__", _NATIVE_FEATURES_CS + _HELICAL_CS)
        src = src.replace("__COMMUNITY_FLATTEN__", "FlattenCommunityGeometry(sw,tpl);" if geometry_only else "")
        src = src.replace("__EDITABLE_HELPERS__", _EDITABLE_CS if dimension_pass else "")
        for token, value in replacements.items():
            src = src.replace(token,value)
        from .sw_target import native_source
        return native_source(src)

    def build(self, timeout_s=900, paint=True, keep_open=True, max_documents=8):
        start = time.monotonic()
        if not self._shapes:
            return BuildResult(False, self.path, error="没有任何形体")
        if os.path.splitext(self.path)[1].lower() != ".sldprt":
            return BuildResult(False, self.path, error="输出文件必须使用 .SLDPRT 扩展名")
        if os.path.exists(self.path):
            return BuildResult(False, self.path, error="输出文件已存在；请使用新路径，避免覆盖原模型")
        if getattr(self,'design_spec',None) is not None and os.path.exists(self.path+'.design.json'):
            return BuildResult(False,self.path,error='设计参数日志已存在；请使用新路径')
        sw_dir = _find_sw_dir()
        if not sw_dir:
            return BuildResult(False, self.path, error="找不到 SolidWorks 安装目录")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        output = ""
        log = ""
        code = -1
        try:
            with temp_dir("swforge_") as work:
                run_log = os.path.join(work,"result.log")
                cs = self.render_cs(paint=paint, _log_path=run_log,
                                    keep_open=keep_open, max_documents=max_documents)
                cs_path = os.path.join(work,"Model.cs")
                with open(cs_path,"w",encoding="utf-8") as fh:
                    fh.write(cs)
                ps = _PS_RUNNER.format(cs=cs_path.replace("'","''"),
                      dll=os.path.join(sw_dir,"SolidWorks.Interop.sldworks.dll").replace("'","''"),
                      cst=os.path.join(sw_dir,"SolidWorks.Interop.swconst.dll").replace("'","''"),
                      cls=_cls_name(cs))
                ps_path = os.path.join(work,"run.ps1")
                with open(ps_path,"w",encoding="utf-8-sig") as fh:
                    fh.write(ps)
                try:
                    proc = subprocess.run(["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",ps_path],
                          capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout_s)
                    output = (proc.stdout or "") + (proc.stderr or "")
                    code = proc.returncode
                except subprocess.TimeoutExpired:
                    output = f"构建超过 {timeout_s} 秒；SW 可能仍在处理，未自动重试"
                if os.path.isfile(run_log):
                    with open(run_log,encoding="utf-8-sig") as fh:
                        log = fh.read()
        except (OSError, ValueError) as exc:
            output = f"{type(exc).__name__}: {exc}"
        # 本次运行日志单独生成，既有模型/日志从不作为本次成功证据。
        with open(self.log_path,"w",encoding="utf-8") as fh:
            fh.write(log or output)
        m = re.search(r"SWFORGE_RESULT ok=(\d+) failed=(\d+) bodies=(\d+) saved=(True|False) errors=(\d+)",log)
        c = re.search(r"SWFORGE_COLOR total=(\d+) requested=(\d+) verified=(\d+)",log)
        good,bad,bodies,saved,err = (int(m[1]),int(m[2]),int(m[3]),m[4] == "True",int(m[5])) if m else (0,0,0,False,0)
        ok = code == 0 and m is not None and good == self.feature_count and bad == 0 and bodies > 0 and saved and err == 0 and os.path.isfile(self.path)
        total,requested,verified = (int(c[1]),int(c[2]),int(c[3])) if c else (0,0,0)
        coverage = verified/requested if requested else (1.0 if not paint or total else 0.0)
        bbox = re.search(r"包络[^\n]*",log)
        result=BuildResult(ok,self.path,bodies,good,bad,time.monotonic()-start,
                           bbox[0] if bbox else "",log,
                           "" if ok else (output[-3000:] or log[-3000:] or "未收到本次构建结果"),
                           round(coverage,6),verified,
                           "" if verified == requested else f"配色回读仅通过 {verified}/{requested} 面")
        # ---- v0.5 物理材料与质量属性
        mat = re.search(r"SWFORGE_MATERIAL requested=(\S*) got=(\S*)",log)
        mass = re.search(r"SWFORGE_MASS mass_kg=([\d.eE+-]+) volume_mm3=([\d.eE+-]+)",log)
        result.output_semantics = "geometry_only" if self._springs or self._augers else "native_features"
        result.native_history = not bool(self._springs or self._augers)
        result.material_requested = self.material
        if mat:
            result.material_applied = "" if mat[2] in ("", "got=") else mat[2]
        if "SWFORGE_MATERIAL failed=" in log:
            result.material_error = log.split("SWFORGE_MATERIAL failed=",1)[1].splitlines()[0][:300]
        elif result.material_requested and not result.material_applied:
            result.material_error = "材料赋值后回读为空"
        if mass:
            try:
                result.mass_kg = float(mass[1]); result.volume_mm3 = float(mass[2])
            except ValueError:
                pass
        # A helical body's geometry is checked in the native bridge before SaveAs.
        if self._springs or self._augers:
            measurements = {}
            for line in log.splitlines():
                if line.startswith(("SWFORGE_SPRING ", "SWFORGE_AUGER ")):
                    kind, key, *values = line.split()
                    tag = base64.b64decode(key).decode("utf8")
                    measurements[(kind, tag)] = [float(value) for value in values]

            if self._springs:
                from .spring import describe, expected_bounds_mm, verify, verify_bounds
                result.spring_checks = {}
                for tag, (spec, calc) in self._springs.items():
                    values = measurements.get(("SWFORGE_SPRING", tag))
                    if values is None:
                        result.spring_checks[tag] = {"ok": False, "reason": "No verified spring geometry"}
                        continue
                    volume, x, y, z, pitch, height, turns, clockwise = values
                    check = verify(volume, calc)
                    check.update(model=describe(spec), bounds=verify_bounds((x,y,z), expected_bounds_mm(calc)),
                                 helix=dict(pitch_mm=pitch, height_mm=height, turns=turns, clockwise=bool(clockwise)))
                    check["ok"] = check["ok"] and check["bounds"]["ok"]
                    result.spring_checks[tag] = check

            if self._augers:
                result.auger_checks = {}
                for tag, calc in self._augers.items():
                    values = measurements.get(("SWFORGE_AUGER", tag))
                    if values is None:
                        result.auger_checks[tag] = {"ok": False, "reason": "No verified auger geometry"}
                        continue
                    volume, x, y, z, area, phase, angle, thickness = values
                    result.auger_checks[tag] = dict(ok=True, expected=calc, volume_mm3=volume,
                        spans_mm=[x,y,z], area_mm2=area, quarter_turn_error_mm=phase,
                        twist_rad=angle, total_normal_thickness_mm=thickness)
        result.native_features = _native_evidence(log)
        if result.ok and getattr(self,'design_spec',None) is not None:
            from .design import resolve_design
            from .variants import file_sha256
            from .version import __version__
            try:
                with open(self.path+'.design.json','x',encoding='utf8') as stream:
                    json.dump({'schema':1,'version':__version__,'model_sha256':file_sha256(self.path),
                        'design':self.design_spec,'resolved':resolve_design(self.design_spec),
                        'feature_strategy':self.feature_strategy},stream,ensure_ascii=False,indent=2)
            except OSError as exc:
                result.ok=False;result.error='Model saved but design manifest failed: '+str(exc)
        from datetime import datetime,timezone
        before=re.search(r'SWFORGE_DOCUMENTS before=(\d+)',log)
        after=re.search(r'SWFORGE_DOCUMENTS after=(\d+)',log)
        memory=re.search(r'SWFORGE_MEMORY working_set_bytes=(\d+)',log)
        with open(self.log_path+'.operations.jsonl','a',encoding='utf-8') as stream:
            stream.write(json.dumps({'time_utc':datetime.now(timezone.utc).isoformat(),
                'operation':'build','path':self.path,'ok':result.ok,'elapsed_s':result.elapsed_s,
                'documents_before':int(before[1]) if before else None,
                'documents_after':int(after[1]) if after else None,
                'working_set_bytes':int(memory[1]) if memory else None,
                'keep_open':keep_open,'max_documents':max_documents,
                'features_ok':good,'features_failed':bad,'bodies':bodies,'native_features':result.native_features,
                'material_requested':result.material_requested,'material_applied':result.material_applied,
                'mass_kg':result.mass_kg,'volume_mm3':result.volume_mm3,
                'paint_error':result.paint_error,'spring_checks':result.spring_checks,
                'auger_checks':result.auger_checks,'error':result.error},ensure_ascii=False)+'\n')
        return result


_CS_TEMPLATE = r'''
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Linq;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public class __CLASS__ {
    const double MM = 0.001;
    const bool MERGE = __MERGE__;
    static IModelDoc2 md;
    static ISldWorks application;
    static IMathUtility math;
    static int okN, badN;
    static StringBuilder log = new StringBuilder();
    static Dictionary<string,double[]> colors = new Dictionary<string,double[]>();
    static Dictionary<string,IFeature> sources = new Dictionary<string,IFeature>();
    static void L(string s) { log.AppendLine(s); }

__NATIVE_FEATURES__
__EDITABLE_HELPERS__
    static IFeature Datum(string axis) {
        // 标准模板前三个 RefPlane 按 Front,Top,Right 排列；不依赖系统语言。
        int wanted = axis == "x" ? 2 : axis == "y" ? 1 : 0;
        int i = 0;
        for (IFeature f=(IFeature)md.FirstFeature(); f!=null; f=(IFeature)f.GetNextFeature()) {
            if (f.GetTypeName2()=="RefPlane" && i++ == wanted) return f;
        }
        throw new Exception("标准模板缺少 " + axis + " 轴基准面");
    }

    // ── 草图推理开关（2026-11-12 实测缺陷的根治点）─────────────────────────
    // 现场：先建 8000 长的大方块，再在同一基准面上建 100 长的方块，
    // 第二个轮廓的四条边被 SW 自动推理成与大块共边 → 拉伸出来是 8000 长的
    // **重复体**（体积 800000 而不是 10000），而 features/bodies/配色回读全过，
    // 属于"静默生成错误几何"。规范要求"读回来核对、对不上就停"，因此：
    //   ① 生成轮廓期间显式关闭 swSketchInference，结束即恢复用户原设置；
    //   ② Box 拉伸后回读包络，对不上直接抛异常（见 CheckBox）。
    static bool inferenceWasOn=true, inferenceTouched=false;

    static void InferenceOff() {
        try {
            // swSketchInference 是【系统选项】，必须通过 ISldWorks 设置；
            // 在 IModelDoc2 上设无效（实测：设了仍然被推断吸附）。
            ISldWorks app=application;
            if(app!=null) {
                inferenceWasOn=app.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swSketchInference);
                app.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swSketchInference,false);
            } else {
                inferenceWasOn=md.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swSketchInference);
                md.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swSketchInference,false);
            }
            inferenceTouched=true;
        } catch (Exception) { inferenceTouched=false; }
    }

    static void InferenceRestore() {
        if(!inferenceTouched) return;
        try {
            ISldWorks app=application;
            if(app!=null) app.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swSketchInference,inferenceWasOn);
            else md.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swSketchInference,inferenceWasOn);
        }
        catch (Exception) { }
        inferenceTouched=false;
    }

    static ISketch Begin(string axis, double offset) {
        md.ClearSelection2(true);
        IFeature plane = Datum(axis);
        if (!plane.Select2(false,0)) throw new Exception("选基准面失败");
        if (Math.Abs(offset)>1e-9) {
            plane = (IFeature)md.FeatureManager.InsertRefPlane(8 | (offset<0 ? 256 : 0),Math.Abs(offset)*MM,0,0,0,0);
            if (plane==null) throw new Exception("建立偏移基准面失败");
            md.ClearSelection2(true);
            if (!plane.Select2(false,0)) throw new Exception("选偏移基准面失败");
        }
        InferenceOff();
        md.SketchManager.InsertSketch(true);
        ISketch sketch = (ISketch)md.SketchManager.ActiveSketch;
        if (sketch==null) { InferenceRestore(); throw new Exception("进入草图失败"); }
        return sketch;
    }

    static double[] Local(ISketch sketch,double x,double y,double z) {
        IMathPoint point=(IMathPoint)math.CreatePoint(new double[]{x*MM,y*MM,z*MM});
        point=(IMathPoint)point.MultiplyTransform(sketch.ModelToSketchTransform);
        double[] p=(double[])point.ArrayData;
        if (Math.Abs(p[2])>1e-7) throw new Exception("草图平面坐标不符，拒绝偏移错误的几何");
        return p;
    }

    static IFeature End(ISketch sketch) {
        md.SketchManager.InsertSketch(true);
        InferenceRestore();
        IFeature found=null;
        for(IFeature f=(IFeature)md.FirstFeature();f!=null;f=(IFeature)f.GetNextFeature())
            if(f.GetTypeName2()=="ProfileFeature") found=f;
        if(found==null) throw new Exception("找不到刚生成的草图");
        md.ClearSelection2(true);
        if(!found.Select2(false,0)) throw new Exception("选择草图失败");
        return found;
    }

    static IFeature Extrude(ISketch sketch,string axis,double start,double h) {
        IMathVector normal=(IMathVector)math.CreateVector(new double[]{0,0,1});
        normal=(IMathVector)normal.MultiplyTransform(sketch.ModelToSketchTransform.Inverse());
        double[] n=(double[])normal.ArrayData;
        double sign=n[axis=="x"?0:axis=="y"?1:2];
        if(Math.Abs(sign)<0.99) throw new Exception("草图法向与拉伸轴不符");
        return (IFeature)md.FeatureManager.FeatureExtrusion3(
            true,false,sign<0,0,0,h*MM,0,false,false,false,false,0,0,
            false,false,false,false,MERGE,false,true,
            Math.Abs(start)<1e-9 ? 0 : 3,Math.Abs(start)*MM,start*sign<0);
    }

    static IBody2 BodyOf(IFeature f) {
        object[] faces=(object[])f.GetFaces();
        if(faces==null || faces.Length==0) throw new Exception("特征没有实体面");
        return (IBody2)((IFace2)faces[0]).GetBody();
    }

    static void Register(string tag,IFeature f,double[] rgb) {
        if(f==null) throw new Exception(tag + " 特征返回空值");
        f.Name="SWFORGE_"+tag;
        sources[tag]=f;
        IBody2 body=BodyOf(f);
        body.Name=tag;
        colors[tag]=rgb;
        okN++;
        L(tag+" -> True");
    }

    static double[] ExactBounds(IBody2 body) {
        // 用 B-Rep 极值点取精确三轴尺寸。GetBodyBox 是近似包围盒，
        // 对螺旋这类曲面体在端部会有偏差，不能用来做 0.2% 级校验。
        double[] dims=new double[3];
        for(int axis=0;axis<3;axis++) {
            double[] limits=new double[2];
            for(int k=0;k<2;k++) {
                double vx=0,vy=0,vz=0;
                if(axis==0) vx=(k==0?-1.0:1.0);
                else if(axis==1) vy=(k==0?-1.0:1.0);
                else vz=(k==0?-1.0:1.0);
                double xv=0,yv=0,zv=0;
                if(!body.GetExtremePoint(vx,vy,vz,out xv,out yv,out zv))
                    throw new Exception("无法读取实体极值点");
                double coord = axis==0?xv:axis==1?yv:zv;
                if(Double.IsNaN(coord)||Double.IsInfinity(coord))
                    throw new Exception("实体极值点不是有限数值");
                limits[k]=coord*1000;
            }
            dims[axis]=limits[1]-limits[0];
        }
        return dims;
    }

    // 盒子拉伸后的回读核对：包络必须与请求的三轴范围一致（0.05 mm 容差）。
    // 不一致说明轮廓被草图推理/自动关系污染 —— 宁可报错，也不留错误几何。
    // GetBodyBox 顺序为 (xmin,ymin,zmin,xmax,ymax,zmax)。
    static void CheckBox(IBody2 body,string tag,double x0,double x1,double y0,double y1,double z0,double z1) {
        double[] bb;
        try { bb=(double[])body.GetBodyBox(); } catch(Exception) { return; }
        double[] want={x0,y0,z0,x1,y1,z1};
        for(int i=0;i<6;i++) {
            double got=bb[i]*1000;
            if(Math.Abs(got-want[i])>0.05)
                throw new Exception(tag+" 几何回读不一致：期望 "+want[i].ToString("0.###")
                    +" mm，实得 "+got.ToString("0.###")+" mm；判定为草图关系污染，拒绝生成错误模型");
        }
    }

    // 当前实体数（用于判断本步拉伸是"新增独立体"还是"并入已有体"）
    static int SolidBodyCount() {
        try { object[] b=(object[])((IPartDoc)md).GetBodies2(0,false); return b==null?0:b.Length; }
        catch(Exception) { return -1; }
    }

    static void Box(string tag,double x0,double x1,double y0,double y1,double z0,double z1,double[] rgb) {
        int bodiesBefore=SolidBodyCount();
        ISketch sketch=Begin("y",0);
        double[] a=Local(sketch,x0,0,z0), b=Local(sketch,x1,0,z1);
        md.SketchManager.CreateCornerRectangle(a[0],a[1],0,b[0],b[1],0);
        End(sketch);
        IFeature feature=Extrude(sketch,"y",y0,y1-y0);
        // 只有「新增独立实体」时，本步的包络才必须等于请求的三轴范围。
        // merge=True 时这一步得到的是与已有体的并集，包络本来就该更大
        // （test_merge_reports_actual_body_count 就是这种场景）。
        if(bodiesBefore>=0 && SolidBodyCount()>bodiesBefore)
            CheckBox(BodyOf(feature),tag,x0,x1,y0,y1,z0,z1);
        Register(tag,feature,rgb);
    }

    static void Cylinder(string tag,string axis,double x,double y,double z,double r,double h,double[] rgb) {
        ISketch sketch=Begin(axis,0);
        double[] p=Local(sketch,axis=="x"?0:x,axis=="y"?0:y,axis=="z"?0:z);
        md.SketchManager.CreateCircleByRadius(p[0],p[1],0,r*MM);
        End(sketch);
        Register(tag,Extrude(sketch,axis,axis=="x"?x:axis=="y"?y:z,h),rgb);
    }

    static void Tube(string tag,string axis,double x,double y,double z,double a,double b,double wall,double h,double[] rgb) {
        ISketch sketch=Begin(axis,0);
        double[] origin={axis=="x"?0:x,axis=="y"?0:y,axis=="z"?0:z};
        int u=axis=="x"?1:0, v=axis=="z"?1:2;
        for(int i=0;i<2;i++) {
            double inset=i*wall;
            double[] low=(double[])origin.Clone(),high=(double[])origin.Clone();
            low[u]-=a/2-inset; high[u]+=a/2-inset;
            low[v]-=b/2-inset; high[v]+=b/2-inset;
            double[] p=Local(sketch,low[0],low[1],low[2]),q=Local(sketch,high[0],high[1],high[2]);
            md.SketchManager.CreateCornerRectangle(p[0],p[1],0,q[0],q[1],0);
        }
        IFeature layout=End(sketch);layout.Name="SWFORGE_"+tag+"_section";
        Register(tag,Extrude(sketch,axis,axis=="x"?x:axis=="y"?y:z,h),rgb);
    }

    // 旋转轮廓上的点：pts 用 (径向, 轴向) 描述，换成世界坐标。
    static double[] RevWorld(string axis,double r,double a,double x,double y,double z) {
        if(axis=="x") return new double[]{x+a, y+r, z};   // 绕 X：轴向 X、径向 Y
        if(axis=="z") return new double[]{x+r, y, z+a};   // 绕 Z：径向 X、轴向 Z
        return new double[]{x+r, y+a, z};                 // 绕 Y：径向 X、轴向 Y
    }

    // 旋转轴上的点（t=-1/+1 取中心线两端）
    static double[] RevAxis(string axis,double x,double y,double z,double t) {
        if(axis=="x") return new double[]{x+t, y, z};
        if(axis=="z") return new double[]{x, y, z+t};
        return new double[]{x, y+t, z};
    }

    static void Revolve(string tag,double[] pts,string axis,double angle,double x,double y,double z,double[] rgb) {
        // 草图平面必须包含旋转轴：绕 X/Y 用 Front 面（法向 Z），绕 Z 用 Top 面（法向 Y）
        string planeNormal = (axis=="z") ? "y" : "z";
        double planeOffset = (axis=="z") ? y : z;
        ISketch sketch=Begin(planeNormal,planeOffset);
        int count=pts.Length/2;
        for(int i=0;i<count;i++) {
            int j=(i+1)%count;
            double[] wa=RevWorld(axis,pts[2*i],pts[2*i+1],x,y,z);
            double[] wb=RevWorld(axis,pts[2*j],pts[2*j+1],x,y,z);
            double[] a=Local(sketch,wa[0],wa[1],wa[2]);
            double[] b=Local(sketch,wb[0],wb[1],wb[2]);
            md.SketchManager.CreateLine(a[0],a[1],0,b[0],b[1],0);
        }
        double[] w0=RevAxis(axis,x,y,z,-1), w1=RevAxis(axis,x,y,z,1);
        double[] p0=Local(sketch,w0[0],w0[1],w0[2]), p1=Local(sketch,w1[0],w1[1],w1[2]);
        ISketchSegment center=(ISketchSegment)md.SketchManager.CreateCenterLine(p0[0],p0[1],0,p1[0],p1[1],0);
        End(sketch);
        ISelectData data=(ISelectData)((ISelectionMgr)md.SelectionManager).CreateSelectData();
        data.Mark=4;
        if(!center.Select4(true,(SelectData)data)) throw new Exception("选择旋转轴失败");
        IFeature f=(IFeature)md.FeatureManager.FeatureRevolve2(true,true,false,false,false,false,
            0,0,angle*Math.PI/180,0,false,false,0,0,0,0,0,MERGE,false,true);
        Register(tag,f,rgb);
    }

    static IBody2 FindBody(string tag) {
        object[] bodies=(object[])((IPartDoc)md).GetBodies2(0,false);
        if(bodies!=null) foreach(object o in bodies) if(((IBody2)o).Name==tag) return (IBody2)o;
        IFeature f;
        if(sources.TryGetValue(tag,out f)) return BodyOf(f);
        throw new Exception("找不到实体 "+tag);
    }

    static void Finish(string tag,double size,bool fillet,string axis,double minLength,double maxLength) {
        IBody2 body=FindBody(tag);
        object[] edges=(object[])body.GetEdges();
        if(edges==null || edges.Length==0) throw new Exception(tag+" 没有可修饰的边");
        md.ClearSelection2(true);
        int selected=0;
        foreach(object e in edges) {
            if(axis!="" || minLength>=0 || maxLength>=0) {
                IEdge edge=(IEdge)e;
                ICurve curve=(ICurve)edge.GetCurve();
                if(!curve.IsLine()) continue;
                IVertex start=(IVertex)edge.GetStartVertex(), end=(IVertex)edge.GetEndVertex();
                if(start==null || end==null) continue;
                double[] a=(double[])start.GetPoint(), b=(double[])end.GetPoint();
                double[] delta=new double[]{Math.Abs(b[0]-a[0]),Math.Abs(b[1]-a[1]),Math.Abs(b[2]-a[2])};
                double length=Math.Sqrt(delta[0]*delta[0]+delta[1]*delta[1]+delta[2]*delta[2])/MM;
                if(minLength>=0 && length<minLength-1e-6 || maxLength>=0 && length>maxLength+1e-6) continue;
                if(axis!="") {
                    int index=axis=="x"?0:axis=="y"?1:2;
                    if(Math.Abs(delta[index]/MM-length)>1e-6) continue;
                }
            }
            if(!((IEntity)e).Select4(true,null)) throw new Exception(tag+" 选边失败");
            selected++;
        }
        L(tag+" selected_edges="+selected);
        if(selected==0) throw new Exception(tag+" 没有符合 edges_rule 的直边");
        IFeature f = fillet ? (IFeature)md.FeatureManager.FeatureFillet3(2,size*MM,0,0,0,0,0,null,null,null,null,null,null,null)
                           : (IFeature)md.FeatureManager.InsertFeatureChamfer(4,1,size*MM,Math.PI/4,0,0,0,0);
        if(f==null) throw new Exception(tag+" "+(fillet?"圆角":"倒角")+"失败；尺寸可能过大或存在不适用的边");
        f.Name="SWFORGE_"+tag+(fillet?"_圆角":"_倒角");
        BodyOf(f).Name=tag;
        sources[tag]=f;
        okN++;
        L(tag+(fillet?" 圆角":" 倒角")+" -> True");
        md.ClearSelection2(true);
    }

    static double Volume(IBody2 body) {
        double[] m=(double[])body.GetMassProperties(1.0);
        if(m==null||m.Length<4||m[3]<=0)throw new Exception("实体体积读取失败");
        return m[3];
    }

    static IFeature CutSketch(ISketch sketch,string axis,double start,double depth,bool through,int direction,IBody2 target) {
        IMathVector normal=(IMathVector)math.CreateVector(new double[]{0,0,1});
        normal=(IMathVector)normal.MultiplyTransform(sketch.ModelToSketchTransform.Inverse());
        double sign=((double[])normal.ArrayData)[axis=="x"?0:axis=="y"?1:2];
        if(Math.Abs(sign)<0.99)throw new Exception("切除轴与草图法向不符");
        End(sketch);
        md.SketchManager.AddToDB=false;
        ISelectData select=(ISelectData)((ISelectionMgr)md.SelectionManager).CreateSelectData();
        select.Mark=8;
        if(!target.Select2(true,(SelectData)select))throw new Exception("切除目标实体选择失败");
        // Dir 按草图法向与目标世界轴计算，不能把所有轴硬编码为 false。
        IFeature f=(IFeature)md.FeatureManager.FeatureCut4(true,false,sign*direction>0,
            through?1:0,0,(through?1:depth)*MM,0,false,false,false,false,0,0,
            false,false,false,false,false,true,false,false,false,false,
            Math.Abs(start)<1e-9?0:3,Math.Abs(start)*MM,start*sign<0,false);
        md.SketchManager.AddToDB=true;
        if(f==null)throw new Exception("原生切除返回空值；孔口/方向或切除范围未与目标相交");
        return f;
    }

    static void RegisterCut(string tag,string target,IFeature f,double before) {
        IBody2 result=BodyOf(f);
        double after=Volume(result);
        if(before-after<=Math.Max(1e-15,before*1e-10))throw new Exception("切除未产生可验证的体积减少");
        bool warning=false;int error=f.GetErrorCode2(out warning);
        if(error!=0)throw new Exception("切除特征包含原生错误: "+error);
        f.Name="SWFORGE_"+tag;
        result.Name=target;
        sources[target]=f;sources[tag]=f;okN++;
        L(String.Format(System.Globalization.CultureInfo.InvariantCulture,
            "SWFORGE_CUT tag={0} target={1} before_mm3={2:R} after_mm3={3:R} removed_mm3={4:R}",
            tag,target,before*1e9,after*1e9,(before-after)*1e9));
        md.ClearSelection2(true);
    }

    static void CutBox(string tag,string target,string axis,double x0,double x1,double y0,double y1,double z0,double z1) {
        IBody2 body=FindBody(target);double before=Volume(body);
        ISketch sketch=Begin(axis,0);
        double[] a=Local(sketch,axis=="x"?0:x0,axis=="y"?0:y0,axis=="z"?0:z0);
        double[] b=Local(sketch,axis=="x"?0:x1,axis=="y"?0:y1,axis=="z"?0:z1);
        md.SketchManager.CreateCornerRectangle(a[0],a[1],0,b[0],b[1],0);
        double start=axis=="x"?x0:axis=="y"?y0:z0;
        double depth=axis=="x"?x1-x0:axis=="y"?y1-y0:z1-z0;
        RegisterCut(tag,target,CutSketch(sketch,axis,start,depth,false,1,body),before);
    }

    static void Hole(string tag,string target,string axis,double x,double y,double z,double diameter,double depth,double through,double direction) {
        IBody2 body=FindBody(target);double before=Volume(body);
        ISketch sketch=Begin(axis,0);
        double[] p=Local(sketch,axis=="x"?0:x,axis=="y"?0:y,axis=="z"?0:z);
        md.SketchManager.CreateCircleByRadius(p[0],p[1],0,diameter*MM/2);
        double start=axis=="x"?x:axis=="y"?y:z;
        IFeature feature=CutSketch(sketch,axis,start,depth,through>0,(int)direction,body);
        // 独立核对新特征确实含指定位置与半径的圆柱面。
        bool cylinder=false;
        foreach(object item in (object[])feature.GetFaces()) {
            ISurface surface=(ISurface)((IFace2)item).GetSurface();
            if(!surface.IsCylinder())continue;
            double[] c=(double[])surface.CylinderParams;
            int k=axis=="x"?0:axis=="y"?1:2;
            double[] center={x*MM,y*MM,z*MM};double delta=0;
            for(int i=0;i<3;i++)if(i!=k)delta+=(c[i]-center[i])*(c[i]-center[i]);
            if(Math.Abs(c[6]-diameter*MM/2)<1e-8&&Math.Sqrt(delta)<1e-8&&Math.Abs(c[3+k])>.999999)cylinder=true;
        }
        if(!cylinder)throw new Exception("新孔的圆柱面位置或直径回读不符");
        RegisterCut(tag,target,feature,before);
    }

    static void HoleGrid(string tag,string target,string axis,double x,double y,double z,double diameter,double depth,double through,double direction,double rows,double columns,double pitchU,double pitchV,string parentGrid) {
        IBody2 body=FindBody(target);double before=Volume(body);
        ISketch sketch=Begin(axis,0);
        double[] world={axis=="x"?0:x,axis=="y"?0:y,axis=="z"?0:z};
        double[] p=Local(sketch,world[0],world[1],world[2]);
        ISketchSegment seed=(ISketchSegment)md.SketchManager.CreateCircleByRadius(p[0],p[1],0,diameter*MM/2);
        md.SketchManager.AddToDB=false;
        md.ClearSelection2(true);
        ISketchPoint center=(ISketchPoint)((ISketchArc)seed).GetCenterPoint2();
        if(!center.Select4(false,null))throw new Exception("Cannot select hole seed center");
        md.SketchAddConstraints("sgFIXED");
        md.ClearSelection2(true);seed.Select4(false,null);
        ISldWorks app=application;
        bool inputDim=app.GetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate);
        IDisplayDimension display;
        try {
            app.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate,false);
            display=(IDisplayDimension)md.AddDiameterDimension2(p[0]+diameter*MM,p[1]+diameter*MM,0);
        } finally { app.SetUserPreferenceToggle((int)swUserPreferenceToggle_e.swInputDimValOnCreate,inputDim); }
        if(display==null)throw new Exception("Cannot dimension hole seed");
        IDimension dimension=(IDimension)display.GetDimension2(0);dimension.Name="HoleDiameter";
        if(rows*columns>1) {
            int u=axis=="x"?1:0,v=axis=="z"?1:2;
            double[] wu=(double[])world.Clone(),wv=(double[])world.Clone();wu[u]+=1;wv[v]+=1;
            double[] pu=Local(sketch,wu[0],wu[1],wu[2]),pv=Local(sketch,wv[0],wv[1],wv[2]);
            double au=Math.Atan2(pu[1]-p[1],pu[0]-p[0]),av=Math.Atan2(pv[1]-p[1],pv[0]-p[0]);
            if(au<0)au+=2*Math.PI;if(av<0)av+=2*Math.PI;
            md.ClearSelection2(true);seed.Select4(false,null);
            if(!md.SketchManager.CreateLinearSketchStepAndRepeat((int)columns,(int)rows,pitchU*MM,pitchV*MM,au,av,"",columns>1,rows>1,true,columns>1,rows>1))
                throw new Exception("Native sketch pattern failed; no expanded-hole fallback");
        }
        md.SketchManager.AddToDB=true;
        IFeature feature=CutSketch(sketch,axis,axis=="x"?x:axis=="y"?y:z,depth,through>0,(int)direction,body);
        // Check every expected cylinder, not just the aggregate volume or API result.
        object[] faces=(object[])feature.GetFaces();int matched=0;
        for(int r=0;r<(int)rows;r++)for(int c=0;c<(int)columns;c++) {
            double[] expected={x*MM,y*MM,z*MM};int k=axis=="x"?0:axis=="y"?1:2;
            expected[axis=="x"?1:0]+=c*pitchU*MM;expected[axis=="z"?1:2]+=r*pitchV*MM;
            bool found=false;
            foreach(object item in faces) {
                ISurface surface=(ISurface)((IFace2)item).GetSurface();if(!surface.IsCylinder())continue;
                double[] cp=(double[])surface.CylinderParams;double delta=0;
                for(int i=0;i<3;i++)if(i!=k)delta+=(cp[i]-expected[i])*(cp[i]-expected[i]);
                if(Math.Abs(cp[6]-diameter*MM/2)<1e-8&&Math.Sqrt(delta)<1e-8&&Math.Abs(cp[3+k])>.999999)found=true;
            }
            if(!found)throw new Exception("Hole grid cylinder readback mismatch: row="+r+" col="+c);matched++;
        }
        RegisterCut(tag,target,feature,before);
        for(IFeature sub=(IFeature)feature.GetFirstSubFeature();sub!=null;sub=(IFeature)sub.GetNextSubFeature())
            if(sub.GetTypeName2()=="ProfileFeature") {
                sub.Name="SWFORGE_"+tag+"_layout";int linear=0,counts=0;
                List<string> linked=new List<string>();
                for(IDisplayDimension dd=(IDisplayDimension)sub.GetFirstDisplayDimension();dd!=null;dd=(IDisplayDimension)sub.GetNextDisplayDimension(dd)) {
                    IDimension d=(IDimension)dd.GetDimension2(0);
                    if(d.GetType()==2) {
                        string countName=columns>1&&counts==0?"Columns":"Rows";
                        double expectedCount=countName=="Columns"?columns:rows;
                        if(Math.Abs(d.SystemValue-expectedCount)>1e-8)throw new Exception("Pattern count mapping mismatch");
                        d.Name=countName;linked.Add(countName);counts++;continue;
                    }
                    if(d.GetType()!=0||d.Name=="HoleDiameter")continue;
                    string name=columns>1&&linear==0?"PitchU":"PitchV";
                    double expected=name=="PitchU"?pitchU:pitchV;
                    if(Math.Abs(d.SystemValue-expected*MM)>1e-8)throw new Exception("Pattern dimension mapping mismatch");
                    d.Name=name;linked.Add(name);linear++;
                }
                if(linear!=(columns>1?1:0)+(rows>1?1:0))throw new Exception("Missing native pattern spacing dimensions");
                if(counts!=linear)throw new Exception("Missing native pattern count dimensions");
                if(parentGrid!="") {
                    IEquationMgr equations=(IEquationMgr)md.GetEquationMgr();
                    foreach(string name in linked) {
                        string equation="\""+name+"@"+sub.Name+"\" = \""+name+"@SWFORGE_"+parentGrid+"_layout\"";
                        if(equations.Add2(-1,equation,true)<0)throw new Exception("Counterbore pattern link rejected: "+equation);
                    }
                    equations.EvaluateAll();
                }
            }
        L("SWFORGE_GRID tag="+tag+" cylinders_verified="+matched+" strategy=native_sketch_pattern");
    }

    static void Paint(object[] bodies) {
        int total=0,requested=0,verified=0;
        if(bodies!=null) foreach(object item in bodies) {
            IBody2 body=(IBody2)item;
            object[] faces=(object[])body.GetFaces();
            if(faces==null) continue;
            total+=faces.Length;
            double[] rgb;
            if(!colors.TryGetValue(body.Name,out rgb) || rgb==null) continue;
            double[] values=new double[]{rgb[0],rgb[1],rgb[2],0.78,0.42,0.16,0.22,0,0};
            foreach(object o in faces) {
                requested++;
                try {
                    IFace2 face=(IFace2)o;
                    face.SetMaterialPropertyValues2(values,1,null);
                    double[] got=(double[])face.GetMaterialPropertyValues2(1,null);
                    // SW stores display RGB in 8-bit channels.
                    double rgbTolerance=1.0/255.0+1e-9;
                    if(got!=null && got.Length>=3 && Math.Abs(got[0]-rgb[0])<=rgbTolerance &&
                       Math.Abs(got[1]-rgb[1])<=rgbTolerance && Math.Abs(got[2]-rgb[2])<=rgbTolerance) verified++;
                } catch(Exception e) { L("配色: "+e.Message); }
            }
        }
        L("SWFORGE_COLOR total="+total+" requested="+requested+" verified="+verified);
    }

    // 连接 SolidWorks。
    // ① GetActiveObject 只找得到「已注册到 ROT」的实例 —— 用户从桌面/开始菜单
    //    启动的 SW 会注册；由 COM Dispatch 从后台拉起的不会（实测 MK_E_UNAVAILABLE）。
    // ② 因此必须有回退：CreateInstance 走 CoCreateInstance，SW 是单实例应用，
    //    通常会挂到已在运行的实例上。
    // ③ 两者都失败时，给使用者一条能照着做的提示，而不是抛 0x800401E3。
    static ISldWorks Connect() {
        string rotErr="", createErr="";
        try {
            ISldWorks s=SwforgeConnection.Active();
            if(IsUsable(s)) { L("SWFORGE_CONNECT via=GetActiveObject"); return s; }
            rotErr="对象不可用（返回空壳）";
        } catch(Exception e) { rotErr=e.GetType().Name+":"+e.Message; }
        L("SWFORGE_CONNECT rot_failed="+rotErr);

        try {
            ISldWorks s=SwforgeConnection.Connect();
            if(IsUsable(s)) { L("SWFORGE_CONNECT via=Connect"); return s; }
            createErr="SolidWorks 未就绪";
        } catch(Exception e) { createErr=e.GetType().Name+":"+e.Message; }
        L("SWFORGE_CONNECT create_failed="+createErr);

        throw new Exception(
            "无法连接 SolidWorks。\n"+
            "  GetActiveObject: "+rotErr+"\n"+
            "  CreateInstance : "+createErr+"\n"+
            "请按顺序检查：\n"+
            "  1) 手动启动 SolidWorks，等主窗口完全出现（不是启动画面）后再运行；\n"+
            "  2) 任务管理器里只应有一个 SLDWORKS.EXE；\n"+
            "  3) 本程序与 SolidWorks 位数必须一致（都用 64 位）；\n"+
            "  4) 不要出现「本程序以管理员运行、SolidWorks 不是」的权限错配。");
    }

    // 真实往返探测：空壳代理在取属性时就会抛异常，这样能区分「连上了」和「拿了个壳」。
    static bool IsUsable(ISldWorks s) {
        if(s==null) return false;
        try {
            string rev=s.RevisionNumber();
            if(String.IsNullOrEmpty(rev)) return false;
            int n=s.GetDocumentCount();
            return n>=0;
        } catch { return false; }
    }

    static void GuardOutputName(ISldWorks sw,string output,IModelDoc2 owned=null) {
        string name=System.IO.Path.GetFileName(output);
        string stem=System.IO.Path.GetFileNameWithoutExtension(output);
        foreach(object item in (object[])sw.GetDocuments()??new object[0]) {
            IModelDoc2 doc=(IModelDoc2)item;
            if(Object.ReferenceEquals(doc,owned)||doc.GetType()!=1)continue;
            string path=doc.GetPathName();
            string title=doc.GetTitle();
            bool conflict=String.IsNullOrEmpty(path)
                ? String.Equals(title,stem,StringComparison.OrdinalIgnoreCase) ||
                  String.Equals(title,name,StringComparison.OrdinalIgnoreCase)
                : String.Equals(System.IO.Path.GetFileName(path),name,StringComparison.OrdinalIgnoreCase);
            if(conflict)throw new Exception("A same-named part is already open: "+(String.IsNullOrEmpty(path)?title:path));
        }
    }

    public static string Run() {
        int nb=0,err=0,warn=0;
        bool saved=false;
        ISldWorks sw=null;
        try {
            sw=Connect();application=sw;
            int before=sw.GetDocumentCount();
            L("SWFORGE_DOCUMENTS before="+before+" limit="+__MAX_DOCUMENTS__);
            if(before>=__MAX_DOCUMENTS__) throw new Exception("SW 文档数量达到上限，未创建新文档");
            math=(IMathUtility)sw.GetMathUtility();
            string year=(Int32.Parse(sw.RevisionNumber().Split('.')[0])+1992).ToString();
            string dir=System.IO.Path.Combine(System.Environment.GetFolderPath(
                System.Environment.SpecialFolder.CommonApplicationData),"SOLIDWORKS","SOLIDWORKS "+year,"templates");
            string tpl=sw.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart);
            string custom=System.Environment.GetEnvironmentVariable("SW_TEMPLATE_DIR");
            if(!String.IsNullOrEmpty(custom)) {
                string overridePath=System.IO.Path.Combine(custom,"gb_part.prtdot");
                if(System.IO.File.Exists(overridePath)) tpl=overridePath;
            } else if(!String.IsNullOrEmpty(System.Environment.GetEnvironmentVariable("SWFORGE_SW_YEAR"))) {
                string local=System.IO.Path.Combine(dir,"gb_part.prtdot");
                if(System.IO.File.Exists(local)) tpl=local;
            }
            if((String.IsNullOrEmpty(tpl) || !System.IO.File.Exists(tpl)) && System.IO.Directory.Exists(dir)) {
                string[] files=System.IO.Directory.GetFiles(dir,"*.prtdot");
                if(files.Length>0) tpl=files[0];
            }
            if(String.IsNullOrEmpty(tpl) || !System.IO.File.Exists(tpl)) throw new Exception("找不到零件模板");
            if(System.IO.File.Exists(__OUT__))throw new Exception("输出文件已存在，拒绝覆盖");
            GuardOutputName(sw,__OUT__);
            L("模板: "+tpl);
            md=(IModelDoc2)sw.NewDocument(tpl,0,0,0);
            if(md==null) throw new Exception("新建零件文档失败");
            md.SketchManager.AddToDB=true;
__BODY__
            md.SketchManager.AddToDB=false;
            bool rebuilt=md.EditRebuild3();
            __EDITABLE_PASS__
            if(verifiedNative.Count>0 && !rebuilt)throw new Exception("Final rebuild failed");
            foreach(IFeature f in verifiedNative)CheckNative(f.Name,f);
            __COMMUNITY_FLATTEN__
            md.ClearSelection2(true);
            object[] bodies=(object[])((IPartDoc)md).GetBodies2(0,false);
            nb=bodies==null?0:bodies.Length;
            if(nb==0) throw new Exception("没有生成实体");
            Paint(bodies);
            double[] bb=new double[]{Double.MaxValue,Double.MaxValue,Double.MaxValue,Double.MinValue,Double.MinValue,Double.MinValue};
            foreach(object o in bodies) {
                double[] b=(double[])((IBody2)o).GetBodyBox();
                for(int i=0;i<3;i++) { bb[i]=Math.Min(bb[i],b[i]); bb[i+3]=Math.Max(bb[i+3],b[i+3]); }
            }
            L(String.Format(System.Globalization.CultureInfo.InvariantCulture,"包络 X {0:F3}~{3:F3} Y {1:F3}~{4:F3} Z {2:F3}~{5:F3}",
                bb[0]*1000,bb[1]*1000,bb[2]*1000,bb[3]*1000,bb[4]*1000,bb[5]*1000));
            // ---- v0.5 物理材料赋值 + 质量回读 ----
            // 此前 material 只是写进 spec 的标签，从未赋给 SW，
            // 导致非 Q235 零件的质量/质心/体积全部按默认材料算。
            try {
                IPartDoc pd=(IPartDoc)md;
                pd.SetMaterialPropertyName2("",__MATERIAL_DB__,__MATERIAL__);
                string mdb="";
                string got=pd.GetMaterialPropertyName2("",out mdb);
                L("SWFORGE_MATERIAL requested="+__MATERIAL__+" got="+got+" db="+mdb);
                if(String.IsNullOrEmpty(got)) L("SWFORGE_MATERIAL WARN 赋值后回读为空，材料可能未生效");
            } catch(Exception e) { L("SWFORGE_MATERIAL failed="+e.Message); }
            try {
                MassProperty mp=(MassProperty)md.Extension.CreateMassProperty();
                L(String.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "SWFORGE_MASS mass_kg={0:F9} volume_mm3={1:F3}",mp.Mass,mp.Volume*1e9));
            } catch(Exception e) { L("SWFORGE_MASS failed="+e.Message); }
            md.ShowNamedView2("",(int)swStandardViews_e.swIsometricView);
            md.ViewZoomtofit2();
            md.GraphicsRedraw2();
            if(System.IO.File.Exists(__OUT__))throw new Exception("输出路径被其他任务占用，拒绝覆盖");
            GuardOutputName(sw,__OUT__,md);
            saved=md.Extension.SaveAs(__OUT__,0,1,null,ref err,ref warn);
            L("保存 "+saved+" err="+err+" warnings="+warn);
        } catch(Exception e) { badN++; L("ERROR "+e.ToString()); }
        finally {
            // 兜底恢复系统选项：任何中途异常都不许把用户的"草图推理"永久关掉
            try { InferenceRestore(); } catch {}
            if(md!=null) { try { md.SketchManager.AddToDB=false; } catch {} }
            if(md!=null && (!saved || !__KEEP_OPEN__)) {
                try { sw.CloseDoc(md.GetTitle()); L("SWFORGE_CLOSED owned_document=True"); }
                catch(Exception e) { L("关闭本轮文档失败: "+e.Message); }
            }
            if(sw!=null) { try { L("SWFORGE_DOCUMENTS after="+sw.GetDocumentCount()); } catch {} }
            if(sw!=null) { try {
                using(var process=System.Diagnostics.Process.GetProcessById(sw.GetProcessID()))
                    L("SWFORGE_MEMORY working_set_bytes="+process.WorkingSet64);
            } catch {} }
            L("SWFORGE_RESULT ok="+okN+" failed="+badN+" bodies="+nb+" saved="+saved+" errors="+err);
            System.IO.File.WriteAllText(__LOG__,log.ToString(),Encoding.UTF8);
        }
        return log.ToString();
    }
}
'''

_PS_RUNNER = r"""$ErrorActionPreference='Stop'
[System.Reflection.Assembly]::LoadFrom('{dll}') | Out-Null
[System.Reflection.Assembly]::LoadFrom('{cst}') | Out-Null
Add-Type -TypeDefinition ([System.IO.File]::ReadAllText('{cs}', [System.Text.Encoding]::UTF8)) `
  -ReferencedAssemblies '{dll}','{cst}','System.Core.dll' -ErrorAction Stop
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
Write-Output ([{cls}]::Run())
"""


def _cls_name(src):
    m=re.search(r"public class (\w+)",src)
    return m[1] if m else "Builder"


def _find_sw_dir():
    from .sw_target import install_dir
    return install_dir()
