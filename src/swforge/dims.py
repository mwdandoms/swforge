# -*- coding: utf-8 -*-
"""总尺寸标注：给工程图补上「总长 / 总宽 / 总高」。

为什么需要单独这一步
--------------------
`InsertModelAnnotations4` 插入的是**模型驱动尺寸**，一个由「底板 + 4 板拼管」
组成的零件只有十来个驱动尺寸，而且会跨视图去重 —— 实测上限 18 个，
且常常只有竖向，**不包含总长/总宽**。这样的图拿去车间没法下料。

本模块显式地：
1. 取每个视图的**可见顶点**（`IView.GetVisibleEntities2`，类型 2）
2. 按模型坐标找 X / Y 方向的极值顶点
3. 选中这对顶点，`AddHorizontalDimension2` / `AddVerticalDimension2` 生成总尺寸
4. 把尺寸线放到视图轮廓外面，不压几何

为什么用 C#
----------
`IEntity.Select4` 与 `IVertex.GetPoint` 在 pywin32 后期绑定下报「类型不匹配」，
C# 早期绑定正常。这与配合模块是同一类原因。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import uuid

from .session import get_session, _value, SWError

__all__ = ["add_overall_dimensions"]


_CS = r'''
using System;
using System.Text;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public class __CLASS__ {
    static StringBuilder log = new StringBuilder();
    static void L(string s) { log.AppendLine(s); }

    static ISldWorks Connect() {
        string e1 = "", e2 = "";
        try {
            ISldWorks s = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application");
            if (Usable(s)) return s;
            e1 = "空壳";
        } catch (Exception ex) { e1 = ex.GetType().Name; }
        try {
            Type t = Type.GetTypeFromProgID("SldWorks.Application");
            if (t != null) {
                ISldWorks s = (ISldWorks)Activator.CreateInstance(t);
                if (Usable(s)) return s;
                e2 = "空壳";
            }
        } catch (Exception ex) { e2 = ex.GetType().Name; }
        throw new Exception("无法连接 SolidWorks（" + e1 + " / " + e2 + "）");
    }

    static bool Usable(ISldWorks s) {
        if (s == null) return false;
        try { return !String.IsNullOrEmpty(s.RevisionNumber()) && s.GetDocumentCount() >= 0; }
        catch { return false; }
    }

    class V {
        public IEntity ent;
        public double x, y, z;
    }

    public static string Run() {
        try {
            ISldWorks sw = Connect();
            IModelDoc2 md = (IModelDoc2)sw.ActiveDoc;
            if (md == null || md.GetType() != (int)swDocumentTypes_e.swDocDRAWING)
                throw new Exception("当前文档不是工程图");

            double gap = __GAP__ / 1000.0;          // 尺寸线离视图轮廓的距离（米）
            int done = 0, tried = 0;

            IDrawingDoc dd = (IDrawingDoc)md;
            IView sheet = (IView)dd.GetFirstView();
            IView v = sheet == null ? null : (IView)sheet.GetNextView();
            int guard = 0;
            while (v != null && guard++ < 20) {
                string vname = v.Name;
                double[] o = (double[])v.GetOutline();
                if (o == null || o.Length < 4) { v = (IView)v.GetNextView(); continue; }

                System.Collections.Generic.List<V> pts = new System.Collections.Generic.List<V>();
                string via = "vertex";

                // 只在最后什么都没标出来时才打实体统计，正常路径不刷日志

                // ---- 路径一：可见顶点（方盒类零件走这里，最准）
                int n = v.GetVisibleEntityCount2(null, (int)swViewEntityType_e.swViewEntityType_Vertex);
                if (n >= 2) {
                    object[] raw = (object[])v.GetVisibleEntities2(null, (int)swViewEntityType_e.swViewEntityType_Vertex);
                    foreach (object eo in raw ?? new object[0]) {
                        try {
                            IEntity ent = (IEntity)eo;
                            IVertex vt = (IVertex)ent;
                            double[] p = (double[])vt.GetPoint();
                            V item = new V();
                            item.ent = ent; item.x = p[0]; item.y = p[1]; item.z = p[2];
                            pts.Add(item);
                        } catch { }
                    }
                }

                // ---- 路径二：没有顶点就退回边端点
                // 圆柱/回转体的侧视只有侧影轮廓线，没有实体顶点，此时抓边再取端点。
                // 注意选的是「边」而不是端点 —— 两条平行边之间的距离才是正确尺寸。
                if (pts.Count < 2) {
                    via = "edge";
                    int ne = v.GetVisibleEntityCount2(null, (int)swViewEntityType_e.swViewEntityType_Edge);
                    if (ne > 0) {
                        object[] rawe = (object[])v.GetVisibleEntities2(null, (int)swViewEntityType_e.swViewEntityType_Edge);
                        foreach (object eo in rawe ?? new object[0]) {
                            try {
                                IEntity ent = (IEntity)eo;
                                IEdge ed = (IEdge)ent;
                                IVertex sv = (IVertex)ed.GetStartVertex();
                                IVertex ev = (IVertex)ed.GetEndVertex();
                                if (sv != null) {
                                    double[] ps = (double[])sv.GetPoint();
                                    V a = new V(); a.ent = ent; a.x = ps[0]; a.y = ps[1]; a.z = ps[2];
                                    pts.Add(a);
                                }
                                if (ev != null) {
                                    double[] pe = (double[])ev.GetPoint();
                                    V b2 = new V(); b2.ent = ent; b2.x = pe[0]; b2.y = pe[1]; b2.z = pe[2];
                                    pts.Add(b2);
                                }
                            } catch { }
                        }
                    }
                }

                // ---- 路径三：两条极值点都拿不到（回转体常见），退回单实体标注
                // 圆柱/圆环的可见边是闭合曲线，没有端点，选一条边直接 AddDimension2：
                // 圆边给直径，直边给长度。虽然只能拿到一个尺寸，但比一张没有任何尺寸的图强。
                if (pts.Count < 2) {
                    int singles = 0;
                    try {
                        int ne2 = v.GetVisibleEntityCount2(null, (int)swViewEntityType_e.swViewEntityType_Edge);
                        if (ne2 > 0) {
                            object[] raws = (object[])v.GetVisibleEntities2(null, (int)swViewEntityType_e.swViewEntityType_Edge);
                            int placed = 0;
                            foreach (object eo in raws ?? new object[0]) {
                                if (placed >= 2) break;
                                tried++;
                                try {
                                    IEntity ent = (IEntity)eo;
                                    md.ClearSelection2(true);
                                    if (!ent.Select4(true, null)) continue;
                                    // 沿视图轮廓左右各内缩一点，避免两个尺寸线重叠
                                    double fcx = (o[0] + o[2]) / 2.0;
                                    double fcy = (o[1] + o[3]) / 2.0;
                                    double dx = (o[2] - o[0]) * (placed == 0 ? 0.25 : -0.25);
                                    object d = md.AddDimension2(fcx + dx, fcy, 0);
                                    if (d != null) {
                                        placed++; done++; singles++;
                                        // 回读尺寸数值
                                        try {
                                            DisplayDimension dispDim = (DisplayDimension)d;
                                            Dimension dim = (Dimension)dispDim.GetDimension2(0);
                                            L("SWFORGE_DIM view=" + vname + " via=single ok value=" +
                                              dim.Value.ToString("F2") + " kind=" + dispDim.Type2.ToString());
                                        } catch { L("SWFORGE_DIM view=" + vname + " via=single ok value=?"); }
                                    }
                                } catch (Exception ex) {
                                    L("SWFORGE_DIM view=" + vname + " via=single exc " + ex.Message);
                                }
                            }
                        }
                    } catch { }
                    md.ClearSelection2(true);
                    if (singles == 0) {
                        try {
                            L("SWFORGE_DIM view=" + vname + " skipped=no_geometry vertex=" +
                              v.GetVisibleEntityCount2(null, (int)swViewEntityType_e.swViewEntityType_Vertex) +
                              " edge=" + v.GetVisibleEntityCount2(null, (int)swViewEntityType_e.swViewEntityType_Edge) +
                              " sil=" + v.GetVisibleEntityCount2(null, (int)swViewEntityType_e.swViewEntityType_SilhouetteEdge));
                        } catch { L("SWFORGE_DIM view=" + vname + " skipped=no_geometry"); }
                    }
                    v = (IView)v.GetNextView();
                    continue;
                }

                V minX = pts[0], maxX = pts[0], minY = pts[0], maxY = pts[0];
                foreach (V q in pts) {
                    if (q.x < minX.x) minX = q;
                    if (q.x > maxX.x) maxX = q;
                    if (q.y < minY.y) minY = q;
                    if (q.y > maxY.y) maxY = q;
                }

                double cx = (o[0] + o[2]) / 2.0;
                double cy = (o[1] + o[3]) / 2.0;

                // ---- 水平总长
                if (Math.Abs(maxX.x - minX.x) > 1e-9) {
                    tried++;
                    md.ClearSelection2(true);
                    bool s1 = minX.ent.Select4(true, null);
                    bool s2 = maxX.ent.Select4(true, null);
                    if (s1 && s2) {
                        try {
                            object d = md.AddHorizontalDimension2(cx, o[1] - gap, 0);
                            if (d != null) { done++; L("SWFORGE_DIM view=" + vname + " via=" + via + " horizontal=ok value=" +
                                ((maxX.x - minX.x) * 1000).ToString("F2")); }
                            else L("SWFORGE_DIM view=" + vname + " horizontal=null");
                        } catch (Exception ex) { L("SWFORGE_DIM view=" + vname + " horizontal=exc " + ex.Message); }
                    } else L("SWFORGE_DIM view=" + vname + " horizontal=select_fail " + s1 + "/" + s2);
                    md.ClearSelection2(true);
                }

                // ---- 垂直总高
                if (Math.Abs(maxY.y - minY.y) > 1e-9) {
                    tried++;
                    md.ClearSelection2(true);
                    bool s1 = minY.ent.Select4(true, null);
                    bool s2 = maxY.ent.Select4(true, null);
                    if (s1 && s2) {
                        try {
                            object d = md.AddVerticalDimension2(o[0] - gap, cy, 0);
                            if (d != null) { done++; L("SWFORGE_DIM view=" + vname + " via=" + via + " vertical=ok value=" +
                                ((maxY.y - minY.y) * 1000).ToString("F2")); }
                            else L("SWFORGE_DIM view=" + vname + " vertical=null");
                        } catch (Exception ex) { L("SWFORGE_DIM view=" + vname + " vertical=exc " + ex.Message); }
                    } else L("SWFORGE_DIM view=" + vname + " vertical=select_fail " + s1 + "/" + s2);
                    md.ClearSelection2(true);
                }

                v = (IView)v.GetNextView();
            }
            md.EditRebuild3();
            L("SWFORGE_DIMSUM done=" + done + " tried=" + tried);
        } catch (Exception e) {
            L("ERROR " + e.ToString());
        }
        return log.ToString();
    }
}
'''

_PS = r"""$ErrorActionPreference='Stop'
[System.Reflection.Assembly]::LoadFrom('{dll}') | Out-Null
[System.Reflection.Assembly]::LoadFrom('{cst}') | Out-Null
Add-Type -TypeDefinition ([System.IO.File]::ReadAllText('{cs}', [System.Text.Encoding]::UTF8)) `
  -ReferencedAssemblies '{dll}','{cst}' -ErrorAction Stop
[Console]::OutputEncoding=[System.Text.Encoding]::UTF8
Write-Output ([{cls}]::Run())
"""


def add_overall_dimensions(drawing_path: str | None = None,
                           gap_mm: float = 12.0,
                           timeout_s: int = 300) -> dict:
    """给工程图补总长/总高尺寸。

    每个视图按可见顶点的模型坐标找极值，生成水平（总长）与垂直（总高）两个尺寸，
    尺寸线放在视图轮廓外 `gap_mm` 处。

    返回 `{ok, done, tried, dims:[...], elapsed_s}`。
    """
    from .drawing import _drawing_document
    from .modeling import _find_sw_dir

    sw = get_session().sw()
    if drawing_path:
        _drawing_document(sw, drawing_path)

    sw_dir = _find_sw_dir()
    if not sw_dir:
        return {"ok": False, "error": "找不到 SolidWorks 安装目录"}

    work = tempfile.mkdtemp(prefix="swforge_dim_")
    cls = "Dim_" + uuid.uuid4().hex[:12]
    src = _CS.replace("__CLASS__", cls).replace("__GAP__", str(float(gap_mm)))
    cs_path = os.path.join(work, "dims.cs")
    with open(cs_path, "w", encoding="utf-8") as fh:
        fh.write(src)
    ps = _PS.format(cs=cs_path.replace("'", "''"),
                    dll=os.path.join(sw_dir, "SolidWorks.Interop.sldworks.dll").replace("'", "''"),
                    cst=os.path.join(sw_dir, "SolidWorks.Interop.swconst.dll").replace("'", "''"),
                    cls=cls)
    ps_path = os.path.join(work, "run.ps1")
    with open(ps_path, "w", encoding="utf-8-sig") as fh:
        fh.write(ps)

    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s)
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        out = f"补总尺寸超时({timeout_s}s)"
    elapsed = time.monotonic() - start

    dims = []
    done = tried = 0
    for line in out.splitlines():
        if line.startswith("SWFORGE_DIM "):
            parts = {}
            for tok in line[len("SWFORGE_DIM "):].split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    parts[k] = v
            dims.append(parts)
        elif line.startswith("SWFORGE_DIMSUM "):
            for tok in line[len("SWFORGE_DIMSUM "):].split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    if k == "done":
                        done = int(v)
                    elif k == "tried":
                        tried = int(v)
    try:
        os.remove(cs_path)
        os.remove(ps_path)
        os.rmdir(work)
    except OSError:
        pass

    return {"ok": done > 0, "done": done, "tried": tried, "dims": dims,
            "elapsed_s": round(elapsed, 2),
            "raw": out if done == 0 else ""}
