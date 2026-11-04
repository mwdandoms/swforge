# v1.4.1：显式配合选面

复杂零件上，自动挑“最大圆柱面”不等于选中设计要配合的孔。v1.4.1 增加明确面引用路径：先枚举，调用方指定两个面，再建立同心或重合配合，并回读实际的原生配合实体与装配几何。

## 用法

```python
from swforge import list_mate_faces, apply_face_mates, inspect_face_mates, MateBuilder

assembly = r'D:\项目\支架装配.SLDASM'
result = list_mate_faces(assembly)
if not result['ok']:
    raise RuntimeError(result['error'])
faces = result['faces']

def unique(predicate):
    matches = [f for f in faces if predicate(f)]
    if len(matches) != 1:
        raise ValueError(f'匹配 {len(matches)} 个面，请进一步明确条件')
    return matches[0]

# component 使用返回清单中的完整实例名；不要依赖 GetComponents 的列表顺序。
hole = unique(lambda f: f['component'] == '支架-1' and f['kind'] == 'cylinder'
              and abs(f['radius_mm'] - 8) < 1e-6
              and abs(f['origin_local_mm'][0] - 80) < 1e-6)
shaft = unique(lambda f: f['component'] == '销-1' and f['kind'] == 'cylinder'
               and abs(f['radius_mm'] - 7.8) < 1e-6)
specs = [dict(type='concentric', face_a=hole, face_b=shaft)]
r = apply_face_mates(assembly, mates=specs)
assert r['ok'], r
# 也可用 fluent 接口；不要对同一对面重复执行两条示例。
# r = MateBuilder(assembly).concentric_faces(hole, shaft).apply()
```

重合配合使用 `type='coincident'` 或 `MateBuilder.coincident_faces(face_a, face_b)`，两个引用必须都是平面。
`alignment` 可为 `closest`（默认）、`aligned`、`anti_aligned`；平面按实际面法向验证方向。
默认几何回读误差阈值为0.001mm，不能通过无限放宽误差关闭验证。

## 面清单与作用域

- `face_ref` 是原生 `GetPersistReference3` 的Base64编码。`face_index` 仅用于诊断，不作为配合标识。
- 引用同时包含装配路径/配置、组件实例名、零件路径/配置与面类型。应用前解析原生持久引用并确认所属组件。
- `origin_local_mm`、`direction_local` 描述零件局部坐标；`origin_assembly_mm`、`direction_assembly` 已乘组件变换。位置和半径单位毫米，方向为单位向量。
- 同心配合允许孔轴半径不同。半径用于调用方识别目标几何，不是决定“能不能同心”的条件；几何间隙和加工合理性仍由设计人员判断。
- 可用 `list_mate_faces(..., component='支架-1', kind='cylinder')` 缩小只读枚举范围。

## 成功判定与失败处理

1. 两个目标面都能解析，文档、配置、组件和几何类型符合请求。
2. 选择集回读确认选中了请求的两个面，不自动改选其他面。
3. `AddMate5` 返回配合，且原生配合实体身份与请求一致。
4. 原生配合特征无错误；同心轴距或平面间距不超过阈值，方向符合约束。
5. 批次结束再次检查所有请求，避免后续配合破坏前面的结果。

全部请求先解析后再修改。中途失败会尝试删除本批新配合、恢复相关组件变换，并回读配合数量与变换；结果含 `rollback_ok`。这不是文件备份恢复，也不保证任意复杂装配的全局状态都可恢复。原有配合不会主动删除。
超时时操作状态记为 `mutation_state='unknown'`，请先检查装配，不能自动重试。进程、活动文档或配置变化时明确失败。
已有同类型同面配合会被拒绝，防止重复创建。

API 默认只修改内存；确认结果后由调用方保存。保存重开后使用 `inspect_face_mates(assembly, specs)` 只读核对持久引用、原生配合和几何误差。

## CLI / MCP

```powershell
swforge mate-faces 装配.SLDASM --component 支架-1 --kind cylinder --out faces.json
swforge mate 装配.SLDASM --spec mate_spec.json --save
swforge mate 装配.SLDASM --spec mate_spec.json --inspect
```

`mate_spec.json` 包含 `mates` 列表，格式与Python示例相同。CLI失败返回非零退出码。
MCP新增：`sw_list_mate_faces`、`sw_apply_face_mates`、`sw_inspect_face_mates`，沿用STA串行入口。

## 已修复的旧路径问题

原自动选面代码把 `ISurface.PlaneParams` 前三项当作位置、后三项当作法向。实际顺序相反；现在从后三项取位置、从 `IFace2.Normal` 取面法向。
自动路径也转换到装配坐标，并在创建后回读所选面之间的几何误差；仍不能保证自动选中的面符合设计意图，复杂零件应使用显式引用。

## 验证入口和边界

```powershell
python -m pytest tests -q -m "not sw"
swforge selftest --work-dir F:\证据\swforge_selftest --keep
python examples/verify_face_mates.py --work-dir F:\证据\新的专项目录 --keep
```

专项试件使用两个真实Ø16孔（局部x=20、80）及Ø15.6带肩销，检验同径歧义、90°旋转、持久引用、原生配合身份、失败批次回退、保存重开和干涉。
SolidWorks插入组件时可能带入平移，不能把局部x=80直接当作装配x=80；验收以变换后的真实目标轴为准。

当前仅实测SW2025 SP5.0，顶层已解析零件的圆柱面和平面。子装配、柔性/轻化组件、复杂过约束、缩放组件及SW2017/2019未验证。
持久引用不应跨装配副本重用，拓扑或配置变化后应重新枚举并核对；不承诺任何模型修改后引用永久有效。

官方参数依据：[平面法向与根点示例](https://help.solidworks.com/2022/english/api/sldworksapi/get_normal_of_planar_surface_example_vb.htm)、[组件变换](https://help.solidworks.com/2019/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IComponent2~Transform2.html)、[持久引用](https://help.solidworks.com/2014/english/api/sldworksapi/SolidWorks.interop.sldworks~SolidWorks.interop.sldworks.IModelDocExtension~GetPersistReference3.html)。兼容性以实机结果为准。
