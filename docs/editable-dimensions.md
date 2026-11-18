# SW2019 可编辑原生尺寸

swforge 1.9.8 起，`PartBuilder` 构建支持的形体时默认在零件内保留原生驱动尺寸。通过 `PartBuilder` 的 CLI、MCP 和 Python 建模声明共享此默认值。装配交付仍需带齐引用文件。

| 建模入口 | SolidWorks 里的改尺寸位置 |
| --- | --- |
| box、plate、cut_box | 在相应拉伸或切除下展开草图，修改 `ProfileWidth` 和 `ProfileHeight` |
| cylinder、hole | 在对应草图修改 `Diameter`。非零的孔心或圆心坐标有 `CenterOffsetX`、`CenterOffsetY`，按草图坐标系读取 |
| compact 双轮廓方管 | 在 `SWFORGE_<tag>_section` 截面草图修改原生驱动尺寸。截面约束由 SW 生成 |
| 拉伸和切除 | 在原生特征编辑原有长度或深度。通孔继续使用贯穿条件 |

矩形以一个角点为锚点，修改尺寸时从该角点伸缩。两边对称变化、孔组对中或等壁厚等设计关系，应按工程意图另外定义。可在 SolidWorks 中检查草图和方程，也可用 `list_model_parameters` 查询当前可用键，使用 `set_parameters` 另行验证改值。基础零件的尺寸嵌入在 `.SLDPRT` 内。使用 SW2019 生成后，同版本能直接打开编辑。

构建过程检查新增尺寸是否驱动，重建后核对实体数量、包络、各实体体积和特征错误。日志用 `SWFORGE_EDITABLE` 记录通过的轮廓。遇到专用历史样件或明确要求保留旧建模行为，Python 调用可传 `editable_dimensions=False`。因此选项不转换已有文件，也不为 STEP 或 Parasolid 导入实体自动补特征，不自动推导任意轮廓的方程或装配配合。复杂特征保留各自原生入口。

复验命令（SolidWorks 2019 已启动时运行）

```powershell
$env:SWFORGE_SW_YEAR='2019'
$env:PYTHONPATH=(Join-Path (Get-Location) 'src')
python tools/verify_editable_dimensions.py '<验收输出目录>'
```
