# swforge v1.4 交接文档 —— 粗糙度符号与公差标注

> 接收人：Codex
> 交接人：前一个开发会话
> 日期：2026-11-04
> 目标版本：**v1.4.0**
> 任务范围：**只做表面粗糙度符号和尺寸公差标注**（形位公差可选，见第 7 节）

---

# 0. 三十秒理解这个项目

**swforge 是用 Python / 命令行 / MCP 驱动本机 SolidWorks 的工具。**

```python
from swforge import PartBuilder, produce

b = PartBuilder("支架.SLDPRT", material="Q235")
b.box("底板", 0, 160, 0, 20, 0, 100)
b.cylinder("通孔", axis="y", x=80, y=20, z=50, r=8, h=20)
r = b.build()                       # r.volume_mm3 是**读回来的**，不是算的
produce("支架.SLDPRT", "支架.SLDRW", paper="A3")   # 三视图 + GB 图框
```

**当前的缺口，也就是你要补的：**

> 出的图有图框、标题栏、材料、重量、比例、尺寸标注，
> **但没有表面粗糙度、没有公差、没有形位公差。**
>
> **拿去加工会被退回来。这是唯一一个「直接影响能不能用」的缺口。**

---

# 1. 五条铁律（违反任何一条，代码不会被接受）

## 铁律 1：每一步都要回读验证

这是整个项目的立身之本。看一下现有代码的风格：

```python
# 建完 → 读回实体数和体积
r = builder.build()
assert r.volume_mm3 > 0            # 不是「调用没报错」，是读回来了

# 赋材质 → 用质量/体积反算密度
density = r.mass_kg / (r.volume_mm3 * 1e-9)
assert abs(density - 7850) < 1     # Q235 标准 7850
```

**你写的粗糙度和公差也必须这样：**

```python
sfs = md.Extension.InsertSurfaceFinishSymbol3(...)
# 不是 return bool(sfs is not None) 就完事
assert sfs is not None
assert sfs.GetSymbolType() == expected_type        # 读回符号类型
texts = [sfs.GetTextAtIndex(i) for i in range(sfs.GetTextCount())]
assert "3.2" in " ".join(texts)                    # 读回 Ra 值
```

**为什么：** 项目里所有严重 bug 都是「调用成功但结果是错的」。
`GetInterferences` 返回 1 处但明细空、配合 `ok=True` 但零件没动、
出图成功但只显示半个图框——**全是静默失败**。

## 铁律 2：中文命名，国标优先

- 零件/特征名用中文：`"底板"`、`"立柱"`、`"通孔"`
- 图框模板选中文 `gb_<纸张>.drwdot`
- 材料用国标牌号：Q235 / 45 / 40Cr / 6061-T6（**不要翻译成 AISI/EN 标准**）
- 注释和文档用中文

**竞品的共同弱点就是纯英文、没有国标概念。这是本项目唯一的差异化定位。**

## 铁律 3：单位是毫米，但 SolidWorks 内部是米

```python
# 建模 API 参数用 mm
b.box("底板", 0, 160, 0, 20, 0, 100)      # 160mm

# 但图纸坐标、视图位置是米
md.CreateDrawViewFromModelView3(model, "*前视", 0.18, 0.20, 0)   # 0.18m = 180mm
```

**粗糙度符号位置、公差标注位置都用米。** 这个换算错一次就会在图上找不到东西。

## 铁律 4：静默失败必须变成显式失败

已知的两个坑（都实测过）：

| 操作 | 症状 | 原因 |
|---|---|---|
| `CreateSectionViewAt4(x, y_same)` | 返回 `None`，**不报错** | 新视图和源视图位置重叠 |
| 画完剖切线后 `ClearSelection2()` | 返回 `None`，**不报错** | 辅助几何被取消选中 |

**你遇到 `None` / `False` 时，不要 `pass` 掉。** 返回结构化的错误：

```python
return {"ok": False, "error": "InsertSurfaceFinishSymbol3 返回 None —— 可能位置在图纸外"}
```

## 铁律 5：注释写「为什么」，不写「是什么」

