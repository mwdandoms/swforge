# -*- coding: utf-8 -*-
"""API 能力探测：这台机器上的 SolidWorks 到底支持哪些接口。

为什么需要这个
--------------
swforge 只在 SolidWorks 2025 SP5.0 上完整实测过。别人拿到它，最可能卡在第一步：

    AttributeError: 'IModelDocExtension' object has no attribute 'CreateMassProperty'

然后他花半天到两天搞不清"是版本不兼容还是我装错了"。

这个模块直接在 10 秒内给出答案：逐个检查每个有风险的 API 在本机
Interop 库里**存不存在**，以及**最高有几参的重载**。

为什么用反射而不是 C# 编译
--------------------------
生成的 C# 如果用 `typeof(IModelDocExtension)` 引用类型，那在缺方法的旧版本上
**编译期就挂了**，连探测的机会都没有。

所以这里走纯反射：`Assembly.LoadFrom(dll)` → `GetType(...)` → `GetMethods()`。
类型在旧版本上都存在，只是方法少几个；反射能把差异如实报出来。

这个设计也顺便验证了 v0.9 的降级思路：**Python 侧先探测，再决定生成哪版 C#**。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time

__all__ = ["probe_api", "RISKY_APIS"]

# 需要探测的 API 清单。
# (键, 接口类型, 方法名, 缺了会怎样)
RISKY_APIS: list[tuple[str, str, str, str]] = [
    # ---- 工程图
    ("insert_model_annotations", "IDrawingDoc", "InsertModelAnnotations4",
     "自动标注：2019~2021 可能只有 3 参重载"),
    ("insert_model_annotations3", "IDrawingDoc", "InsertModelAnnotations3",
     "自动标注的上一代重载"),
    ("view_dim_count", "IView", "GetDimensionCount4",
     "尺寸计数：旧版只有 GetDimensionCount"),
    ("visible_entities2", "IView", "GetVisibleEntities2",
     "总尺寸标注取顶点：旧版是 GetVisibleEntities"),
    ("visible_entity_count2", "IView", "GetVisibleEntityCount2",
     "总尺寸标注计数"),
    ("add_dimension2", "IModelDoc2", "AddDimension2", "总尺寸标注建尺寸"),
    ("add_horizontal_dimension2", "IModelDoc2", "AddHorizontalDimension2", "水平总尺寸"),
    ("add_vertical_dimension2", "IModelDoc2", "AddVerticalDimension2", "垂直总尺寸"),

    # ---- 质量属性
    ("create_mass_property", "IModelDocExtension", "CreateMassProperty",
     "质量属性：旧版可能只有 GetMassProperties2"),
    ("get_mass_properties2", "IModelDoc2", "GetMassProperties2", "质量属性旧接口"),

    # ---- 装配
    ("add_component5", "IAssemblyDoc", "AddComponent5", "插零件：旧版是 4 参"),
    ("add_component4", "IAssemblyDoc", "AddComponent4", "插零件旧接口"),
    ("add_mate5", "IAssemblyDoc", "AddMate5", "建配合：旧版是 4 参"),
    ("add_mate4", "IAssemblyDoc", "AddMate4", "建配合旧接口"),
    ("get_bodies2", "IComponent2", "GetBodies2", "组件实体：旧版是 GetBodies"),

    # ---- 会话
    ("activate_doc3", "ISldWorks", "ActivateDoc3", "激活文档：旧版是 2 参"),
    ("activate_doc2", "ISldWorks", "ActivateDoc2", "激活文档旧接口"),
    ("get_document_count", "ISldWorks", "GetDocumentCount", "文档计数（资源守卫用）"),

    # ---- 实体
    ("body_copy2", "IBody2", "Copy2", "干涉求交前必须转临时体"),
    ("body_operations2", "IBody2", "Operations2", "布尔求交"),
    ("face_get_surface", "IFace2", "GetSurface", "配合自动选面"),
    ("entity_select4", "IEntity", "Select4", "选择面/边"),
    ("vertex_get_point", "IVertex", "GetPoint", "顶点坐标（总尺寸用）"),
    ("edge_get_start_vertex", "IEdge", "GetStartVertex", "边端点（回转体总尺寸用）"),

    # ---- 导出
    ("save_as", "IModelDocExtension", "SaveAs", "保存/导出"),
    ("get_export_file_data", "ISldWorks", "GetExportFileData", "PDF 导出参数"),

    # ---- 用户偏好（单位）
    ("get_user_pref_int", "IModelDocExtension", "GetUserPreferenceInteger", "读单位设置"),
    ("set_user_pref_int", "IModelDocExtension", "SetUserPreferenceInteger", "设单位设置"),
]


_PS = r"""
$ErrorActionPreference = 'Stop'
$dll    = '__DLL__'
$cst    = '__CST__'
$apiJson= '__API__'

