# PartBuilder API 速查

## 构造

```python
from swforge import PartBuilder
b = PartBuilder(out_path, material="Q235")   # material 可省，默认 Q235
```

材质务必显式给国标牌号，见 `materials.md`。

## 基本体

```python
b.box(tag, x0, x1, y0, y1, z0, z1)      # 矩形板/方块
```
坐标全部是 **mm**，`(x0,x1)` 是 X 跨度，不是"起点+长度"。

## 孔

```python
b.hole(tag, target, *, axis="y", x=0, y=0, z=0,
       diameter=10, depth=None, through_all=False, direction=1,
       counterbore_diameter=None, counterbore_depth=None)
```

| 参数 | 说明 |
|---|---|
| `target` | 目标实体 tag |
| `axis` | 孔轴方向 `x` / `y` / `z` |
| `x,y,z` | 孔口所在点 |
| `through_all` | 完全贯穿（与 `depth` 二选一） |
| `direction` | +1 / -1，**朝料里切**（见 pitfalls ⑦） |
| `counterbore_diameter/depth` | 平底沉孔 |

## 切除与阵列

```python
b.cut_box(tag, target, x0, x1, y0, y1, z0, z1, axis="y")   # 矩形切除
b.hole_grid(tag, target, *, rows=1, columns=1,
            pitch_u=20, pitch_v=20, **hole)                 # 孔网格
```

## 其他特征

```python
b.revolve(...)      # 旋转体
b.fillet(...)       # 圆角
b.chamfer(...)      # 倒角
```

## 构建与读回

```python
r = b.build(paint=False, keep_open=False)
assert r.ok, r.error
print(r.bodies, r.volume_mm3, r.mass_kg)
```

`build()` 之后**必须**核对：

- `r.ok` 是否为 True
- `r.bodies` 数量对不对
- `r.volume_mm3` 与手算值差多少（应该 < 1 mm³）

## 多实体

`box()` 不重叠时自动成为独立实体。
空心件用「外壳 box + 内腔 cut_box」两步：

```python
b.box("管外", x0, x1, y0, y1, z0, z1)
b.cut_box("内腔", "管外",
          x0=x0+w, x1=x1-w, y0=y0-1, y1=y1+1, z0=z0+w, z1=z1-w,
          axis="y")        # 长度方向那根轴要给穿，两端各多 1mm 保证切透
```

## 常见错误

| 报错 | 原因 |
|---|---|
| `原生切除返回空值；孔口/方向或切除范围未与目标相交` | `direction` 反了，或孔口不在料上 |
| `SW 文档数量达到上限` | 没清场，见 pitfalls ③ |
| `RPC_E_SERVERFAULT (0x80010105)` | `sw.Visible` 没设 True，见 pitfalls ② |
| `RPC_E_DISCONNECTED (0x80010108)` | 实例崩了，需彻底重启，见 pitfalls ④ |