```python
# 好
# 位置必须和源视图错开。实测：重叠时 API 直接返回 None，什么错都不报。
px, py = cx + offset, cy + offset_y

# 不好
# 设置位置
px, py = cx + offset, cy + offset_y
```

**SolidWorks 的坑不在文档里，只在踩过的人脑子里。** 写进注释是唯一能让它留下来的办法。

---

# 2. 代码结构

```
G:\GT\swforge\
├── src\swforge\
│   ├── __init__.py          导出 56 项（新功能要加进去！）
│   ├── session.py           连接、ping、属性读取辅助 _value()
│   ├── modeling.py          PartBuilder：box/plate/tube/cylinder/revolve/fillet
│   ├── drawing.py           produce() 出图、add_dimensions() 标注、export_pdf()
│   ├── dims.py              C# 模板：按视图朝向选标注轴（380 行，最难的模块）
│   ├── views_extra.py       剖视图 / 局部放大（v1.2 新增）
│   ├── assembly.py          AssemblyBuilder、check_interference()、read_volume()
│   ├── mates.py             配合（已知：复杂零件自动选面不可靠）
│   ├── bom.py               BOM 明细表
│   ├── gb_materials.py      20 个国标牌号 + 材质库部署
│   ├── guard.py             活动文档守卫（多客户端）
│   ├── resources.py         文档数守卫（SolidWorks 上限 8 个）
│   ├── selftest.py          10 项实机自检
│   ├── probe.py             28 项 API 反射探测
│   ├── status.py            swforge status
│   ├── release_check.py     发版一致性检查
│   ├── colors.py            分色
│   ├── cleanup.py           垃圾体清理
│   ├── batch.py             批量出图
│   └── cli.py               19 个 CLI 子命令
├── tests\                   172 项离线测试 + live_concurrency.py
├── docs\                    15 份文档
└── demo\                    演示脚本、GIF、封面
```

**你要新建的模块：`src\swforge\annotations.py`**

---

# 3. v1.4 任务：粗糙度符号

## 3.1 API 签名（已反射确认，不是猜的）

```python
# 首选（返回对象，可以回读）
sfs = md.Extension.InsertSurfaceFinishSymbol3(
    SymType,            # int    符号类型 —— 见 3.2，需实测
    LeaderType,         # int    引线类型
    LocX, LocY, LocZ,   # double 位置，**单位米**
    LaySymbol,          # int    加工纹理方向
    ArrowType,          # int    箭头类型
    MachAllowance,      # str    加工余量，如 "0.5"
    OtherVals,          # str    其他值
    ProdMethod,         # str    加工方法，如 "车"、"铣"
    SampleLen,          # str    取样长度，如 "2.5"
    MaxRoughness,       # str    上限 Ra，如 "3.2"
    MinRoughness,       # str    下限 Ra
    RoughnessSpacing,   # str    间距参数
) -> SFSymbol           # 返回对象 → 可以回读，用这个

# 备选（返回 bool，不能回读）
ok = md.InsertSurfaceFinishSymbol(...)   # IDrawingDoc，参数相同 -> Boolean
```

## 3.2 `SymType` 的取值 —— **需要你先实测**

`swSurfaceFinishSymbol_e` **不在** `swconst` 程序集里（我查过了）。
所以这个整数只能靠实测确定。

**实测方法**：写个脚本从 0 试到 8，每个插一次，导出 PDF 看图，
把每个值对应的符号形状记下来（√ 基本符号 / 去除材料 / 不去除材料 / 带横线……）。

**这一步不能省。** 猜错会让全图的粗糙度符号都是错的。

## 3.3 回读接口（`ISFSymbol`）

```python
sfs.GetSymbolType()        -> int      符号类型
sfs.GetTextCount()         -> int      文字数量
sfs.GetTextAtIndex(i)      -> str      第 i 段文字（Ra 值在这里）
sfs.GetTextHeightAtIndex(i)-> float
sfs.GetLeaderCount()       -> int
sfs.GetArrowHeadCount()    -> int
sfs.GetAnnotation()        -> 关联的 Annotation（可拿位置）
```

**验收时必须读 `GetTextAtIndex` 确认 Ra 值真的写进去了。**

## 3.4 建议的实现

