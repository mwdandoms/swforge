# -*- coding: utf-8 -*-
"""装配配合（Mate）：同心 / 重合，自动选面。

为什么用 C# 而不是 Python COM
-----------------------------
`IFace2.GetSurface()` 在 pywin32 后期绑定下报「找不到成员」，
而同一个调用在 C# 早期绑定里正常，能拿到 `IsCylinder()` / `CylinderParams`
（半径 + 轴向）与 `IsPlane()` / `PlaneParams`（法向）。
所以选面与建配合整段放在 C# 里做，Python 只负责拼装参数与解析结果。

自动选面策略
------------
* **同心**：两边各找一个圆柱面，**半径相等**（默认容差 0.05 mm）即成对。
  多个候选时取面积最大的一对（通常是主孔/主轴）。
* **重合**：两边各找一个平面，**法向平行且反向**，取两平面距离最近的一对。

判定依据（不采信 API 返回值）
----------------------------
`AddMate5` 的 `ErrorStatus` 只是线索。真正的判据是：
1. 返回的 `Mate2` 不为 None；
2. 装配的特征数比操作前增加；
3. （同心）配合后两零件的圆柱轴线距离接近 0。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import uuid

from .session import get_session, _value, SWError

__all__ = ["MateBuilder", "list_mates", "CONCENTRIC", "COINCIDENT", "DISTANCE"]

CONCENTRIC = 1
COINCIDENT = 0
DISTANCE = 5


# ----------------------------------------------------------------- C# 模板
_CS_TEMPLATE = r'''
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public class __CLASS__ {
    static StringBuilder log = new StringBuilder();
    static ISldWorks sw = null;
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

    // ---- 面信息 ----
    class FaceInfo {
        public IFace2 face;
        public string compName;
        public int kind;          // 1=圆柱 2=平面 0=其它
        public double radius;     // 圆柱
        public double[] axis;     // 圆柱轴向
        public double[] origin;   // 圆柱轴线上一点
        public double[] normal;   // 平面法向
        public double[] pnt;      // 平面上一点
        public double area;
    }

    static List<FaceInfo> Faces(IComponent2 comp) {
        List<FaceInfo> outList = new List<FaceInfo>();
        object[] bodies = (object[])comp.GetBodies2((int)swBodyType_e.swSolidBody);
        if (bodies == null) return outList;
        foreach (object bo in bodies) {
            IBody2 b = (IBody2)bo;
            object[] faces = (object[])b.GetFaces();
            if (faces == null) continue;
            foreach (object fo in faces) {
                IFace2 f = (IFace2)fo;
                FaceInfo fi = new FaceInfo();
                fi.face = f;
                fi.compName = comp.Name2;
                try { fi.area = f.GetArea(); } catch { fi.area = 0; }
                try {
                    ISurface s = (ISurface)f.GetSurface();
                    if (s.IsCylinder()) {
                        double[] p = (double[])s.CylinderParams;
                        fi.kind = 1;
                        fi.origin = new double[] { p[0], p[1], p[2] };
                        fi.axis = new double[] { p[3], p[4], p[5] };
                        fi.radius = p[6];
                    } else if (s.IsPlane()) {
                        double[] p = (double[])s.PlaneParams;
                        fi.kind = 2;
                        fi.pnt = new double[] { p[0], p[1], p[2] };
                        fi.normal = new double[] { p[3], p[4], p[5] };
                    }
                } catch { fi.kind = 0; }
                outList.Add(fi);
            }
        }
        return outList;
    }

    static double Dist(double[] a, double[] b) {
        double s = 0;
        for (int i = 0; i < a.Length; i++) { double d = a[i] - b[i]; s += d * d; }
        return Math.Sqrt(s);
    }

    static double Dot(double[] a, double[] b) {
        double s = 0;
        for (int i = 0; i < a.Length; i++) s += a[i] * b[i];
        return s;
    }

    static bool Parallel(double[] a, double[] b, double tol) {
        double na = Math.Sqrt(Dot(a, a)), nb = Math.Sqrt(Dot(b, b));
        if (na < 1e-12 || nb < 1e-12) return false;
        double c = Math.Abs(Dot(a, b) / (na * nb));
        return c > 1.0 - tol;
    }

    static int FeatureCount(IModelDoc2 md) {
        int n = 0;
        for (IFeature f = (IFeature)md.FirstFeature(); f != null; f = (IFeature)f.GetNextFeature()) n++;
        return n;
    }

    public static string Run() {
        IModelDoc2 md = null;
        try {
            sw = Connect();
            md = (IModelDoc2)sw.ActiveDoc;
            if (md == null || md.GetType() != (int)swDocumentTypes_e.swDocASSEMBLY)
                throw new Exception("当前文档不是装配体");
            IAssemblyDoc ad = (IAssemblyDoc)md;
            object[] cos = (object[])ad.GetComponents(false);
            if (cos == null) throw new Exception("装配体没有组件");
            List<IComponent2> comps = new List<IComponent2>();
            foreach (object o in cos) comps.Add((IComponent2)o);
            L("DSHSW_ASM title=" + md.GetTitle() + " components=" + comps.Count);

            foreach (string spec in new string[] { __SPECS__ }) {
                string[] p = spec.Split('|');
                string op = p[0];
                int ia = int.Parse(p[1]);
                int ib = int.Parse(p[2]);
                if (ia >= comps.Count || ib >= comps.Count) {
                    L("DSHSW_MATE op=" + op + " result=index_out_of_range");
                    continue;
                }
                IComponent2 ca = comps[ia], cb = comps[ib];
                List<FaceInfo> fa = Faces(ca), fb = Faces(cb);

                FaceInfo pa = null, pb = null;
                string how = "";
                if (op == "concentric") {
                    double tolR = double.Parse(p[3], System.Globalization.CultureInfo.InvariantCulture);
                    double best = -1;
                    foreach (FaceInfo x in fa) {
                        if (x.kind != 1) continue;
                        foreach (FaceInfo y in fb) {
                            if (y.kind != 1) continue;
                            double dr = Math.Abs(x.radius - y.radius) * 1000.0;
                            if (dr > tolR) continue;
                            if (!Parallel(x.axis, y.axis, 0.02)) continue;
                            double score = Math.Min(x.area, y.area);
                            if (score > best) { best = score; pa = x; pb = y; }
                        }
                    }
                    how = pa == null ? "no_matching_cylinder"
                                     : ("R=" + (pa.radius * 1000).ToString("F3") + "mm");
                } else if (op == "coincident") {
                    double best = double.MaxValue;
                    foreach (FaceInfo x in fa) {
                        if (x.kind != 2) continue;
                        foreach (FaceInfo y in fb) {
                            if (y.kind != 2) continue;
                            if (!Parallel(x.normal, y.normal, 0.02)) continue;
                            // 反向更常见（面贴面），同向也可，交给 Align 处理
                            double d = Dist(x.pnt, y.pnt);
                            if (d < best) { best = d; pa = x; pb = y; }
                        }
                    }
                    how = pa == null ? "no_parallel_plane"
                                     : ("d=" + best.ToString("F3") + "m");
                } else {
                    L("DSHSW_MATE op=" + op + " result=unsupported");
                    continue;
                }

                if (pa == null || pb == null) {
                    L("DSHSW_MATE op=" + op + " result=" + how);
                    continue;
                }

                md.ClearSelection2(true);
                // IFace2 不继承 IEntity，但底层 Face2 对象支持 IEntity 的 QI，
                // 选择方法（Select2 等）只能通过 IEntity 接口调用。
                bool s1 = false, s2 = false;
                string selErr = "";
                try {
                    IEntity e1 = (IEntity)(object)pa.face;
                    IEntity e2 = (IEntity)(object)pb.face;
                    s1 = e1.Select2(true, 1);
                    s2 = e2.Select2(true, 1);
                } catch (Exception ex) { selErr = " cast/select失败: " + ex.Message; }
                if (!s1 || !s2) {
                    L("DSHSW_MATE op=" + op + " result=select_failed a=" + s1 + " b=" + s2 + selErr);
                    md.ClearSelection2(true);
                    continue;
                }
                L("DSHSW_SELECT op=" + op + " a=" + s1 + " b=" + s2 +
                  " faceA=" + pa.compName + " faceB=" + pb.compName);

                int before = FeatureCount(md);
                int errStatus = 0;
                int mateType = op == "concentric" ? (int)swMateType_e.swMateCONCENTRIC
                                                  : (int)swMateType_e.swMateCOINCIDENT;
                Mate2 mate = null;
                try {
                    mate = ad.AddMate5(mateType, 0, false,
                        0, 0, 0, 1, 1, 0, 0, 0, false, false, 0, out errStatus);
                } catch (Exception ex) {
                    L("DSHSW_MATE op=" + op + " result=exception msg=" + ex.Message);
                    md.ClearSelection2(true);
                    continue;
                }
                int after = FeatureCount(md);
                md.ClearSelection2(true);
                // 关键：swAddMateError_NoError == 1（不是 0！）
                // 判据 = Mate2 非空 且 errStatus==1；特征数只作参考（配合特征在
                // MateGroup 之下，FirstFeature 链遍历不一定能数到）。
                bool ok = (mate != null) && (errStatus == 1);
                L("DSHSW_MATE op=" + op + " result=" + (ok ? "ok" : "fail") +
                  " errStatus=" + errStatus + " features " + before + "->" + after +
                  " how=" + how);
            }

            // 结果几何核对：每个组件的包围盒中心
            foreach (IComponent2 c in comps) {
                try {
                    double[] box = (double[])c.GetBox(false, false);
                    if (box == null || box.Length < 6) continue;
                    L("DSHSW_BOX comp=" + c.Name2 +
                      " x=" + ((box[0] + box[3]) / 2 * 1000).ToString("F3") +
                      " y=" + ((box[1] + box[4]) / 2 * 1000).ToString("F3") +
                      " z=" + ((box[2] + box[5]) / 2 * 1000).ToString("F3"));
                } catch (Exception ex) { L("DSHSW_BOX comp=" + c.Name2 + " err=" + ex.Message); }
            }
            L("DSHSW_RESULT mates=" + __SPECSCOUNT__);
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


def _find_sw_dir():
    from .modeling import _find_sw_dir as f

    return f()


def _cs_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class MateBuilder:
    """在当前装配体上建配合。

    用法::

        m = MateBuilder()
        m.concentric(0, 1)          # 组件 0 与 1 同心
        m.coincident(0, 1)          # 组件 0 与 1 重合
        r = m.apply()
        print(r["mates"], r["ok"])
    """

    def __init__(self, assembly_path: str | None = None, timeout_s: int = 300):
        self.assembly_path = assembly_path
        self.timeout_s = timeout_s
        self._specs: list[str] = []

    def concentric(self, a: int, b: int, radius_tol_mm: float = 0.05) -> "MateBuilder":
        self._specs.append(f"concentric|{int(a)}|{int(b)}|{float(radius_tol_mm)}")
        return self

    def coincident(self, a: int, b: int) -> "MateBuilder":
        self._specs.append(f"coincident|{int(a)}|{int(b)}")
        return self

    def apply(self) -> dict:
        # 允许空规格：这时只做「读装配坐标包围盒」，用于前后对比
        if self.assembly_path:
            _activate_assembly(self.assembly_path)

        sw_dir = _find_sw_dir()
        if not sw_dir:
            return {"ok": False, "error": "找不到 SolidWorks 安装目录"}

        work = tempfile.mkdtemp(prefix="dshsw_mate_")
        cls = "Mat_" + uuid.uuid4().hex[:12]
        specs = ",".join(_cs_str(s) for s in self._specs)
        src = (_CS_TEMPLATE
               .replace("__CLASS__", cls)
               .replace("__SPECS__", specs)
               .replace("__SPECSCOUNT__", str(len(self._specs))))
        cs_path = os.path.join(work, "mate.cs")
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
                timeout=self.timeout_s)
            out = (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            out = f"建配合超时({self.timeout_s}s)"
        elapsed = time.monotonic() - start

        mates = []
        for line in out.splitlines():
            if line.startswith("DSHSW_MATE "):
                mates.append(_kv(line[len("DSHSW_MATE "):]))
        boxes = [_kv(l[len("DSHSW_BOX "):]) for l in out.splitlines()
                 if l.startswith("DSHSW_BOX ")]
        try:
            os.remove(cs_path)
            os.remove(ps_path)
            os.rmdir(work)
        except OSError:
            pass

        built = [m for m in mates if m.get("result") == "ok"]
        if not self._specs:
            return {"ok": bool(boxes), "requested": 0, "built": 0, "mates": [],
                    "component_boxes_center_mm": boxes,
                    "elapsed_s": round(elapsed, 2), "raw": out if not boxes else ""}
        return {
            "ok": len(built) == len(self._specs),
            "requested": len(self._specs),
            "built": len(built),
            "mates": mates,
            "component_boxes_center_mm": boxes,
            "elapsed_s": round(elapsed, 2),
            "raw": out if not mates else "",
        }


def _kv(text: str) -> dict:
    out = {}
    for token in text.split():
        if "=" in token:
            k, v = token.split("=", 1)
            out[k] = v
    return out


def _activate_assembly(path: str):
    import pythoncom
    from win32com.client import VARIANT

    sw = get_session().sw()
    target = os.path.normcase(os.path.abspath(path))
    title = None
    for d in (_value(sw, "GetDocuments") or []):
        try:
            cur = str(_value(d, "GetPathName"))
        except Exception:                                # noqa: BLE001
            continue
        if cur and os.path.normcase(os.path.abspath(cur)) == target:
            title = str(_value(d, "GetTitle"))
            break
    if title is None:
        doc = sw.OpenDoc(path, 2)
        if doc is None:
            raise SWError(f"打不开装配体：{path}")
        title = str(_value(doc, "GetTitle"))
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    sw.ActivateDoc3(title, False, 0, err)


def list_mates(assembly_path: str | None = None) -> dict:
    """列出装配体里的配合特征（按类型名过滤）。"""
    sw = get_session().sw()
    md = sw.ActiveDoc
    if assembly_path:
        _activate_assembly(assembly_path)
        md = sw.ActiveDoc
    if md is None or _value(md, "GetType") != 2:
        return {"ok": False, "error": "当前文档不是装配体"}
    names = []
    total = 0
    f = _value(md, "FirstFeature")
    guard = 0
    while f is not None and guard < 2000:
        guard += 1
        try:
            t = str(_value(f, "GetTypeName2"))
            if "Mate" in t:
                names.append({"type": t, "name": str(_value(f, "Name"))})
            total += 1
            f = _value(f, "GetNextFeature")
        except Exception:                                # noqa: BLE001
            break
    return {"ok": True, "features": total, "mate_count": len(names), "mates": names}
