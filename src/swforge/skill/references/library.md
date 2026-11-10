# GB 型材素材库优先

## 为什么

本机装了 **1306 个 GB 型材焊件轮廓**（`F:\sw基础材料库`，25 个分类）：

| 分类 | 数量 | 分类 | 数量 |
|---|---|---|---|
| 矩型管 | 219 | 方管 | 124 |
| 圆管 | 171 | 冷弯空心方管 | 121 |
| 不等边角钢 | 84 | 热轧H型钢 | 84 |
| 等边角钢 | 82 | 扁钢 | 60 |

**有同型号就用库里的，不要从零画。**

从零画的后果：四块板拼成方管、没有内圆角、壁厚不准，
出来的是"看起来像方管"的东西，不是真型材。用素材库出来的是
SolidWorks 原生结构构件（Structural Member）+ 原生切割清单。

## 怎么用

```python
from swforge import MaterialLibrary

lib = MaterialLibrary()
hit = lib.resolve_section(shape="shs", a=150, b=150, t=6.3)
# hit = {"ok": True, "path": "F:\sw基础材料库\GB型材库\方管\150 x 150 x 6.3.SLDLFP",
#        "profile": {...}, "advice": "素材库有同型号，直接用，不要从零建模"}

if hit["ok"]:
    ...  # 把 hit["path"] 交给结构构件
else:
    print(hit["advice"])       # 库里没有，会给出最接近的候选
```

`shape` 取值：

```
shs        方管 / 方通 / 冷弯空心方管
rhs        矩型管
chs        圆管
angle-eq   等边角钢
angle-neq  不等边角钢
hbeam      H型钢 / 热轧H型钢
ibeam      工字钢
channel    槽钢
round-bar  圆钢
square-bar 方钢
flat-bar   扁钢
alu        铝型材
```

## 建框架时自动查库

```python
from swforge import create_weldment_frame

r = create_weldment_frame(out, section=50, wall=2, length=600, width=400, height=500)
print(r["profile_resolution"]["source"])   # "library" 或 "generated"
```

`use_library=True` 是默认值：先查库，有同型号就用库里的原生型材截面，
没有才回退到现场生成矩形环。也可以直接指定：

```python
create_weldment_frame(out, profile_path=r"...\150 x 150 x 6.3.SLDLFP")
```

## 命令行

```bash
swforge lib-scan                      # 列出所有分类和数量
swforge lib-find --shape shs --a 150 --b 150 --t 6.3   # 查具体型号
swforge lib-find --keyword 150        # 按文件名模糊查
```

## 库模式与现场生成的区别

同一组参数 `50×50×2`：

```
素材库轮廓   体积 1,952,162.8 mm³   质量 15.324 kg
现场生成     体积 1,996,800.0 mm³   质量 15.6749 kg
差异 -2.24%
```

这个差异是**正常的**——真冷弯方管有内圆角，比理想尖角矩形环少 2% 的料。
库模式下体积核对容差放宽到 6% 并把实际比值记在
`geometry_verification.section_area_ratio` 里。

## 坑

- 命名不统一：`100 x 100 x 10.0` / `100×4` / `102x1.5` / `HM150×100`，
  不要自己拼字符串匹配，用 `lib.find()` 走语义参数。
- 壁厚不一定有你要的：150×100 矩型管只有 3.2/4.0/5.0/6.3/8.0/10.0。
- 找不到时 `advice` 会给出最接近的候选，**必须让用户确认**再替代。
- 素材库是 `.SLDLFP` 焊件轮廓，不是零件；不能直接当 .sldprt 打开。

## 单根型材（最常用）

用户说「建一根 150×150×6.3 方管，长 3 米」时，**用这个，不要用 PartBuilder**：

```python
from swforge import create_standard_member
r = create_standard_member(out, shape="shs", a=150, b=150, t=6.3, length=3000)
```

它会自动查库并三种结果：

| source | 含义 | 处理 |
|---|---|---|
| `library` | 用素材库真型材建模 | 正常 |
| `generated_fallback` | 库里有但轮廓不可用，已回退 | 告知用户 |
| `generated` | 库里没有，现场建 | 看 advice 候选 |

命令行：`swforge member out.sldprt --shape shs --a 150 --b 150 --t 6.3 --length 3000`
