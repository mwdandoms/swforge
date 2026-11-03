# 问题日志

记录开发过程中发现的真实问题。**包括已经修好的，和目前还没修的。**

为什么要公开这个：一个只展示成功记录的项目不可信。
下面的每一条都对应一次实际失败，能查到具体现象和修复提交。

---

## 已修复

### 2026-11-03 · 干涉检查「计数有、明细空」

**现象**
`check_interference()` 返回 `interference_count: 1`，但 `interferences` 是空列表。
调用方知道有干涉，但不知道是**哪两个零件**相交，也拿不到干涉体积。

**根因**
`IInterferenceDetectionMgr.GetInterferences` 在 pywin32 后期绑定下是**属性**（返回 tuple），
不是方法。代码写成 `mgr.GetInterferences()` 抛 `TypeError: 'tuple' object is not callable`，
被外层 `except Exception: raw = None` 吞掉，于是明细变成空。

**为什么难发现**
计数是从另一处 `GetInterferenceCount` 读的，正常返回 1。
所以整个调用「看起来成功了」，只是明细为空——没有报错、没有异常、没有警告。

**修复**
改用 `_value()` 统一处理「属性还是方法」的不确定性，并补充从
`Volume` / `InterferenceVolume`、`Components` / `GetComponents` 多路径提取。

**验证**
两个 20mm 立方沿 X 偏移 10mm 装配：
```
{'volume_mm3': 4000.0, 'components': ['a-1', 'b-1']}
```
理论值 10×20×20 = 4000，偏差 0.00%。

提交 `9f3ad42`

---

### 2026-11-03 · 尺寸过度标注 + 非主视图标注值错误

**现象一：数量**
一个 20 个特征的支架，自动标注出 **22 个尺寸**，全部堆在视图同一边互相重叠，图纸不可用。

**排查**
逐个测标注类型位：
```
INS_DIMS(8)        →  0 个
MARKED(32768)      → 22 个
NOT_MARKED(524288) →  0 个
所有组合            → 22 个
```
说明**不是类型选错**——SolidWorks 自己摆放时不做避让，也没有对应开关。

**修复一**
改成受控标注：自己选极值顶点建尺寸，位置由我们决定；
内部特征尺寸只取最大的几个跨度（≥总长 15%），并做跨视图去重。
结果 **22 → 9 个**。

**现象二：值错了**
右视图标出 **114**，实际深度是 **120**。

**根因**
用**模型坐标 X/Y** 找极值——这只对主视图成立。
右视图的屏幕水平方向是模型 **Z**，上视图的竖直方向也是模型 Z。
选错了顶点对，SolidWorks 算出的是错的值。

**修复二**
按 `IView.GetOrientationName()` 选择投影轴：
前视用 X/Y，上视用 X/Z，右视用 Z/Y。

**验证**
```
工程图视图1（主视）  H=160  V=140  I=80  I=40
工程图视图2（俯视）  H=160  V=120  I=28
工程图视图3（右视）  H=120  V=140
```
深度 120 是对的——立柱比底板多探出 20mm。

提交 `163a06e`

---

### 2026-11-03 · PyPI 首次上传被拒：写了不存在的 classifier

**现象**
上传返回 `HTTP 400 Bad Request`，Actions 页面上看不出原因。

**根因**
`pyproject.toml` 里写了：
```
"Topic :: Scientific/Engineering :: Computer Aided Design"
```
这个 classifier **在 PyPI 上不存在**。官方 320 个 Topic 里最接近的是
`Topic :: Scientific/Engineering` 和 `Topic :: Multimedia :: Graphics :: 3D Modeling`。

错误信息藏在 HTML 响应体里，要点进日志逐行看才能发现。

**修复**
换成 13 条逐条验证过的 classifier，并给发布 workflow 加了强制检查：
上传前下载官方清单，任何 classifier 不在清单里就拒绝上传。

提交 `52a0b57`

---

### 2026-11-03 · `swforge --help` 在非中文 Windows 上崩溃

**现象**
CI 报 `UnicodeEncodeError: 'charmap' codec can't encode characters`。
一个陌生人装完之后跑的**第一条命令**就崩。

**根因**
标准输出编码是 cp1252 时，打印中文帮助文本抛异常。

**修复**
`_make_output_safe()` 用 `errors='replace'` 兜底；
JSON 输出在单字节编码下转义成 `\uXXXX`，保证机器还能解析。

提交 `2d7eb8d`

---

### 2026-11-03 · 自检工具自己把文档名额占满

**现象**
`swforge selftest` 前 5 项通过，后 4 项连环失败，报
`SW 文档名额不足：需要 1，当前 8/8`。

**根因**
「资源守卫」这一项故意建了 3 个文档来测试，但**没关掉**。
后面每一项都要建文档，全被 8 个上限挡住。
自检工具自己制造了它要检测的问题。

