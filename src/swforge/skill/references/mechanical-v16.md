> 2026-11-05：DS六项复审已优化并实机验证。中心剖切通过实际切面/20mm孔隙及保存重开核验；本地1.6.0，未发布。详见36号日志。下文停工状态为历史记录。

# v1.6 原生焊件与直齿轮

**停工交接：v1.6未完成整体验收。剖视重叠已修复，但真实中心切孔/剖面线未确认（GetFaceHatchCount=0）。当前安装仍1.5.1；未生成最终wheel/sdist、未安装1.6、未发布。以35号交接日志为准。**

本版本地开发基线为实际 v1.5.1，原目录名仍为 `swforge_v1.5.0`。本版源码独立在 `swforge_v1.6.0`。未获得发布授权。

## P1：十二杆 SHS 框架

```python
from swforge import create_weldment_frame
result = create_weldment_frame(
    r"F:\output\frame.SLDPRT", length=600, width=400, height=500,
    section=40, wall=3, material="Q235",
    drawing_path=r"F:\output\frame.SLDDRW")
assert result["ok"], result
```

尺寸为外包络 X/Y/Z，单位 mm。四根 X 杆长 length，四根 Y 杆长 width−2×section，四根 Z 杆长 height−2×section；端部为直角平切、明确的无间隙对接，不自动斜切、倒角、焊脚或工艺设计。原生结构构件由自建 `.sldlfp` 双矩形轮廓、3D 路径草图和 `InsertStructuralWeldment5` 建立，含原生 `WeldmentFeature`、`WeldMemberFeat` 和 Cut List。截面是锐角理想方管；不声称符合热轧/冷弯圆角型材截面。角钢、非正方 RHS、斜撑、复杂 Trim/Extend 暂未覆盖。

输出回读：每根实体体积/截面面积得到实际杆长，与原生清单长度/数量交叉比对；材料和质量密度单独核对。清单默认合并相同杆件，通常为三组×4；等长时可能进一步合并。图纸生成总尺寸、原生切割清单表和序号气泡，视图中遮挡的杆件可由其他视图编号。焊缝要求必须由调用方另外明确给定。

## P2：零变位外直齿圆柱齿轮

```python
from swforge import create_spur_gear
result = create_spur_gear(
    r"F:\output\gear.SLDPRT", module=2, teeth=24,
    pressure_angle=20, face_width=20, bore=12, material="45",
    drawing_path=r"F:\output\gear.SLDDRW")
```

输入：module 0.5–10 mm，teeth 整数18–120，pressure_angle 20–25°，face_width 正数，bore 为正且保留至少一个模数的径向轮缘；hub_diameter / hub_length 同时为0或同时为正，轮毂位于 +Z 齿端外侧。chord_error 为0.001–0.02 mm 的离散误差目标。

基准尺寸：d=mz，db=d cosα，da=m(z+2)，df=m(z−2.5)，分度圆弧齿厚πm/2，齿距πm，变位系数0。工作齿面使用自适应离散的渐开线折线，包含精确分度圆采样点；根部为径向过渡。模型包含原生根圆盘拉伸、单齿拉伸、参考轴和原生圆周阵列，可选原生轮毂。轴用于阵列，交付模型默认隐藏。

**这是有数值校验的几何与参数出图能力。根部不等于滚刀包络的真实过渡曲线；未验证接触、齿轮精度等级、热处理、承载或加工刀具。不能将其直接宣传为已通过制造认证的齿轮生成器。** 不支持变位、斜齿、内齿、锥齿、蜗轮或根切齿形。

图纸包括总尺寸、中心通孔原生直径标注、参数表；带轮毂样件补轮毂原生直径及剖视图。表格参数与模型原生自定义属性逐项核对。齿轮周向的外包络线性尺寸可能不同于公称齿顶圆直径（尤其齿数/齿相位变化时），应以参数表和几何公称尺寸区分，不用轮廓投影宽度代替公称直径。

## 家族变型与源保护

```python
from swforge import create_mechanical_variant
r = create_mechanical_variant(
    r"F:\output\gear.SLDPRT", r"F:\output\gear_28.SLDPRT",
    parameters={"teeth":28, "face_width":22},
    drawing_path=r"F:\output\gear_28.SLDDRW")
```

这里是**按参数重生成家族副本**，不是修改任意历史零件全部设计关系。原模型及 `.swforge.json` 必须一致、已保存且没有未保存修改；未知参数拒绝，输出必须全新路径，源模型SHA-256保持。原生特征可在SW编辑，但手工编辑后元数据会过期，禁止继续盲用旧参数出图。

`.sldlfp`、`.SLDPRT`、`.SLDDRW`、`.swforge.json` 和指纹文件应整体保留。跨电脑传递需放在同一目录并检查 SW 引用解析；此版未宣称任意目录迁移的 Pack and Go 完整支持。

`mechanical_drawing(part_path,new_path)` 不覆盖既有图纸。插原生焊件清单可能刷新模型缓存：只对本次新开的模型保存缓存，并同步元数据指纹；用户预先打开的模型有未保存变化时拒绝/返回待处理结果，不静默保存用户工作。构建器对自己刚创建的模型拥有保存权限。

CLI：`weldment-frame` / `spur-gear --spec parameters.json --out new.SLDPRT --drawing new.SLDDRW`；`mechanical-inspect`、`mechanical-variant`、`mechanical-drawing`。

MCP：`sw_create_weldment_frame`、`sw_create_spur_gear`、`sw_inspect_mechanical`、`sw_mechanical_variant`、`sw_mechanical_drawing`，沿用串行 STA worker。

## 复测和接口边界

```powershell
$env:PYTHONPATH="<此版本源码>\src"
python examples/verify_v16.py --work-dir F:\output\v16_repeat_new --rounds 2
```

路径必须未存在。保存原始几何/表格/图纸/PDF与文档数量；仅清理本轮生成文档，不强关用户文件。用户已要求本轮用新版本重复测试代替降级旧版的安装回滚。验收结论以实际证据为准，不把本说明当成通过证明。SW2017/2019兼容仍须另机验证。

参考：[SW原生结构构件接口](https://help.solidworks.com/2021/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeatureManager~InsertStructuralWeldment5.html)、[SW圆周阵列与选择标记](https://help.solidworks.com/2020/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~FeatureCircularPattern4.html)、[SW切割清单图纸示例](https://help.solidworks.com/2025/english/api/sldworksapi/Insert_Weldment_Cut_List_Table_Example_VB.htm)、[KHK齿轮尺寸参考](https://khkgears.net/new/gear_knowledge/gear_technical_reference/calculation_gear_dimensions.html)、[KHK原厂齿轮样件目录](https://khkgears.net/pdf/2023/spur-gears.pdf)。