```python
# src/swforge/annotations.py

def add_surface_finish(drawing_path=None, x=0.0, y=0.0, ra="3.2",
                       symbol_type=None, prod_method="", lay="",
                       verify=True) -> dict:
    """在工程图上加一个表面粗糙度符号。

    返回 {ok, type, ra_readback, texts, error}
    """
    ...
```

**需要做的判断**：

1. **位置从哪来？** 三个选择：
   - 调用方显式传 x, y（最简单，先做这个）
   - 从视图轮廓推算（`view.GetOutline()` 返回 `[x1,y1,x2,y2]`，单位米）
   - 从选中的面推算（复杂，v1.4 可以先不做）

   **建议：先支持显式坐标 + 视图轮廓两个来源。**

2. **默认值**：GB/T 131 常用 Ra 值 `0.4 / 0.8 / 1.6 / 3.2 / 6.3 / 12.5 / 25`。
   默认给 `3.2`（一般机加工最常见的值）。

3. **批量**：一个零件往往多个面要标。提供
   `add_surface_finishes(drawing, [{x,y,ra}, ...])`。

## 3.5 验收标准

```
[ ] 插入后 GetSymbolType() 与请求的一致
[ ] GetTextAtIndex 里能读到 "3.2"
[ ] PDF 导出后符号可见（不能只在内存里）
[ ] 位置在图纸范围内（0 < x < 幅面宽，0 < y < 幅面高）
[ ] 插入 5 个符号，视图数不变（符号不是视图）
[ ] 连续插入 20 次不崩（测资源泄漏）
```

---

# 4. v1.4 任务：尺寸公差

## 4.1 API 签名（已反射确认）

```python
# 从显示尺寸拿到 IDimension
disp_dim = ...                          # IDisplayDimension
dim = disp_dim.GetDimension2(0)         # -> Dimension

# 设置公差类型
dim.SetToleranceType(NewType)           # -> Boolean

# 设置上下偏差（对称公差用 ± 值）
dim.SetToleranceValues(TolMin, TolMax)  # -> Boolean

# 配合公差（如 H7/g6）
dim.SetToleranceFitValues(NewLValue, NewUValue)   # -> Boolean

# 回读
dim.GetToleranceType()    -> int
dim.GetToleranceValues()  -> Object（数组）
dim.GetToleranceFitValues() -> str
```

## 4.2 `swTolType_e` 枚举（已从 swconst 读出）

```
swTolNONE          = 0    无公差
swTolBASIC         = 1    基本尺寸（加框）
swTolBILAT         = 2    双向公差（+0.1/-0.1）
swTolLIMIT         = 3    极限尺寸（160.1 / 159.9）
swTolSYMMETRIC     = 4    对称公差（160 ±0.1）   ← 最常用
swTolMIN           = 5    最小
swTolMAX           = 6    最大
swTolMETRIC        = 7    公制
swTolFIT           = 7    配合（同名值）
swTolFITWITHTOL    = 8    配合+公差
swTolFITTOLONLY    = 9    只有公差
swTolBLOCK         = 10   块
swTolGeneral       = 11   一般公差
```

**v1.4 至少要支持：`BILAT`(2)、`LIMIT`(3)、`SYMMETRIC`(4)、`FIT`(7)**

## 4.3 怎么找到要标公差的尺寸

现有的 `add_dimensions()` 在 `drawing.py` 里，它已经能：
- 创建尺寸
- 按视图朝向选轴（`dims.py` 里的 C# 模板）
- 跨视图去重
- 返回 `{overall: {dims: [{view, horizontal, vertical, value}]}}`

**你需要在此基础上拿到 `IDisplayDimension` 对象。**

**建议路径**：给 `add_dimensions()` 的返回结构里加上尺寸对象引用，
或者新增一个 `list_dimensions(drawing)` 函数：

```python
def list_dimensions(drawing_path=None) -> list[dict]:
    """枚举工程图里所有尺寸，返回可操作的对象引用。

    返回 [{value, name, view, dim_obj, disp_obj}, ...]
    """
```

**注意**：pywin32 后期绑定下，`IDisplayDimension` 的方法可能表现为属性。
用项目里现成的 `_value(obj, "Name")` 辅助函数（见 `session.py`），
它会处理「可调用 vs 属性」的歧义。