**修复**
每项检查跑完调用 `_close_created()` 关掉自己建的文档；
runner 在每项之间再扫一遍。

**教训**
测试工具本身也需要测试。第一次跑出 9/9 是通过的，
但那是环境干净时；在真实场景（前一项留下垃圾）下就暴露了。

提交 `9f3ad42`

---


### 2026-11-04 · BOM 实机验证发现的三个问题

**问题 1：`GetComponents` 被当成无参方法调用**

`session._value()` 的判断是「有 `_oleobj_` 就不调用」，但通过 `getattr` 拿到的
绑定方法**没有** `_oleobj_`，于是它被无参调用，COM 抛
`-2147352561 非选择性的参数`（`DISP_E_PARAMNOTOPTIONAL`）。

`IAssemblyDoc.GetComponents(Boolean ToplevelOnly)` 必须显式传参。
修复后 BOM 能正确读到 4 个组件。

**问题 2：`_value` 把 COM 对象当函数调用**

比问题 1 更隐蔽：`IComponent2.GetModelDoc2` 在后期绑定下**直接返回文档对象**
（`CDispatch`），而 COM 对象本身是 callable 的。
我的 `_value` 看到 callable 就 `v()`，等于把整个文档当函数执行，
返回 `None` —— **不报错，静默失败**。

结果就是材料永远读不到（显示「未指定」），但流程看起来一切正常。

修复：判断顺序改成「带 `_oleobj_` 的当成对象原样返回，其余 callable 才调用」。

**问题 3：组件自身的材料方法读不到材料**

实测在 SolidWorks 2025 SP5.0 上：

```
IComponent2.GetMaterialUserName()        -> ''（空）
IComponent2.GetMaterialIdName()          -> ''（空）
ModelDoc2.GetMaterialPropertyName2()     -> 'Q235'   ← 只有这个能读到
ModelDoc2.MaterialIdName                 -> 'swforge_gb_materials|Q235|9015'
```

而且 `GetMaterialPropertyName2` 的第二个参数是**字符串出参**，
必须传 `VARIANT(VT_BSTR | VT_BYREF)`，直接传普通字符串报「类型不匹配」。

修复后 BOM 材料列正确显示 Q235，`missing_material` 为空。

**验证结果**

```
装配：底板 ×1 + 垫片 ×3
种类 2 项，共计 4 件
1. 垫片  x3  [Q235]
2. 底板  x1  [Q235]
缺材料：[]
```

---

## 未修复 / 已记录

### BOM 表插入成功但位置不可控

**现象**
`insert_bom_table()` 返回 `{'ok': True, 'rows': 3, 'columns': 3}`，
图纸上确实有 1 个表格注解（`GetTableAnnotationCount` = 1），
但**导出 PDF 后表格不在页面上**。

`use_anchor=False` 时给 `(0.02, 0.02)`，表格落在图框外；
改成 `use_anchor=True`（用模板定义的 BOM 锚点）后，仍然不可见。

**排查到的限制**
`TableAnnotation` 在 pywin32 后期绑定下：
```
GetPosition    -> AttributeError（取不到）
SetPosition    -> 无效果
TextHeight     -> AttributeError
```

**也就是说位置既读不到也改不了**，无法靠代码调整。

**当前状态**
- BOM **数据提取**（材料、数量、合并）已实机验证通过 ✅
- BOM **表格插入**返回成功、行列数正确，但**位置需要进一步排查** ⚠️

**下一步**
- 用 C# 早期绑定读 `ITableAnnotation.GetPosition`（pywin32 拿不到的，
  和 `DisplayDimension.GetAnnotation` 是同一类限制）
- 或者在工程图模板里预置 BOM 锚点，验证锚点模式

**影响**
`swforge bom` 命令（读明细 + 导出 CSV）**不受影响，可以正常使用**。
只有「自动插表到工程图」这一项还没达到可用状态。



### 2026-11-04 · 配合在复杂零件上自动选面不可靠

**现象**
演示脚本里用「支架（含 Ø16 通孔）+ 销（Ø15.6）」做配合，结果：

```
coincident(0,1)                  ok=True   位置 [0.0, 200.0]  没动
concentric(0,1, tol=0.05)        ok=False  位置 [0.0, 200.0]  明确报错
concentric(0,1, tol=0.5)         ok=True   位置 [0.0, 0.0]    落错位置
```

孔在 x=80，但同心配合把销放到了 x=0，于是销压在板边缘，
随后干涉检查报出 **2 处假干涉**（3822.69 + 1911.345 mm³）。

