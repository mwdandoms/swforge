# -*- coding: utf-8 -*-
"""原地改参数并原生重建（1.9.3 新增）。

与 `variants.create_variant()` 的区别
=====================================
`create_variant()` 是**只复制**路线：另存新件再改参，源件永远不动。
本模块补的是另一条路：**在同一份零件上**改尺寸、重建、回读，适合
「图纸版本号要往前走」的场合。

安全约束
========
1. 只接受 `list_model_parameters()` 返回的**精确键**
   （`name` 全名或去掉 `@特征` 的 `key`），不接受模糊名。
2. 只改**可写的线性尺寸**；角度、只读、驱动不了的直接拒绝。
3. 默认 `save=False`：改完、量完、再**还原**，文件一个字节不动。
   要落盘必须显式 `save=True`，且默认先写一份带时间戳的 `.bak` 备份。
4. 任何一步失败（设值被拒 / 重建 False / 回读不符 / 特征报错 / 体积漂移）
   都自动把参数改回原值并重建，返回 `ok=False` + `rolled_back`。

用法
----
>>> from swforge import set_parameters
>>> r = set_parameters(r"D:\\out\\DSH_弹簧.SLDPRT",
...                    {"D3@SWFORGE_coil_helix@rb2_spring.Part": 75.0})
>>> r["volume_before_mm3"], r["volume_after_mm3"], r["restored"]
(1589.926, 1596.258, True)

体积校验
--------
给了 `expect_volume_mm3` 才比对，偏差超过 `tolerance_pct` 判失败；
不给就只回读，不做「应该多少」的猜测。
"""
from __future__ import annotations

import math
import os
import shutil
import time
import uuid

from .native_bridge import run_native, target_document

__all__ = ["set_parameters"]

MAX_PARAMETERS = 100


def _check_parameters(parameters) -> dict:
    """和 variants 同一套校验：精确键、有限正数、最多 100 个。"""
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object of exact parameter keys")
    if not parameters:
        raise ValueError("Specify at least one exact parameter")
    if len(parameters) > MAX_PARAMETERS:
        raise ValueError(f"parameters must contain at most {MAX_PARAMETERS} exact keys")
    result = {}
    for name, value in parameters.items():
        if not isinstance(name, str) or "@" not in name or not name.strip():
            raise ValueError("Use an exact key returned by list_model_parameters")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Parameter values must be finite positive millimetres: {name}")
        value = float(value)
        if value != value or value in (float("inf"), float("-inf")) or value <= 0:
            raise ValueError(f"Parameter values must be finite positive millimetres: {name}")
        result[name] = value
    return result


def _backup_path(path: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{path}.bak_{stamp}_{uuid.uuid4().hex[:8]}"


def set_parameters(part_path, parameters, *, save: bool = False, material=None,
                   expect_volume_mm3: float | None = None, tolerance_pct: float = 0.5,
                   backup: bool = True, allow_unsaved: bool = False,
                   keep_open: bool = False) -> dict:
    """在同一份零件上改精确尺寸 → 原生重建 → 回读校验。

    `save=False`（默认）改完会还原，文件不变；`save=True` 落盘，
    落盘前若 `backup` 为真则先复制一份 `.bak_<时间戳>` 备份。
    `keep_open=False`（默认）时，本次调用自己打开的零件结束就关掉。

    返回字典：`ok`、`changes`（含 before/after/readback）、
    `volume_before_mm3`、`volume_after_mm3`、`saved`、`restored`、
    `backup`、`volume_check`（仅在给了期望体积时出现）。
    """
    parameters = _check_parameters(parameters)
    part_path = os.path.abspath(os.fspath(part_path))
    if not part_path.lower().endswith(".sldprt"):
        raise ValueError("set_parameters only accepts .sldprt parts")
    if not os.path.isfile(part_path):
        raise ValueError("Part does not exist: " + part_path)
    if isinstance(tolerance_pct, bool) or not isinstance(tolerance_pct, (int, float)):
        raise ValueError("tolerance_pct must be a number")
    tolerance_pct = float(tolerance_pct)
    if tolerance_pct < 0 or not math.isfinite(tolerance_pct):
        raise ValueError("tolerance_pct must be finite and non-negative")
    if expect_volume_mm3 is not None:
        if isinstance(expect_volume_mm3, bool) or not isinstance(expect_volume_mm3, (int, float)):
            raise ValueError("expect_volume_mm3 must be a number")
        expect_volume_mm3 = float(expect_volume_mm3)
        if not math.isfinite(expect_volume_mm3) or expect_volume_mm3 <= 0:
            raise ValueError("expect_volume_mm3 must be finite and positive")

    material_db = ""
    if material is not None:
        from .gb_materials import ensure_library, lookup

        if not isinstance(material, str) or lookup(material) is None:
            raise ValueError("material must be an explicit supported GB material name")
        material_db = ensure_library()

    backup_path = ""
    if save and backup:
        backup_path = _backup_path(part_path)
        shutil.copy2(part_path, backup_path)

    try:
        from .session import get_session, _value

        md = None
        result = {}
        sw = get_session().sw()
        was_open = sw.GetOpenDocumentByName(part_path) is not None
        try:
            sw, md, target = target_document(part_path, 1)
            result = run_native(dict(target, mode="setparams", parameters=parameters,
                                     material=material or "", material_db=material_db,
                                     save=bool(save), restore_after=not save,
                                     expect_volume_mm3=expect_volume_mm3,
                                     tolerance_pct=tolerance_pct,
                                     allow_unsaved=bool(allow_unsaved)))
        finally:
            if md is not None and not was_open and not keep_open and result.get("mutation_state") != "unknown":
                sw.CloseDoc(str(_value(md, "GetTitle")))
    except Exception as exc:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "backup": backup_path, "path": part_path}

    result["path"] = part_path
    result["save_requested"] = bool(save)
    result["backup"] = backup_path
    return result