## 4.4 建议的实现

```python
def set_tolerance(drawing_path=None, dim_name=None, dim_value=None,
                  tol_type="symmetric", upper=0.1, lower=None,
                  fit="H7/g6") -> dict:
    """给一个尺寸设置公差。

    tol_type: "symmetric" | "bilateral" | "limit" | "fit" | "none"
    返回 {ok, type_readback, values_readback, error}
    """
```

## 4.5 一个重要的设计判断：**要不要做「自动推荐公差」**

**不做。**

理由写在 `docs/limitations.md` 里，我原话抄过来：

> 公差等级取决于配合性质、加工能力、成本，这是**工艺知识**。
> **工具瞎标公差比不标更糟** —— 工人照做会出废品。

**v1.4 只做「把你给的公差标上去」，不做「替你想该给多少」。**

如果你觉得需要辅助，最多做到「按 GB/T 1800 查表给出 IT 等级的数值范围」，
**不要自动选等级**。

## 4.6 验收标准

```
[ ] SetToleranceType 后 GetToleranceType 读回一致
[ ] SetToleranceValues(-0.1, 0.1) 后读回是 [-0.1, 0.1]
[ ] 对称公差在 PDF 上显示为 ±0.1
[ ] 极限公差显示为 160.1 / 159.9
[ ] 配合公差能设 H7/g6 并读回
[ ] 设置后尺寸值本身不变（只加公差，不改名义值）
```

---

# 5. 形位公差（可选，做完上面两项再说）

## 5.1 API

```python
gtol = md.NewGtol()                     # IDrawingDoc -> Object（实际是 Gtol）
# 或
gtol = md.INewGtol()                    # -> Gtol

gtol.SetFrameValues2(FrameNumber, Tol1, Tol2, Datum1, Datum2, Datum3)
gtol.SetFrameSymbols2(FrameNumber, GCS, TolDia1, TolMC1, TolDia2, TolMC2,
                      DatumMC1, DatumMC2, DatumMC3)
gtol.SetPosition(X, Y, Z)               # 单位米

# 回读
gtol.GetFrameCount()      -> int16
gtol.GetFrameValues(n)    -> Object
gtol.GetFrameSymbols3(n)  -> Object
```

## 5.2 `swGtolGeomCharSymbol_e` 枚举（已读出）

```
swGcsNONE           = 12
swGcsSYMMETRY       = 13    对称度
swGcsSTRAIGHT       = 14    直线度
swGcsFLAT           = 15    平面度        ← 最常用
swGcsROUND          = 16    圆度
swGcsCYL            = 17    圆柱度
swGcsLINEPROF       = 18    线轮廓度
swGcsSURFPROF       = 19    面轮廓度
swGcsANG            = 20    倾斜度
swGcsPERP           = 21    垂直度        ← 最常用
swGcsPARALLEL       = 22    平行度        ← 最常用
swGcsPOSITION       = 23    位置度        ← 最常用
swGcsCONC           = 24    同轴度
swGcsCIRCRUNOUT     = 25    圆跳动
swGcsTOTALRUNOUT    = 26    全跳动
swGcsCIRCOPENRUNOUT = 27
swGcsTOTALOPENRUNOUT= 28
swGcsUBUTTON        = 29
swGcsSQUARE         = 30
```

## 5.3 需要实测的点

- `NewGtol()` 之后**怎么让符号真正出现在图纸上**？
  `SetFrameValues2` + `SetPosition` 是否足够，还是需要额外的 insert 调用。
  **这一点我没实测过，你要先试。**
- 基准符号（A、B、C）是单独的 API 还是 Gtol 的一部分。

---

# 6. 怎么验证（这是最重要的一节）

## 6.1 三级验证，缺一不可

```powershell
# 第 1 级：离线测试（不碰 SolidWorks，秒级）
python -m pytest tests -q -m "not sw"

# 第 2 级：实机自检（10 项，约 2 分钟）
swforge selftest

# 第 3 级：真实出图验证（导出 PDF 用眼睛看）
python -c "from swforge.drawing import export_pdf; ..."
```