$out = [ordered]@{}

try {
    $asm = [System.Reflection.Assembly]::LoadFrom($dll)
} catch {
    @{ ok = $false; error = "载入 Interop 失败: $($_.Exception.Message)" } | ConvertTo-Json -Compress
    exit 0
}

# 程序集版本 + 文件版本（后者通常能对上 SolidWorks 年份）
try {
    $out['assembly_version'] = $asm.GetName().Version.ToString()
    $out['file_version']     = (Get-Item $dll).VersionInfo.FileVersion
    $out['product_version']  = (Get-Item $dll).VersionInfo.ProductVersion
    $out['dll_path']         = $dll
} catch { }

$apis = Get-Content $apiJson -Raw -Encoding UTF8 | ConvertFrom-Json

$result = @{}
foreach ($a in $apis) {
    $key = $a[0]; $typeName = $a[1]; $method = $a[2]; $impact = $a[3]
    $fullName = "SolidWorks.Interop.sldworks.$typeName"
    $entry = [ordered]@{ type = $typeName; method = $method; impact = $impact }
    try {
        $t = $asm.GetType($fullName)
        if (-not $t) {
            $entry['exists'] = $false
            $entry['reason'] = "类型 $fullName 不存在"
        } else {
            $ms = @($t.GetMethods() | Where-Object { $_.Name -eq $method })
            # 声明的类型上没找到 -> 全局扫一遍，避免清单写错类型就误报缺失
            if ($ms.Count -eq 0) {
                foreach ($cand in $asm.GetTypes()) {
                    if (-not $cand.IsInterface) { continue }
                    $hit = @($cand.GetMethods() | Where-Object { $_.Name -eq $method })
                    if ($hit.Count -gt 0) {
                        $entry['found_on'] = $cand.Name
                        $ms = $hit
                        break
                    }
                }
            }
            if ($ms.Count -eq 0) {
                $entry['exists'] = $false
            } else {
                $counts = @($ms | ForEach-Object { $_.GetParameters().Count })
                $entry['exists']     = $true
                $entry['overloads']  = $ms.Count
                $entry['max_params'] = ($counts | Measure-Object -Maximum).Maximum
                $entry['min_params'] = ($counts | Measure-Object -Minimum).Minimum
            }
        }
    } catch {
        $entry['exists'] = $false
        $entry['reason'] = $_.Exception.Message
    }
    $result[$key] = $entry
}
$out['apis'] = $result

