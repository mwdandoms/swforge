# BOM 明细表

## 一句话

从装配体读组件清单，**同一零件合并计数**，材料直接从组件读，不用逐个打开零件。

---

## 命令

```powershell
swforge bom                      # 当前打开的装配
swforge bom 总装.SLDASM           # 指定文件
swforge bom 总装.SLDASM --csv bom.csv
```

输出：

```
  装配：G:\proj\总装.SLDASM
  种类 3 项，共计 5 件

| 序号 | 名称 | 数量 | 材料 |
|---:|---|---:|---|
| 1 | 底板 | 1 | Q235 |
| 2 | 立柱 | 2 | Q235 |
| 3 | 垫片 | 2 | 未指定 |

  ⚠ 这些零件没有材料：垫片
    材料缺失时 SolidWorks 默认密度是 1000 kg/m³（水），质量会错约 7.85 倍。
    missing_material 非空就该先补材料。
```

---

## 代码调用

```python
from swforge import collect_bom, bom_to_csv

r = collect_bom("总装.SLDASM")
print(r["distinct_parts"], r["total_items"])   # 3 5
for row in r["rows"]:
    print(row["seq"], row["name"], row["qty"], row["material"])

bom_to_csv(r["rows"], "bom.csv")
```

返回结构：

| 字段 | 含义 |
|---|---|
| `ok` | 是否成功 |
| `rows` | 明细行，每行 `{seq, name, qty, material, path}` |
| `distinct_parts` | 零件种类数 |
| `total_items` | 总件数（各数量之和） |
| `missing_material` | 没有材料的零件名列表 |

---

## 三条必须知道的规则

### 1. 同一零件合并计数

装 3 个同样的垫片 → **一行「垫片 ×3」**，不是三行。

路径比较时**忽略大小写**（Windows 路径大小写不敏感）。
否则 `C:\Parts\Plate.SLDPRT` 和 `c:\parts\plate.SLDPRT` 会被当成两个零件，
BOM 直接翻倍。

### 2. 压缩件默认不算，但可以要求算

被压缩的组件图上看不到，列进 BOM 会误导。默认排除。

做「全零件清单」而不是「图上清单」时：

```python
r = collect_bom("总装.SLDASM", include_suppressed=True)
```

### 3. 「从明细表排除」永远生效

SolidWorks 允许把某个组件标记成「从明细表排除」（`ExcludeFromBOM`）。
**这是用户的明确意图，无论 `include_suppressed` 怎么设都不列出来。**

---

## 材料是怎么读的

```python
IComponent2.GetMaterialUserName()   # 优先，返回 Q235 这类用户可见名
IComponent2.GetMaterialIdName()     # 退回，返回内部 ID
```

**为什么不逐个打开零件去读？**

SolidWorks 默认只允许同时打开 **8 个文档**。一个 20 个零件的装配，
逐个打开读材料会立刻撞上限，而且每个零件开关一次要几百毫秒。

组件对应的零件在装配打开时就已经加载了，直接问组件即可 ——
**零额外开销**。

---

## 没有材料为什么重要

SolidWorks 的默认密度是 **1000 kg/m³，也就是水的密度**。

没赋材质时它**不会报错**，只会让质量算错约 **7.85 倍**（钢是 7850）。

所以 BOM 里材料缺失不是「留个空格」这么简单：

```python
if r["missing_material"]:
    print("先补材料再出图")
```

`group_components` 会把缺失材料写成 **「未指定」** 而不是空字符串 ——
空单元格读起来像「材料就是空的」，而实际后果是质量错了 7.85 倍。

---

## CSV 导出

```python
bom_to_csv(rows, "bom.csv")
```

**带 UTF-8 BOM**。不带的话 Excel 打开中文表头是乱码 ——
这是国内用户最先撞上的问题，不是可选项。

列：`序号, 名称, 数量, 材料, 路径`

---

## 把 BOM 表插进工程图

```python
from swforge import insert_bom_table

r = insert_bom_table("总装.SLDDRW", x=0.2, y=0.05, anchor="bottom-left")
print(r)
# {'ok': True, 'rows': 3, 'columns': 5, 'anchor': 'bottom-left'}
```

用 `IView.InsertBomTable6`（参数最多的版本，能控制编号方式和是否展开子装配）。

`anchor` 可选：`bottom-left` / `top-left` / `top-right` / `bottom-right`。

> ⚠️ **这一项只完成了一半。**
>
> 实机验证结果：表格**能建出来**（返回 `rows=3, columns=3`，
> 图纸上确实有 1 个表格注解），但**位置不可控** ——
> 导出 PDF 后表格不在页面上。
>
> 原因是 `TableAnnotation` 在 pywin32 后期绑定下 `GetPosition` / `SetPosition`
> 都取不到，位置既读不了也改不了。需要走 C# 早期绑定才能解决。
>
> **数据提取（`swforge bom` 命令、CSV 导出）不受此影响，可以正常使用。**

---

## 限制

| 限制 | 说明 |
|---|---|
| **插表位置不可控** | 表格能建出来但落在图框外，待用 C# 早期绑定解决 |
| 不含重量列 | 需要逐个组件算质量，会显著变慢；后续按需加 |
| 不含标准件标记 | 国标件库还没做 |
| 不处理子装配展开 | 目前只列顶层（`swBOMType_TopLevel`） |
| 材料名依赖 SolidWorks 返回 | 若返回内部 ID 而非 `Q235`，需要映射表 |