**根因**
`MateBuilder.concentric(a, b)` 只接受**组件索引**，内部自动挑选圆柱面。
在零件有多个圆柱面/圆弧面时，挑中的不一定是目标那一个。
同类项目有相同问题（andrewbartels1 #199：fillet/chamfer 测试打到了错误的面）。

**为什么 `tol=0.05` 反而报错**
销 Ø15.6 配孔 Ø16，半径差 0.2mm 超出默认公差 0.05mm。
这时 API 返回 `ok=False` —— **这个行为是诚实的**，比静默失败好。
放宽到 0.5 才「成功」，但选错了面。

**当前处理**
- 演示脚本改用两块简单板做配合（这个场景位置正确、可复现）
- 复杂零件的配合**不宣称可用**

**计划**
`concentric` 应支持显式指定面索引，而不是靠自动挑选。
需要先用 `probe.py` 的反射能力枚举组件的圆柱面及其半径，
再按目标半径筛选。这是 v1.2 的工作。

---

### 2026-11-04 · 出图后没有缩放到适合，只显示半个图框

**现象**
`produce()` 生成工程图后，A3 幅面在窗口里只显示一部分，
录屏和截图时第一眼看到的是半个图框。

**根因**
创建视图后没调用 `ViewZoomtofit2()`。

**修复**
在 `produce()` 保存前、以及 `add_dimensions()` 标注后各调用一次
`md.ViewZoomtofit2()` —— 标注会改变视图范围，所以两处都要。

---

### 2026-11-04 · SolidWorks 由 COM 拉起时没有可见窗口

**现象**
用 `Dispatch('SldWorks.Application')` 启动的 SolidWorks，
`Visible` 属性是 `False`，`MainWindowHandle` 是 0 —— **没有窗口**。

**影响**
录屏录不到任何画面；截图也是空的。

**修复**
显式设置 `sw.Visible = True`，再用 `FindWindowW` + `ShowWindow` + `SetForegroundWindow`
把它切到前台。演示脚本的 `focus_sw()` 就是做这件事。

**顺带发现**
`Start-Process "E:\SW2025\SLDWORKS.exe"` 路径是错的，正确路径是
`E:\SW2025\SOLIDWORKS\SLDWORKS.exe`（中间有子目录）。


### 2026-11-04 · BOM 表「插了看不见」—— 两个原因都不是库的 bug

**现象**
`insert_bom_table()` 返回 `{ok: True, rows: 3, columns: 3}`，
但导出的 PDF 上看不到表。

**排查**
表其实一直插对了，在标题栏正上方（GB 明细表的标准位置）。看不见的原因是：

1. **插入后没重新缩放**。视图还停在模型上，表在视野之外。
2. **模板回退**。装配图模板 `gb_assembly.drwdot` 不存在时，
   代码回退到目录里第一个 `.drwdot`，实际是 `gb_a0.drwdot`。
   A0 是 841×1189mm，表缩到 2 倍比例后小得看不见。

**修复**
- `insert_bom_table()` 插完自动 `ViewZoomtofit2()`
- 文档写明：装配图要用 A3 模板，别让它回退

**顺带修的问题**
BOM 里显示的是组件实例名（`垫片-3`），合并计数后变成「垫片-3 ×3」。
改用零件文件名，显示「垫片 ×3」。

**结论**
`ITableAnnotation` 上**没有** `GetPosition` / `SetPosition`；
位置由 `Anchored` + `AnchorType` 控制，而 `AnchorType` 在 pywin32 下
赋值不生效（读了还是原值）。所以想控制位置只能靠锚点 + 正确幅面的模板，
不能靠坐标。这一点已写进 `insert_bom_table` 的 docstring。

---

### 2026-11-04 · 剖视图 / 局部放大：两次静默失败

**现象一：新视图位置和源视图重叠时返回 None**
```python
sec = md.CreateSectionViewAt4(cx + 0.20, cy, 0, "A", 0, None)   # None
sec = md.CreateSectionViewAt4(cx + 0.20, cy - 0.10, 0, "A", 0, None)  # 成功
```
不给 Y 偏移时，新视图和源视图位置重叠，SolidWorks 直接返回 `None`，
**不抛异常、不报错**。

**现象二：清掉选择后返回 None**
画完剖切线后如果调 `ClearSelection2(True)`，再生成剖视图也是 `None`。
辅助几何（剖切线、放大圆圈）必须保持选中状态。

**修复**
- `add_section_view()` / `add_detail_view()` 默认带 Y 偏移
- 退出草图后不清选择
- 两处都写了注释说明原因

**实测**
3 个视图 → 6 个，生成 `剖面视图 A-A`、`剖面视图 B-B`、`局部视图 I`。

---

### 2026-11-04 · CreateMassProperty 在 Python 里不可用

**现象**
```python
ext = md.Extension
mp = ext.CreateMassProperty()
# com_error: (-2147352573, '找不到成员。')
```

