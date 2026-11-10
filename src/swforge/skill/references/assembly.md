# 装配、配合与干涉

## 一、定位只能靠配合

**禁止**硬设坐标：

```
❌ SetXform / SetXformAndSolve / SetTransform / TranslateComponent
✅ 配合（Mate）
```

## 二、配合类型

```python
from swforge import ...   # 见 swforge 导出
```

| 类型 | 值 |
|---|---|
| 重合 coincident | 0 |
| 同心 concentric | 1 |
| 垂直 perpendicular | 2 |
| 平行 parallel | 3 |
| 距离 distance | 5 |
| 角度 angle | 6 |
| 锁定 lock | 16 |

```python
create_mate("distance", (face_a, face_b), distance_mm=10)
create_mate("coincident", (face_a, face_b))
create_lock_mate(comp)
```

## 三、选面要点（容易踩）

- 面必须用 `mod.IFace2(face._oleobj_)` **重包**一次
- `face.Select2(True, 1)` 传**两个**参数
- `EntitiesToMate` 要包成 `VARIANT(VT_ARRAY|VT_DISPATCH, (e1, e2))`
- `AddMate5` 必须 **15 个参数**

## 四、判据不是 errStatus

```
errStatus ≠ 0 不代表创建失败
真正判据 = CreateMate 返回非 None 且 特征数递增
```

验证：

```python
n0 = md.GetFeatureCount(False)
feat = md.FeatureManager.CreateMate(...)
n1 = md.GetFeatureCount(False)
ok = feat is not None and n1 > n0
```

## 五、干涉检查

```python
interf = md.GetInterferences      # 后期绑定下是属性
```

返回干涉对象数组，每个可读：

```python
interf.GetInterferenceVolume()    # mm³
```

**判据**：干涉体积必须为 0。非 0 就停下，不要"看着差不多"放过。

## 六、实测基线（可用来验证环境）

| 项目 | 期望值 |
|---|---|
| 两块 100×100×10 板重叠 2mm | 干涉 2000 mm³ |
| 销 Ø20 插 Ø20 孔 | 干涉 ≈ 0 |
| 配合前 X=[60,0] → 配合后 | X=[0,0] |
