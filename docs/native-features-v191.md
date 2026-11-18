# Community 2.0：SolidWorks 原生建模特征

这七项通过 Python 的 PartBuilder 和既有的 JSON 接口使用。JSON 可以通过 CLI 的
build / --validate-only 或 MCP 的 sw_validate_part / sw_build_part 提交。长度单位为 mm，角度为度。
输出是新的 SLDPRT 文件。失败不保存半成品，也不覆盖原有文件。

| 功能 | Python 方法 | JSON 字段 | 首版范围 |
|---|---|---|---|
| 线性阵列 | linear_pattern | linear_patterns | 单方向 X/Y/Z；count 含母特征；spacing 为间距；reverse 反向 |
| 圆周阵列 | circular_pattern | circular_patterns | 绕经过原点的 X/Y/Z 轴等分；360°闭合不重复首件；angle 指定总角度 |
| 镜像 | mirror | mirrors | 以 xy/xz/yz 原点基准面镜像一个母特征 |
| 抽壳 | shell | shells | 单实体，单个轴向极值平面开口，等厚向内 |
| 筋 | rib | ribs | 单实体，同一平面上的一段开放直线，对称厚度 |
| 放样 | loft | lofts | 2–20 个平行圆截面，沿选定轴按位置递增 |
| 装饰螺纹 | cosmetic_thread | cosmetic_threads | 精确定位圆形起始边，盲螺纹，显式直径和深度，不切实体 |

## 快速示例

在源码目录执行：

    swforge build examples/native_20_pattern.json --out pattern.SLDPRT --validate-only
    swforge build examples/native_20_pattern.json --out pattern.SLDPRT

直接使用 Python：

    from swforge import PartBuilder

    result = (
        PartBuilder("shell_demo.SLDPRT")
        .box("case", -20, 20, 0, 30, -15, 15)
        .shell("open_case", "case", thickness=2, open_side="+y")
        .build(keep_open=False)
    )
    print(result.ok, result.native_features, result.error)

放样用 (x,y,z,半径) 声明截面。筋用世界坐标 start、end 声明草图直线，axis 是草图平面法向。
抽壳 open_side 取 +x/-x/+y/-y/+z/-z。该方向有多个候选面时拒绝自动选面。
装饰螺纹用 center 和 edge_diameter 精确指定起始边，diameter、depth 为实际螺纹显示尺寸，
note 是可选显示文字。不自动推导标准牙型或孔径。该特征不改变零件体积。

基础体及放样先建，随后切除、倒角和圆角，最后执行其他新特征。Python 在最后阶段
保留调用顺序；JSON 按字段定义顺序处理。母特征引用同一份建模描述里已有的实体形体或切除 tag，
不接管已有零件。原生特征可在 SolidWorks 中编辑，模型仍受实体连通性、选面唯一性和重建条件约束。
复杂截面和导引线、变壁厚、多体筋、双方向阵列、现有零件就地修改不属于首版范围。

## 验证

本轮在 SolidWorks 2019 SP5 与 2025 SP5 验证七类原生特征及反向、Z 轴和部分角度阵列，共每版 10 个用例。构建后重开保存文件，核对原生特征类型、错误码、体积及孔位；详见[验证范围](validation-community.md)。可复现入口为 `tools/validate_v191_features.py`。工程图保持公开 1.7 范围，图幅显式指定。

参考：[SolidWorks 线性阵列 API](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeatureManager~FeatureLinearPattern4.html)、
[抽壳 API](https://help.solidworks.com/2020/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~InsertFeatureShell.html)、
[筋 API](https://help.solidworks.com/2024/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~InsertRib.html)、
[放样 API](https://help.solidworks.com/2018/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~InsertProtrusionBlend2.html)。