**第 3 级不能省。** 这个项目里有过「调用成功、数据正确、但 PDF 上是空白」的情况。

## 6.2 导出 PDF 并看图的方法

```python
from swforge.drawing import export_pdf
import pypdfium2 as pdfium

export_pdf("图.SLDDRW", "图.pdf")
pdfium.PdfDocument("图.pdf")[0].render(scale=2.0).to_pil().save("图.png")
```

然后看那个 PNG。

## 6.3 自检要加新项

`selftest.py` 里现在有 10 项。**v1.4 应该加第 11、12 项：**

```
[PASS] 粗糙度符号可加可读      Ra=3.2 读回一致
[PASS] 公差可设可读           ±0.1 读回 [-0.1, 0.1]
```

**注意**：加检查项时要考虑文档数上限（SolidWorks 最多 8 个），
每项检查完必须关闭文档。现有代码里 `_close_created()` 就是干这个的。

## 6.4 单元测试怎么写

项目里能离线的测试都走「生成源码快照」路线——
不碰 COM，只断言生成的 C# / COM 调用序列正确。

参考 `tests/test_generated_source.py`。

---

# 7. 不能做的事（硬禁区）

| 禁止 | 原因 |
|---|---|
| ❌ 改 `docs/issue-log.md` 里已记录的结论 | 那是实测记录，不是草稿 |
| ❌ 用 `GetActiveObject` | 项目整体禁用，只用 `Dispatch`（见 `docs/why-getactiveobject-fails.md`） |
| ❌ 把国标材料翻译成欧美标准 | Q235 不能变成 A36，这是项目的差异化定位 |
| ❌ 自动推荐公差等级 | 工艺知识，做不好会害人 |
| ❌ 声称「支持」但没实测过 | 只测过 SW 2025 SP5.0，其他版本必须写「未验证」 |
| ❌ 删除或改写 `CHANGELOG.md` 历史 | 只追加 |
| ❌ 在测试里 `time.sleep` 超过 3 秒 | 会让 CI 变慢，用轮询代替 |

---

# 8. 发版流程（v1.4.0 完成时）

```powershell
# 1. 改版本号（两处，必须一致）
#    pyproject.toml:  version = "1.4.0"
#    src/swforge/__init__.py:  __version__ = "1.4.0"

# 2. 更新 CHANGELOG.md 和 CHANGELOG.en.md（中英都要）

# 3. 跑全部验证
python -m pytest tests -q -m "not sw"
swforge selftest

# 4. 提交并推送
git add -A
git commit -m "feat: surface finish symbols and dimension tolerances"
git push

# 5. 打标签（会触发 GitHub Actions 自动发布）
git tag -a v1.4.0 -m "v1.4.0 - 粗糙度与公差"
git push origin v1.4.0

# 6. 等 CI 构建完，到 Actions 页面批准 pypi 环境的部署
#    （用户已授权「自动批准但必须告知」，所以可以自动批准，
#      但要在汇报里明确写「已自动批准」）

# 7. 验证真的发出去了
swforge status

# 8. 同步归档到 F 盘（这一步经常被忘）
python F:\SW+AI\_tools\sync_archive.py

# 9. 更新 F 盘文档
#    01_文档\28_v1.4.0_发布说明.md（新建）
#    01_文档\00_项目总览.md（版本号、能力）
#    01_文档\01_开发日志.md（追加一段）
```

**第 8 步曾经被忘过，导致归档落后 8 个版本。现在有工具了，别忘。**

---

# 9. 环境信息

| 项 | 值 |
|---|---|
| 仓库 | `G:\GT\swforge`（git，远端 `git@github.com:mwdandoms/swforge.git`） |
| 归档 | `F:\SW+AI`（源码快照 / 发布包 / 文档） |
| SolidWorks | `E:\SW2025\SOLIDWORKS\SLDWORKS.exe`，版本 2025 SP5.0（`RevisionNumber()` = `33.5.0`） |
| Python | 3.14.3（系统），另有 3.10+ 兼容要求 |
| 互操作库 | `SolidWorks.Interop.sldworks.dll` / `swconst.dll`，版本 33.5.0.53 |
| 模板目录 | `C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates`（`gb_a3.drwdot` 等） |
| PyPI | `swforge` 1.3.1 |
| 文档站 | https://mwdandoms.github.io/swforge/ |

