# v1.4 粗糙度与尺寸公差

本机验证范围：SolidWorks 2025 SP5.0（33.5.0），其他版本未验证。
只应用明确指定的工艺要求，不自动选公差等级或加工要求。形位公差不在本版范围。

## Python

```python
from swforge import add_surface_finish, add_surface_finishes, list_surface_edges, list_dimensions, set_tolerance

drawing = r'D:\项目\底板.SLDDRW'
# 工艺标注优先附着真实轮廓边；先枚举，再明确指定 view_name 和 edge_index。
edges = list_surface_edges(drawing, view_name='工程图视图1')
add_surface_finish(drawing, view_name=edges[0]['view'], edge_index=edges[0]['edge_index'], ra='3.2', leader=True)
# 以下坐标模式是独立图纸符号，不声明任何加工面关联。
add_surface_finish(drawing, x=0.30, y=0.23, ra='3.2', symbol_type='machining')
add_surface_finishes(drawing, [
    dict(view_name='工程图视图1', offset_x=0.008, offset_y=0.012, ra='1.6'),
    dict(x=0.35, y=0.23, ra='6.3', symbol_type='basic'),
])
rows = list_dimensions(drawing)
# 使用枚举得到的完整名称，避免多个视图中相同数值被误选。
name = rows[0]['name']
set_tolerance(drawing, dim_name=name, tol_type='symmetric', upper=0.1)
set_tolerance(drawing, dim_name=name, tol_type='bilateral', lower=-0.05, upper=0.2)
set_tolerance(drawing, dim_name=name, tol_type='limit', lower=-0.1, upper=0.1)
set_tolerance(drawing, dim_name=name, tol_type='fit', fit='H7/g6')
set_tolerance(drawing, dim_name=name, tol_type='none')
```

- **位置及偏移用米，Ra 用 μm，尺寸值和公差偏差用毫米**。极限公差输入上下偏差；160 的 ±0.1 显示为 160.10/159.90。
- 默认返回 JSON 可序列化的数据。`list_dimensions(..., include_objects=True)` 提供本线程 COM 引用，不可跨线程传递。
- 枚举范围是当前图纸；多页工程图需先激活目标页。角度、倒角、未知类型公差拒绝执行。
- 支持基本符号 `basic/0`、去除材料 `machining/1`、不去除材料 `no_machining/2`。默认去除材料；这只是符号默认值，调用方负责工程含义。
- `edge_index` 配合明确的 `view_name` 关联真实可见直边；`edge_fraction` 在0~1之间指定贴边位置。无引线贴边目前只支持水平直边，其他方向用 `leader=True`，引线端点必须回读确认落在目标边上。已验证视图移动后符号随动、保存重开后关联保留。
- 附着路径当前只验证了零件工程图的直边，曲边及装配体视图未验证。
- 显式坐标必须成对提供；省略坐标且不指定边时从视图轮廓加偏移。此模式返回 `placement='sheet'`，是独立符号，不关联加工面，不能把它误认为完成的表面工艺标注。不做自动避让。
- 函数只修改内存文档，成功后调用方决定保存或导 PDF。返回 `ok` 仅表示该次 API 操作回读正确，不表示图纸可直接投产。
- 批量操作先校验全部参数。执行中失败立即停止，`created` 和 `results` 记录部分成果；失败插入不自动重试，避免重复符号。
- 公差写入失败会尝试恢复原公差，`rollback_ok` 表示恢复后的回读结果。失败的粗糙度插入可能留下符号，`created=True` 时应检查内存文档后再保存。

## CLI / MCP

```powershell
swforge surface-finish 底板.SLDDRW --ra 3.2 --x 0.30 --y 0.23 --save
swforge surface-edges 底板.SLDDRW --view 工程图视图1
swforge surface-finish 底板.SLDDRW --view 工程图视图1 --edge 0 --ra 3.2 --save
swforge surface-finish 底板.SLDDRW --view 工程图视图1 --edge 1 --leader --ra 3.2 --x 0.18 --y 0.22 --save
swforge dimensions 底板.SLDDRW
swforge tolerance 底板.SLDDRW --dim "完整名称（从 dimensions 复制）" --type symmetric --upper 0.1 --save
swforge tolerance 底板.SLDDRW --dim "完整名称" --type fit --fit H7/g6 --save
```

不传 `--save` 时保留在内存，CLI 失败返回非零退出码。
MCP 新工具：`sw_add_surface_finish`、`sw_add_surface_finishes`、`sw_list_surface_edges`、`sw_list_dimensions`、`sw_set_tolerance`；均通过现有 STA worker 串行执行。

## 实机验收入口

```powershell
python -m pytest tests -q -m "not sw"
swforge selftest --work-dir F:\证据\swforge_selftest --keep
python examples/verify_annotations.py --work-dir F:\证据\新目录 --keep
```

验收脚本检查四类公差、名义值不变、同值拒绝猜选、五个附着符号、引线端点、视图移动10mm随动、连续20次插入、保存重开及 PDF 独立渲染。检查最终 PNG，确认符号与尺寸可见且没有重叠。示例 Ra 值仅用于功能验收，不代表对试块的生产工艺推荐。
`--keep` 成功时保留一个演示零件和一张工程图，失败时只关闭本轮拥有的文档。

## 实测发现

1. `InsertSurfaceFinishSymbol3` 在本机忽略插入坐标，必须调用 `Annotation.SetPosition2` 并回读；否则符号堆在原点。
2. 工程图参考尺寸 `IDimension.GetType()` 实测返回 0，使用 `IDisplayDimension.Type2` 判断线性或角度。
3. 无公差尺寸 `GetToleranceValues()` 可返回 None，改从 `Dimension.Tolerance.GetMinValue/GetMaxValue` 回读。
4. `SetToleranceValues` 使用米；`H7/g6` 使用 `Dimension.Tolerance.SetFitValues('H7','g6')` 并分别回读孔、轴代号。

官方接口参考：[插入粗糙度](https://help.solidworks.com/2019/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~InsertSurfaceFinishSymbol3.html)、[符号枚举](https://help.solidworks.com/2024/English/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swSFSymType_e.html)。实际兼容性以本机验收为准。
