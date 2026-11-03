**中文** | [English](pitfalls.en.md)

# 踩坑记录

这份文档是本项目最值钱的部分 —— 每条都是真实踩过、并且**靠独立回读才查清**的。

---

## 1. `errStatus` 的 0 不一定表示成功

`IAssemblyDoc.AddMate5` 的最后一个 out 参数是 `swAddMateError_e`：

```
swAddMateError_ErrorUknown    = 0
swAddMateError_NoError        = 1     ← 成功是 1，不是 0
swAddMateError_IncorrectSelections = 4
```

**教训**：**别假设"0 就是成功"**。查枚举，别猜。

---

## 2. `IBody2.Operations2` 只接受 API 临时体

对文档里的实体直接求交：

```
Operations2(SWBODYINTERSECT=15901, toolBody, out err)
→ 返回 (None, 1)
```

`swBodyOperationError_e` 里 **1 = `swBodyOperationNonApiBody`**。

**解法**：

```python
ta = body_a.Copy2(False)      # IsTemporaryBody() → True
tb = body_b.Copy2(False)
res = ta.Operations2(15901, tb, 0)   # out 参数传普通 int
arr, code = res                       # 返回 (结果, 错误码)
```

**另一个坑**：out 参数传 `VARIANT(VT_BYREF|VT_I4)` 会报
`TypeError: int() argument must be ... not 'VARIANT'`，必须传**普通 int**。

---

## 3. 后期绑定拿不到面/边/顶点的某些方法

| 调用 | pywin32 后期绑定 | C# 早期绑定 |
|---|---|---|
| `IFace2.GetSurface()` | ❌ 找不到成员 | ✅ |
| `IEntity.Select4()` | ❌ 类型不匹配 | ✅ |
| `IVertex.GetPoint()` | ❌ TypeError | ✅ |
| `IComponent2.GetBodies2(0)` | ⚠️ 参数个数不同 | ✅ |

**结论**：涉及面 / 边 / 顶点 / 组件的操作，一律走生成的 C#。

补充：`IFace2` 不继承 `IEntity`，但底层 `Face2` 对象支持 `IEntity` 的 QI，
所以 C# 里要写 `(IEntity)(object)face`。

---

## 4. SolidWorks 不注册 ROT

`Marshal.GetActiveObject("SldWorks.Application")` 只在 SW 由**交互式启动**时成功。
由 COM `Dispatch` 从后台拉起时：

```
COMException 0x800401E3 (MK_E_UNAVAILABLE)
```

**解法**：两级 fallback

```csharp
try { sw = (ISldWorks)Marshal.GetActiveObject("SldWorks.Application"); }
catch { sw = (ISldWorks)Activator.CreateInstance(Type.GetTypeFromProgID("SldWorks.Application")); }
```

**还要做真实往返探测**（`RevisionNumber()` + `GetDocumentCount()`），
因为 `Activator.CreateInstance` 有时返回**空壳代理**，只看非空会误判。

---

## 5. 材质库必须放在 SW 扫描目录

同一份 `.sldmat`：

| 位置 | 结果 |
|---|---|
| `E:\...\lang\chinese-simplified\sldmaterials\` | ✅ 生效 |
| `%LOCALAPPDATA%\swforge\` | ❌ 静默失败，密度退回 1000 |
| `C:\ProgramData\SOLIDWORKS\SOLIDWORKS <年>\自定义材料\` | ✅ 生效 |

而且 SW 自带中文库**没有 GB 钢牌号**（没有 Q235 / 45 / 40Cr），
所以必须自己生成。生成时**从原生库克隆材料节点**，只改名字和 DENS/EX/NUXY ——
手拼 XML 会被判为无效库。

---

## 6. 单位在边界处换算一次

`IAssemblyDoc.AddComponent5(path, ..., X, Y, Z)` 内部要**米**，
而项目约定是**毫米**。不换算的后果：零件被放到 **60 米外**，
连带让"5 mm 重叠"的干涉测试永远测不出重叠。

**约定**：对外一律毫米，进 COM 前除以 1000，出 COM 后乘回。

---

## 7. `_value()` 无参调用带参方法

通用包装 `_value(obj, name)` 会 `value()` 调用，遇到需要参数的 COM 方法
（如 `GetUserPreferenceInteger(47, 0)`）就报「非选择性的参数」。

**解法**：有参方法直接显式调用，别过通用包装。

---

## 8. `except: continue` 会把"取不到"伪装成"没有"

`_view_list()` 早期版本用 `md.GetViews`，拿到的是原生 `PyIDispatch`，
属性访问抛异常后被 `except: continue` 吞掉 → 统计函数**永远返回 0 个视图**，
而调用方看起来"正常"。

**解法**：改用 `GetFirstView()` 链表；且凡是 `except` 后继续的地方，
都要留下可见的失败信号。

---

## 9. 工程图模板决定单位与图框

`E:\...\data\templates\GB.drwdot` 是**英文模板**：英制、无 GB 图纸格式。
`C:\ProgramData\...\templates\gb_a3.drwdot` 才是中文的：毫米、`a3 - gb.slddrt`。

用错模板的表现：100 mm 显示成 `3.94`（英寸），且整张图没有边框和标题栏。

---

## 10. `InsertModelAnnotations4` 不给总尺寸

它插的是**模型驱动尺寸**，一个「底板 + 4 板拼管」的零件只有十来个，
而且会**跨视图去重**（所以俯视图经常 0 个尺寸是正常的）。
实测上限 18 个，且常常只有竖向。

总尺寸要自己补：取 `IView.GetVisibleEntities2(null, swViewEntityType_Vertex=2)`，
按模型坐标找极值顶点，选中后 `AddHorizontalDimension2` / `AddVerticalDimension2`。