$out | ConvertTo-Json -Depth 6 -Compress
"""


def _find_interop(sw_dir: str | None = None) -> tuple[str, str]:
    """找到 Interop DLL 的路径。"""
    if sw_dir is None:
        try:
            from .modeling import _find_sw_dir
            sw_dir = _find_sw_dir()
        except Exception:                                 # noqa: BLE001
            sw_dir = None
    if not sw_dir:
        return "", ""
    return (os.path.join(sw_dir, "SolidWorks.Interop.sldworks.dll"),
            os.path.join(sw_dir, "SolidWorks.Interop.swconst.dll"))


def probe_api(sw_dir: str | None = None, timeout_s: int = 120) -> dict:
    """反射探测本机 Interop 库支持的 API。

    返回
    ----
    dict:
        ok             探测本身是否成功（不代表所有 API 都在）
        assembly_version / file_version / product_version
        apis           {key: {exists, overloads, max_params, impact, ...}}
        missing        缺失的键列表
        summary        人读摘要

    注意：`exists=False` 不等于功能不可用 —— 可能还有旧重载，
    所以同时探测了 3/4/2 这些上一代方法。
    """
    dll, cst = _find_interop(sw_dir)
    if not dll or not os.path.isfile(dll):
        return {"ok": False,
                "error": f"找不到 SolidWorks Interop DLL（找的是 {dll or '空路径'}）",
                "apis": {}}

    work = tempfile.mkdtemp(prefix="swforge_probe_")
    api_path = os.path.join(work, "apis.json")
    with open(api_path, "w", encoding="utf-8") as fh:
        json.dump([[k, t, m, i] for k, t, m, i in RISKY_APIS], fh, ensure_ascii=False)

    ps = (_PS
          .replace("__DLL__", dll.replace("'", "''"))
          .replace("__CST__", cst.replace("'", "''"))
          .replace("__API__", api_path.replace("'", "''")))
    ps_path = os.path.join(work, "probe.ps1")
    with open(ps_path, "w", encoding="utf-8-sig") as fh:
        fh.write(ps)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s)
        raw = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        raw, err = "", f"探测超时（{timeout_s}s）"
    elapsed = round(time.monotonic() - started, 2)

    for f in (api_path, ps_path):
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        os.rmdir(work)
    except OSError:
        pass

    if not raw:
        return {"ok": False, "error": err or "探测无输出", "apis": {}, "elapsed_s": elapsed}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": f"探测输出无法解析: {raw[:200]}",
                "apis": {}, "elapsed_s": elapsed}

    apis = data.get("apis") or {}
    missing = [k for k, v in apis.items() if not v.get("exists")]

    # ---- 生成人读摘要，按"影响"分组
    ok_list = [k for k, v in apis.items() if v.get("exists")]
    data["ok"] = True
    data["elapsed_s"] = elapsed
    data["missing"] = missing
    data["available_count"] = len(ok_list)
    data["total_count"] = len(apis)
    data["summary"] = _summarize(apis, missing)
    return data


def _summarize(apis: dict, missing: list[str]) -> list[str]:
    """把结果整理成几行能直接贴进 issue 的话。"""
    lines = []
    total = len(apis)
    lines.append(f"探测了 {total} 个风险 API，可用 {total - len(missing)} 个")

    if not missing:
        lines.append("全部可用 —— 本机 SolidWorks 支持 swforge 的完整功能")
        return lines

    lines.append(f"缺失 {len(missing)} 个：")
    for k in missing:
        a = apis.get(k) or {}
        lines.append(f"  - {k}：{a.get('impact', '')}")

    # 判断主链路是否还能跑
    fatal = []
    if not apis.get("body_copy2", {}).get("exists"):
        fatal.append("干涉求交（需要 IBody2.Copy2）")
    if not (apis.get("add_dimension2", {}).get("exists")
            and (apis.get("visible_entities2", {}).get("exists")
                 or apis.get("edge_get_start_vertex", {}).get("exists"))):
        fatal.append("总尺寸标注")
    if not apis.get("insert_model_annotations", {}).get("exists") and \
       not apis.get("insert_model_annotations3", {}).get("exists"):
        fatal.append("自动标注")

    if fatal:
        lines.append("主链路受影响：" + "、".join(fatal))
    else:
        lines.append("主链路仍可用（缺失的都是可选能力）")
    return lines