**原因**
`IModelDocExtension.CreateMassProperty` 在 pywin32 后期绑定下取不到。
`modeling.py` 之所以能用，是因为它走的是**编译后的 C#**（早期绑定）。

**解决**
Python 侧改走 `IBody2.GetMassProperties(1.0)` —— 传密度 1.0，
返回数组第 4 项（下标 3）是体积，单位 m³：

```python
for b in md.GetBodies2(0, True):
    mp = b.GetMassProperties(1.0)
    total += float(mp[3]) * 1e9        # m³ -> mm³
```

已封装为 `read_volume()`。

---

### 2026-11-04 · 多客户端并发：实测通过

**测试方式**
两个独立 Python 进程，同时操作同一个 SolidWorks 实例。

**结果**
```
进程 A: connect / build / open_own / reclaim / readback   全通过
进程 B: connect / build / open_own / reclaim / readback   全通过
A 被切到 并发_B -> 抢回 并发_A
B 被切到 并发_A -> 抢回 并发_B
```

关键证据是 `readback`：抢回后读到的体积是 24000.0 mm³，
与各自建的零件一致 —— 证明读到的是**自己的**文档，不是对方的。

**之前的状态**
`guard.py` 的并发逻辑只做过同进程内模拟（selftest 第 10 项）。
现在补上了真正的双进程验证。

---

### 2026-11-04 · 发版检查脚本：第一步就抓到自己

写 `release_check.py` 的测试时，`test_source_change_with_version_bump_passes`
**失败**了。原因是我的实现把「源码改了 + 版本号已升」也判成「漏发」。

这个状态其实很正常：改了代码、升了版本号、还没打新标签。
判错会让每次开发中途都报红。

改成：
- 源码改了 + 版本号没动 → **错误**（真的漏发）
- 源码改了 + 版本号已升 → **提醒**（正常准备发版）

**测试写完就抓到了自己的逻辑错误**，这正是写测试的理由。


## 其他未修复项

### Dispatch 会启动第二个 SolidWorks 实例

**现象**
机器上出现 2 个 `SLDWORKS.EXE` 进程，之后所有 COM 调用报
`MK_E_UNAVAILABLE (0x800401E3)`，连接时好时坏。

**原因**
项目规定「只用 Dispatch，禁 GetActiveObject」（SolidWorks 不注册 ROT）。
`Dispatch('SldWorks.Application')` 找不到已注册实例时会**新开一个**，
于是有了两个实例，互相抢 ROT 条目。

**当前的缓解**
清缓存后重连；selftest 遇到 `rot_failed` 会自动重试一次。

**还没解决**
没有主动检测「已有多个实例」并给出提示。
计划：`swforge selftest` 开工前检查进程数，多于一个就警告并说明原因。

---

### session 缓存在实例重启后失效

**现象**
SolidWorks 实例被杀掉重启后，同一个 Python 进程里的 COM 指针全部失效，
后续调用报 `rot_failed`。

**当前缓解**
selftest 里对 `rot_failed` / `Operation unavailable` 做一次重连重试。

**还没解决**
`session.py` 没有「连接已失效就自动重建」的统一机制，
每个调用方要自己处理。计划在 v1.2 里做。

---

### 干涉检查的明细字段依赖多路径猜测

**现状**
体积从 `Volume` 或 `InterferenceVolume` 里试，零件名从 `Components` 或
`GetComponents` 里试。目前两条路径都命中了，但这种「试出来」的写法不够稳。

**计划**
用 `probe.py` 的反射机制确认 `IInterference` 到底暴露哪些成员，
把猜测换成确定。

---

### 多客户端并发未处理

**现状**
两个 agent 同时连一个 SolidWorks 时，任一方的 `ActivateDoc` 都会把
对方的活动文档切走。同类项目有这个 issue（hjbaard #10）。

**计划**
v1.1 实现「活动文档守卫」：操作前记录目标文档，操作后回读确认，
发现被别人切走就重新激活并重试。

---

## 环境相关（非代码问题）

### 中文写入 .bat 会导致 cmd 解析失败

**现象**
批处理文件里任何位置出现中文（即使放在引号内），cmd 都会把命令行截断，
报 `'ODING' 不是内部或外部命令` 这类看不懂的错误。

**原因**
cmd.exe 逐字节读取 .bat，用当前代码页解释。UTF-8 的中文字节会被误解析，
甚至破坏行结构。`chcp 65001 >nul` 放在第一行也救不了——文件本身已经被读坏了。

**做法**
`.bat` 只写 ASCII，中文全部由 Python 输出（配合 `chcp 65001` +
`PYTHONIOENCODING=utf-8`，实测 ✓ ✗ mm³ → 【】 全部正常显示）。
