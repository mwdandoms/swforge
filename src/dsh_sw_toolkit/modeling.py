# -*- coding: utf-8 -*-
"""声明式零件建模，单位 mm，坐标直接对应 SolidWorks 世界 X/Y/Z。

Python 描述经 C# Interop 早期绑定执行。v0.3 支持三轴圆柱、绕 Y 旋转
闭合多边形、按源实体 tag 对全部边圆角/45°倒角。合并后的实体采用最后
一个构成实体的颜色；精细面级分色可另外调用 colors.apply_rules。
"""
from __future__ import annotations

import json
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


class PartBuilder:
    """建模声明，不在添加形体时连接 SW。所有 tag 在单个构建器中唯一。"""

    def __init__(self, path: str, material: str = "Q235", merge: bool = False, material_db: str | None = None,
                 log: str | None = None):
        self.path = os.path.abspath(path)
        self.material = material
        # 材质库路径：None 表示自动（GB 牌号用生成的库，其它交给 SW 默认库）
        self.material_db = material_db
        self.merge = bool(merge)
        self.log_path = os.path.abspath(log or os.path.splitext(self.path)[0] + ".buildlog.txt")
        self._boxes: list[_Box] = []
        self._shapes = []
        self._finishes = []
        self._tags = set()

    def _add(self, tag, kind, values, color):
        tag = str(tag)
        if not tag.strip() or tag in self._tags:
            raise ValueError(f"tag 必须非空且唯一：{tag!r}")
        rgb = _color(color)
        self._tags.add(tag)
        self._shapes.append((kind, tag, values, rgb))
        return rgb

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

    def fillet(self, tag, r, edges_rule=None):
        """对源 tag 所属实体的全部边倒圆角。过大的半径构建失败，不保存半成品。"""
        return self._finish(tag, "Fillet", _number(r, "r", True),edges_rule)

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
        x0,x1,z0,z1 = cx-sx/2,cx+sx/2,cz-sz/2,cz+sz/2
        self.box(tag+"_前",x0,x1,y0,y1,z0,z0+wall,color)
        self.box(tag+"_后",x0,x1,y0,y1,z1-wall,z1,color)
        self.box(tag+"_左",x0,x0+wall,y0,y1,z0+wall,z1-wall,color)
        self.box(tag+"_右",x1-wall,x1,y0,y1,z0+wall,z1-wall,color)
        return self

    def tube_z(self, tag, z0, z1, cx, cy, sx, sy, wall=6.3, color="yellow", inset=0.0):
        self._tube_check(z1-z0, sx, sy, wall, inset)
        x0,x1,y0,y1 = cx-sx/2,cx+sx/2,cy-sy/2,cy+sy/2
        self.box(tag+"_下",x0,x1,y0,y0+wall,z0,z1,color)
        self.box(tag+"_上",x0,x1,y1-wall,y1,z0,z1,color)
        self.box(tag+"_左",x0,x0+wall,y0+wall,y1-wall,z0,z1,color)
        self.box(tag+"_右",x1-wall,x1,y0+wall,y1-wall,z0,z1,color)
        return self

    def tube_x(self, tag, x0, x1, cy, cz, sy, sz, wall=6.3, color="yellow", inset=0.0):
        self._tube_check(x1-x0, sy, sz, wall, inset)
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
        return len(self._shapes) + len(self._finishes)

    def render_cs(self, *, paint=True, _log_path=None, keep_open=True, max_documents=8):
        if isinstance(max_documents, bool) or not isinstance(max_documents, int) or max_documents < 0:
            raise ValueError("max_documents 必须为非负整数（0 表示不允许再建文档）")
        calls = []
        for kind, tag, vals, rgb in self._shapes:
            args = [_cs_string(tag)]
            if kind == "Revolve":
                pts, axis, angle, x, y, z = vals
                args.append("new double[]{" + ",".join(_cs_num(v) for p in pts for v in p) + "}")
                args.append(_cs_string(axis))
                args.extend(_cs_num(v) for v in (angle,x,y,z))
            else:
                args.extend(_cs_string(v) if isinstance(v,str) else _cs_num(v) for v in vals)
            args.append("null" if rgb is None or not paint else
                        "new double[]{" + ",".join(_cs_num(v) for v in rgb) + "}")
            calls.append("        " + kind + "(" + ",".join(args) + ");")
        for kind, tag, size,rule in self._finishes:
            calls.append(f"        Finish({_cs_string(tag)},{_cs_num(size)},{str(kind == 'Fillet').lower()},"
                         f"{_cs_string(rule.get('axis',''))},{_cs_num(rule.get('min_length_mm',-1))},"
                         f"{_cs_num(rule.get('max_length_mm',-1))});")
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
                        "__BODY__": "\n".join(calls)}
        src = _CS_TEMPLATE
        for token, value in replacements.items():
            src = src.replace(token,value)
        return src

    def build(self, timeout_s=900, paint=True, keep_open=True, max_documents=8):
        start = time.monotonic()
        if not self._shapes:
            return BuildResult(False, self.path, error="没有任何形体")
        if os.path.splitext(self.path)[1].lower() != ".sldprt":
            return BuildResult(False, self.path, error="输出文件必须使用 .SLDPRT 扩展名")
        sw_dir = _find_sw_dir()
        if not sw_dir:
            return BuildResult(False, self.path, error="找不到 SolidWorks 安装目录")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        output = ""
        log = ""
        code = -1
        try:
            with tempfile.TemporaryDirectory(prefix="dshsw_") as work:
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
        m = re.search(r"DSHSW_RESULT ok=(\d+) failed=(\d+) bodies=(\d+) saved=(True|False) errors=(\d+)",log)
        c = re.search(r"DSHSW_COLOR total=(\d+) requested=(\d+) verified=(\d+)",log)
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
        mat = re.search(r"DSHSW_MATERIAL requested=(\S*) got=(\S*)",log)
        mass = re.search(r"DSHSW_MASS mass_kg=([\d.eE+-]+) volume_mm3=([\d.eE+-]+)",log)
        result.material_requested = self.material
        if mat:
            result.material_applied = "" if mat[2] in ("", "got=") else mat[2]
        if "DSHSW_MATERIAL failed=" in log:
            result.material_error = log.split("DSHSW_MATERIAL failed=",1)[1].splitlines()[0][:300]
        elif result.material_requested and not result.material_applied:
            result.material_error = "材料赋值后回读为空"
        if mass:
            try:
                result.mass_kg = float(mass[1]); result.volume_mm3 = float(mass[2])
            except ValueError:
                pass
        from datetime import datetime,timezone
        before=re.search(r'DSHSW_DOCUMENTS before=(\d+)',log)
        after=re.search(r'DSHSW_DOCUMENTS after=(\d+)',log)
        memory=re.search(r'DSHSW_MEMORY working_set_bytes=(\d+)',log)
        with open(self.log_path+'.operations.jsonl','a',encoding='utf-8') as stream:
            stream.write(json.dumps({'time_utc':datetime.now(timezone.utc).isoformat(),
                'operation':'build','path':self.path,'ok':result.ok,'elapsed_s':result.elapsed_s,
                'documents_before':int(before[1]) if before else None,
                'documents_after':int(after[1]) if after else None,
                'working_set_bytes':int(memory[1]) if memory else None,
                'keep_open':keep_open,'max_documents':max_documents,
                'features_ok':good,'features_failed':bad,'bodies':bodies,
                'material_requested':result.material_requested,'material_applied':result.material_applied,
                'mass_kg':result.mass_kg,'volume_mm3':result.volume_mm3,
                'paint_error':result.paint_error,'error':result.error},ensure_ascii=False)+'\n')
        return result


