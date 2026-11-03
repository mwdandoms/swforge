# -*- coding: utf-8 -*-
"""装配体：插入零件、固定基件、跑干涉检查。

关键实测结论（本机 SW2025 SP5.0）
--------------------------------
1. **零件必须先打开**再 `AddComponent5`，否则返回 None（不报错，静默失败）。
   这是本环境最反直觉的一条：直接传文件路径给一个未打开的零件，一律失败。
2. `GetComponents(False)` 能拿到组件清单；组件的 `Name2` 形如 `a_base-1`。
3. 干涉检查走 `IAssemblyDoc.GetInterferenceDetectionManager`，
   读完必须调用 `Done()` 释放。

配合（Mate）
-----------
`CreateMate` / `AddMate5` 需要先选中两个实体的面，本版**没有实现自动选面**，
只提供 `list_components()` 与 `check_interference()` 这类不依赖选择的检查。
配合请先在 SW 界面里建立，再用本模块做干涉验证。
"""

from __future__ import annotations

import os

from .session import get_session, _value, SWError

__all__ = ["AssemblyBuilder", "list_components", "check_interference"]


def _abs(path: str) -> str:
    if not path or not os.path.isfile(path):
        raise ValueError(f"零件文件不存在：{path}")
    return os.path.abspath(path)


def _default_asm_template() -> str:
    cands = []
    env = os.environ.get("SW_TEMPLATE_DIR")
    if env:
        cands.append(os.path.join(env, "Assembly.asmdot"))
    base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    for year in range(2026, 2019, -1):
        for vendor in ("SOLIDWORKS", "SolidWorks"):
            cands.append(os.path.join(base, vendor, f"SOLIDWORKS {year}",
                                      "templates", "gb_assembly.asmdot"))
            cands.append(os.path.join(base, vendor, f"SOLIDWORKS {year}",
                                      "templates", "Assembly.asmdot"))
    for p in cands:
        if os.path.isfile(p):
            return p
    raise RuntimeError("找不到装配模板，请设置 SW_TEMPLATE_DIR")


def _activate(sw, md):
    """把指定文档设为活动文档。"""
    from win32com.client import VARIANT
    import pythoncom

    title = str(_value(md, "GetTitle"))
    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    sw.ActivateDoc3(title, False, 0, err)
    return sw.ActiveDoc


def _open_part(sw, path: str):
    """打开零件并返回文档对象；已打开则直接复用。"""
    target = os.path.normcase(os.path.abspath(path))
    for d in (_value(sw, "GetDocuments") or []):
        try:
            cur = str(_value(d, "GetPathName"))
        except Exception:                                # noqa: BLE001
            continue
        if cur and os.path.normcase(os.path.abspath(cur)) == target:
            return d
    from win32com.client import VARIANT
    import pythoncom

    err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    doc = sw.OpenDoc6(path, 1, 1, "", err, warn)         # 1 = swDocPART
    if doc is None:
        raise SWError(f"打开零件失败：{path}")
    return doc


def _fix_component(ad, comp) -> str:
    """把组件固定。逐级尝试不同选择 API，返回实际生效的那条。"""
    errors = []
    try:
        ad.ClearSelection2(True)
    except Exception:                                    # noqa: BLE001
        pass
    for label, sel in (
        ("Select4(True,None,False)", lambda: comp.Select4(True, None, False)),
        ("Select4(True,None)",       lambda: comp.Select4(True, None)),
        ("Select(True)",             lambda: comp.Select(True)),
        ("Select2(True,0)",          lambda: comp.Select2(True, 0)),
    ):
        try:
            sel()
            ok = ad.FixComponent()
            return f"{label} -> FixComponent={ok}"
        except Exception as exc:                         # noqa: BLE001
            errors.append(f"{label}: {type(exc).__name__}")
    return "失败（" + "; ".join(errors) + "）"