## 9.1 已知的环境坑

| 现象 | 原因 | 处理 |
|---|---|---|
| `Dispatch` 拉起的 SW 没有窗口 | 默认 `Visible=False` | 显式 `sw.Visible = True` + `ShowWindow` |
| `EditRebuild3()` 报 `'bool' object is not callable` | pywin32 把无参方法暴露成属性 | 用 `_value(md, "EditRebuild3")` |
| `GetInterferences()` 报错 | 同上，是属性不是方法 | 用 `_value(mgr, "GetInterferences")` |
| `Extension.CreateMassProperty()` 找不到成员 | 后期绑定取不到 | 用 `IBody2.GetMassProperties(1.0)` |
| 文档数到 8 就失败 | SolidWorks 硬上限 | 用 `resources.py` 的守卫 |
| 中文 `.bat` 报 `'ODING' is not recognized` | cmd.exe 按字节读 | `.bat` 只用 ASCII |

---

# 10. 参考资料

## 项目内

| 文档 | 内容 |
|---|---|
| `docs/issue-log.md` | **278 行，所有已修复和未修复问题的完整排查记录** |
| `docs/limitations.md` | 明确的做不到的事 |
| `docs/pitfalls.md` | 踩坑清单 |
| `docs/features.md` | v1.2 全部能力 + 实测数据 |
| `docs/why-getactiveobject-fails.md` | 为什么禁用 GetActiveObject |
| `F:\SW+AI\01_文档\03_不足与风险.md` | P-01~P-07，含公差缺口的详细说明 |
| `F:\SW+AI\01_文档\01_开发日志.md` | 完整开发过程（635+ 行） |

## 外部

- SolidWorks API Help：在本机 `E:\SW2025\SOLIDWORKS\api\` 下
- 用反射查 API 的方法：
  ```powershell
  $asm=[System.Reflection.Assembly]::LoadFrom("E:\SW2025\SOLIDWORKS\SolidWorks.Interop.sldworks.dll")
  $t=$asm.GetType("SolidWorks.Interop.sldworks.IModelDocExtension")
  $t.GetMembers() | Where-Object { $_.Name -match 'SurfaceFinish' }
  ```
  枚举在 `SolidWorks.Interop.swconst.dll` 里。

---

# 11. 任务清单（按顺序做）

```
[ ] 1. 跑通现有环境
        pip install -e .
        swforge selftest        ← 必须 10/10 通过才开始
        python -m pytest tests -q -m "not sw"   ← 172 项

[ ] 2. 实测 SymType 取值（0~8 逐个插，导 PDF 看图）
        把结果写成 docs/surface-finish-symbol-types.md

[ ] 3. 实现 add_surface_finish() 单个符号
        含回读验证

[ ] 4. 实现 add_surface_finishes() 批量
        位置从视图轮廓推算

[ ] 5. 实现 list_dimensions() 枚举尺寸对象
        这是公差的前置

[ ] 6. 实现 set_tolerance() 四种类型
        SYMMETRIC / BILAT / LIMIT / FIT

[ ] 7. 加 CLI 子命令
        swforge surface-finish --ra 3.2 --x 0.1 --y 0.2
        swforge tolerance --dim "D1@草图1" --type symmetric --upper 0.1

[ ] 8. 加 selftest 第 11、12 项

[ ] 9. 更新文档
        docs/features.md、docs/limitations.md、CHANGELOG 中英

[ ] 10. 发版 v1.4.0 + 同步归档
```

---

# 12. 一句话总结

> **这个项目的价值不在于「能调 API」，而在于「调完敢说它对」。**
>
> 你加的每一个粗糙度符号、每一个公差，都必须能被读回来验证。
> 如果做不到回读，那就说明这条路走不通，**应该报告而不是绕过**。
>
> 图纸能不能直接投产，取决于你这一版。

---

**有疑问时优先看 `docs/issue-log.md`——那里记录了 278 行的踩坑过程，
比你重新踩一遍快得多。**