_CS_TEMPLATE = r'''
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public class __CLASS__ {
    const double MM = 0.001;
    const bool MERGE = __MERGE__;
    static IModelDoc2 md;
    static IMathUtility math;
    static int okN, badN;
    static StringBuilder log = new StringBuilder();
    static Dictionary<string,double[]> colors = new Dictionary<string,double[]>();
    static Dictionary<string,IFeature> sources = new Dictionary<string,IFeature>();
    static void L(string s) { log.AppendLine(s); }

    static IFeature Datum(string axis) {
        // 标准模板前三个 RefPlane 按 Front,Top,Right 排列；不依赖系统语言。
        int wanted = axis == "x" ? 2 : axis == "y" ? 1 : 0;
        int i = 0;
        for (IFeature f=(IFeature)md.FirstFeature(); f!=null; f=(IFeature)f.GetNextFeature()) {
            if (f.GetTypeName2()=="RefPlane" && i++ == wanted) return f;
        }
        throw new Exception("标准模板缺少 " + axis + " 轴基准面");
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
        md.SketchManager.InsertSketch(true);
        ISketch sketch = (ISketch)md.SketchManager.ActiveSketch;
        if (sketch==null) throw new Exception("进入草图失败");
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
        f.Name="DSH_"+tag;
        sources[tag]=f;
        IBody2 body=BodyOf(f);
        body.Name=tag;
        colors[tag]=rgb;
        okN++;
        L(tag+" -> True");
    }

    static void Box(string tag,double x0,double x1,double y0,double y1,double z0,double z1,double[] rgb) {
        ISketch sketch=Begin("y",0);
        double[] a=Local(sketch,x0,0,z0), b=Local(sketch,x1,0,z1);
        md.SketchManager.CreateCornerRectangle(a[0],a[1],0,b[0],b[1],0);
        End(sketch);
        Register(tag,Extrude(sketch,"y",y0,y1-y0),rgb);
    }

    static void Cylinder(string tag,string axis,double x,double y,double z,double r,double h,double[] rgb) {
        ISketch sketch=Begin(axis,0);
        double[] p=Local(sketch,axis=="x"?0:x,axis=="y"?0:y,axis=="z"?0:z);
        md.SketchManager.CreateCircleByRadius(p[0],p[1],0,r*MM);
        End(sketch);
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
        f.Name="DSH_"+tag+(fillet?"_圆角":"_倒角");
        BodyOf(f).Name=tag;
        sources[tag]=f;
        okN++;
        L(tag+(fillet?" 圆角":" 倒角")+" -> True");
        md.ClearSelection2(true);
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
        L("DSHSW_COLOR total="+total+" requested="+requested+" verified="+verified);
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
            ISldWorks s=(ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
            if(IsUsable(s)) { L("DSHSW_CONNECT via=GetActiveObject"); return s; }
            rotErr="对象不可用（返回空壳）";
        } catch(Exception e) { rotErr=e.GetType().Name+":"+e.Message; }
        L("DSHSW_CONNECT rot_failed="+rotErr);

        try {
            Type t=Type.GetTypeFromProgID("SldWorks.Application");
            if(t==null) { createErr="ProgID 未注册（SolidWorks 未安装或未注册 COM）"; }
            else {
                ISldWorks s=(ISldWorks)Activator.CreateInstance(t);
                if(IsUsable(s)) { L("DSHSW_CONNECT via=CreateInstance"); return s; }
                createErr="对象不可用（返回空壳，常见于 SW 尚未完成启动）";
            }
        } catch(Exception e) { createErr=e.GetType().Name+":"+e.Message; }
        L("DSHSW_CONNECT create_failed="+createErr);

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

    public static string Run() {
        int nb=0,err=0,warn=0;
        bool saved=false;
        ISldWorks sw=null;
        try {
            sw=Connect();
            int before=sw.GetDocumentCount();
            L("DSHSW_DOCUMENTS before="+before+" limit="+__MAX_DOCUMENTS__);
            if(before>=__MAX_DOCUMENTS__) throw new Exception("SW 文档数量达到上限，未创建新文档");
            math=(IMathUtility)sw.GetMathUtility();
            string tpl=sw.GetUserPreferenceStringValue((int)swUserPreferenceStringValue_e.swDefaultTemplatePart);
            if(String.IsNullOrEmpty(tpl) || !System.IO.File.Exists(tpl)) {
                foreach(string version in new string[]{"2026","2025","2024","2023","2022","2021","2020"}) {
                    string dir=@"C:\ProgramData\SOLIDWORKS\SOLIDWORKS "+version+@"\templates";
                    if(!System.IO.Directory.Exists(dir)) continue;
                    string[] files=System.IO.Directory.GetFiles(dir,"*.prtdot");
                    if(files.Length>0) { tpl=files[0]; break; }
                }
            }
            if(String.IsNullOrEmpty(tpl) || !System.IO.File.Exists(tpl)) throw new Exception("找不到零件模板");
            L("模板: "+tpl);
            md=(IModelDoc2)sw.NewDocument(tpl,0,0,0);
            if(md==null) throw new Exception("新建零件文档失败");
            md.SketchManager.AddToDB=true;
__BODY__
            md.SketchManager.AddToDB=false;
            md.EditRebuild3();
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
                L("DSHSW_MATERIAL requested="+__MATERIAL__+" got="+got+" db="+mdb);
                if(String.IsNullOrEmpty(got)) L("DSHSW_MATERIAL WARN 赋值后回读为空，材料可能未生效");
            } catch(Exception e) { L("DSHSW_MATERIAL failed="+e.Message); }
            try {
                MassProperty mp=(MassProperty)md.Extension.CreateMassProperty();
                L(String.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "DSHSW_MASS mass_kg={0:F9} volume_mm3={1:F3}",mp.Mass,mp.Volume*1e9));
            } catch(Exception e) { L("DSHSW_MASS failed="+e.Message); }
            md.ShowNamedView2("",(int)swStandardViews_e.swIsometricView);
            md.ViewZoomtofit2();
            md.GraphicsRedraw2();
            saved=md.Extension.SaveAs(__OUT__,0,1,null,ref err,ref warn);
            L("保存 "+saved+" err="+err+" warnings="+warn);
        } catch(Exception e) { badN++; L("ERROR "+e.ToString()); }
        finally {
            if(md!=null) { try { md.SketchManager.AddToDB=false; } catch {} }
            if(md!=null && (!saved || !__KEEP_OPEN__)) {
                try { sw.CloseDoc(md.GetTitle()); L("DSHSW_CLOSED owned_document=True"); }
                catch(Exception e) { L("关闭本轮文档失败: "+e.Message); }
            }
            if(sw!=null) { try { L("DSHSW_DOCUMENTS after="+sw.GetDocumentCount()); } catch {} }
            if(sw!=null) { try {
                using(var process=System.Diagnostics.Process.GetProcessById(sw.GetProcessID()))
                    L("DSHSW_MEMORY working_set_bytes="+process.WorkingSet64);
            } catch {} }
            L("DSHSW_RESULT ok="+okN+" failed="+badN+" bodies="+nb+" saved="+saved+" errors="+err);
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
  -ReferencedAssemblies '{dll}','{cst}' -ErrorAction Stop
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
Write-Output ([{cls}]::Run())
"""


def _cls_name(src):
    m=re.search(r"public class (\w+)",src)
    return m[1] if m else "Builder"


def _find_sw_dir():
    cands=[os.environ.get("SW_INSTALL_DIR", ""),os.environ.get("SOLIDWORKS_DIR", "")]
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
            for year in range(2026,2019,-1):
                try:
                    with winreg.OpenKey(hive,rf"SOFTWARE\SolidWorks\SOLIDWORKS {year}\Setup") as key:
                        cands.append(winreg.QueryValueEx(key,"SolidWorks Folder")[0])
                except OSError:
                    pass
    except ImportError:
        pass
    for letter in ("E","D","C","F"):
        for year in range(2026,2019,-1):
            cands.append(rf"{letter}:\SW{year}\SOLIDWORKS")
        cands.append(rf"{letter}:\Program Files\SOLIDWORKS Corp\SOLIDWORKS")
    return next((p for p in cands if p and os.path.isfile(os.path.join(p,"SolidWorks.Interop.sldworks.dll"))),None)