class AssemblyBuilder:
    """按顺序插入零件并记录，最后一次性建出装配体。

    用法::

        a = AssemblyBuilder(r"D:\\out\\总装.SLDASM")
        a.add(r"D:\\out\\底座.SLDPRT", x=0,  y=0, z=0, fixed=True)
        a.add(r"D:\\out\\立柱.SLDPRT", x=0,  y=0, z=0)
        r = a.build()
        print(r["ok"], r["components"])
        print(check_interference())
    """

    def __init__(self, path: str, template: str | None = None,
                 keep_open: bool = True):
        if not str(path).lower().endswith(".sldasm"):
            raise ValueError("装配体输出必须使用 .SLDASM 扩展名")
        self.path = os.path.abspath(path)
        self.template = template
        self.keep_open = keep_open
        self._items = []                                  # (path, x, y, z, fixed)

    def add(self, part_path: str, x: float = 0.0, y: float = 0.0, z: float = 0.0,
            fixed: bool = False) -> "AssemblyBuilder":
        """插入零件。**坐标单位是毫米**（与全项目一致）。

        SolidWorks 的 `AddComponent5` 内部要米，这里统一换算；
        v0.7 及以前直接把毫米当米传，导致零件被放到 60 米外。
        """
        self._items.append((_abs(part_path), float(x), float(y), float(z), bool(fixed)))
        return self

    # ------------------------------------------------------------------ 构建
    def build(self, max_documents: int = 8) -> dict:
        from .resources import ensure_capacity

        if not self._items:
            return {"ok": False, "error": "没有要插入的零件"}
        cap = ensure_capacity(need=1, limit=max_documents)
        if not cap["allowed"]:
            return {"ok": False, "error": cap["error"], "resource": cap}

        sw = get_session().sw()
        log = []
        asm = None

        def L(msg):
            log.append(str(msg))
            print(msg)

        try:
            tpl = self.template or _default_asm_template()
            L(f"模板: {tpl}")
            asm = sw.NewDocument(tpl, 0, 0, 0)
            if asm is None:
                return {"ok": False, "error": "新建装配文档失败", "log": "\n".join(log)}

            ad = asm                                        # 后期绑定同一个 dispatch
            inserted = []
            for path, x, y, z, fixed in self._items:
                # ① 零件必须先打开，否则 AddComponent5 静默返回 None
                _open_part(sw, path)
                asm = _activate(sw, asm)
                comp = None
                try:
                    comp = ad.AddComponent5(path, 0, "", False, "",
                                            x / 1000.0, y / 1000.0, z / 1000.0)
                except Exception as exc:                     # noqa: BLE001
                    L(f"AddComponent5 异常 {os.path.basename(path)}: {exc}")
                if comp is None:
                    try:
                        comp = ad.AddComponent4(path, "", x / 1000.0, y / 1000.0, z / 1000.0)
                    except Exception:                        # noqa: BLE001
                        pass
                if comp is None:
                    L(f"插入失败: {os.path.basename(path)}")
                    continue
                name = str(_value(comp, "Name2"))
                L(f"插入 {name} @ ({x},{y},{z})")
                if fixed:
                    L(f"固定 {name} -> {_fix_component(ad, comp)}")
                inserted.append({"part": path, "component": name,
                                 "position": [x, y, z], "fixed": fixed})

            comps = self._components(ad)
            L(f"组件数 = {len(comps)}")
            ok = len(inserted) == len(self._items) and len(comps) >= len(self._items)
            saved = False
            if ok:
                from win32com.client import VARIANT
                import pythoncom
                err = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                warn = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
                # ExportData 是 IDispatch 指针；直接传 None 会变成 VT_EMPTY 导致类型不匹配
                export_data = VARIANT(pythoncom.VT_DISPATCH, None)
                try:
                    saved = bool(asm.Extension.SaveAs(self.path, 0, 1, export_data,
                                                      err, warn))
                    L(f"保存 {saved} err={err.value}")
                except Exception as exc:                     # noqa: BLE001
                    L(f"保存异常: {exc}")
            return {
                "ok": bool(ok and saved),
                "path": self.path,
                "components": comps,
                "inserted": inserted,
                "saved": saved,
                "log": "\n".join(log),
            }
        finally:
            if asm is not None and not self.keep_open:
                try:
                    sw.CloseDoc(str(_value(asm, "GetTitle")))
                except Exception:                            # noqa: BLE001
                    pass

    @staticmethod
    def _components(ad) -> list[dict]:
        try:
            raw = ad.GetComponents(False)
        except Exception:                                    # noqa: BLE001
            return []
        out = []
        for c in (raw or []):
            try:
                out.append({
                    "name": str(_value(c, "Name2")),
                    "path": str(_value(c, "GetPathName")),
                    "suppressed": bool(_value(c, "IsSuppressed")),
                })
            except Exception:                                # noqa: BLE001
                out.append({"name": str(c), "path": "", "suppressed": False})
        return out


# ---------------------------------------------------------------------- 只读接口
def list_components(assembly_path: str | None = None) -> dict:
    """列出当前（或指定）装配体的组件。"""
    sw = get_session().sw()
    md = sw.ActiveDoc
    if assembly_path:
        md = sw.OpenDoc(assembly_path, 2)                # 2 = swDocASSEMBLY
        sw.ActivateDoc(assembly_path)
        md = sw.ActiveDoc
    if md is None or _value(md, "GetType") != 2:
        raise RuntimeError("当前文档不是装配体")
    comps = AssemblyBuilder._components(md)
    return {"ok": True, "path": str(_value(md, "GetPathName")),
            "count": len(comps), "components": comps}


def check_interference(assembly_path: str | None = None,
                       treat_coincident_as_interference: bool = False) -> dict:
    """跑干涉检查并返回干涉清单。

    读完后调用 `Done()` 释放管理器。
    """
    sw = get_session().sw()
    md = sw.ActiveDoc
    if assembly_path:
        md = sw.OpenDoc(assembly_path, 2)
        sw.ActivateDoc(assembly_path)
        md = sw.ActiveDoc
    if md is None or _value(md, "GetType") != 2:
        return {"ok": False, "error": "当前文档不是装配体"}

    # 后期绑定下这是**属性**（InterferenceDetectionManager），
    # 方法名 GetInterferenceDetectionManager 取不到。
    mgr = None
    last = ""
    for name in ("InterferenceDetectionManager", "GetInterferenceDetectionManager"):
        try:
            got = _value(md, name)
            got = got() if callable(got) and not hasattr(got, "GetInterferenceCount") else got
            if got is not None:
                mgr = got
                break
        except Exception as exc:                         # noqa: BLE001
            last = f"{name}: {type(exc).__name__}"
    if mgr is None:
        return {"ok": False, "error": f"取干涉管理器失败（{last}）"}
    if mgr is None:
        return {"ok": False, "error": "干涉管理器为空"}

    try:
        try:
            mgr.TreatCoincidenceAsInterference = bool(treat_coincident_as_interference)
        except Exception:                                # noqa: BLE001
            pass
        count = 0
        items = []
        try:
            count = int(_value(mgr, "GetInterferenceCount") or 0)
        except Exception:                                # noqa: BLE001
            count = 0
        if count:
            try:
                raw = mgr.GetInterferences()
            except Exception:                            # noqa: BLE001
                raw = None
            for x in (raw or []):
                try:
                    items.append({
                        "volume_mm3": round(float(_value(x, "Volume")) * 1e9, 3),
                        "components": [str(_value(c, "Name2")) for c in
                                       (x.Components if hasattr(x, "Components") else [])],
                    })
                except Exception:                        # noqa: BLE001
                    items.append({"raw": str(x)})
        try:
            mgr.Done()
        except Exception:                                # noqa: BLE001
            pass
        return {"ok": True, "interference_count": count, "interferences": items,
                "note": "count=0 表示无干涉；重合面是否算干涉由参数控制"}
    except Exception as exc:                             # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
