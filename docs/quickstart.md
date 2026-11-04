# 快速开始

## 1. 装

```powershell
pip install "swforge[mcp,pdf]"
```

可选依赖：

| 附加项 | 装什么 |
|---|---|
| `[mcp]` | MCP 服务器（30 个工具），给 Claude / Cursor 这类智能体用 |
| `[pdf]` | PDF 导出与渲染验证 |
| `[dev]` | 开发用（pytest 等） |

国内网络慢的话用镜像：

```powershell
pip install "swforge[mcp,pdf]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

> 镜像同步有延迟，刚发版那几小时可能还没有。装不到就换官方源。

---

## 2. 先启动 SolidWorks

**这一步必须手动做。** 工具不会替你启动它——因为启动一个 CAD 是用户的决定，
工具擅自拉起一个几百 MB 的进程不合适。

启动后确认主窗口是可见的、没有卡在启动画面。

---

## 3. 自检

```powershell
swforge selftest
```

这一步会花大约 1 分钟，在真实 SolidWorks 上建零件、出图、装装配。

**九项全 PASS 才说明这台机器上功能完整。** 有 FAIL 就把输出贴出来——
每一项失败都对应一个具体的能力缺口，不是笼统的「跑不起来」。

只跑某一项：

```powershell
swforge selftest --only interference
```

---

## 4. 建第一个零件

```python
from swforge import PartBuilder

b = PartBuilder("测试.SLDPRT", material="Q235")
b.box("底板", 0, 160, 0, 20, 0, 100)
b.cylinder("孔", axis="y", x=80, y=20, z=50, r=8, h=20)
r = b.build()

print(f"成功 {r.ok}  实体 {r.bodies}  质量 {r.mass_kg:.3f} kg  体积 {r.volume_mm3:.0f} mm³")
```

**尺寸单位一律 mm。**

`build()` 返回值里最重要的三项：

| 字段 | 含义 |
|---|---|
| `ok` | 是否成功（不只是「没抛异常」） |
| `bodies` | 从 SolidWorks **回读**到的实体数 |
| `mass_kg` / `volume_mm3` | 从 SolidWorks **回读**的质量和体积 |

---

## 5. 出工程图

```python
from swforge import produce, add_dimensions

r = produce("测试.SLDPRT", "测试.SLDDRW", paper="A3")
# {'ok': True, 'views': 3, 'page': 'A3'}

d = add_dimensions("测试.SLDDRW", curated=True, internal=1)
# {'mode': 'curated', 'after': 9, ...}
```

`curated=True`（默认）只标总尺寸和几个最大跨度的内部特征尺寸，并跨视图去重。

想要旧的全量标注（会重叠）：

```python
add_dimensions("测试.SLDDRW", curated=False)
```

---

## 6. 装配与干涉

```python
from swforge import AssemblyBuilder, MateBuilder, check_interference

ab = AssemblyBuilder("总装.SLDASM")
ab.add("底板.SLDPRT", x=0, y=0, z=0, fixed=True)
ab.add("立柱.SLDPRT", x=60, y=0, z=0)
ab.build()

# 同心配合：把第二个零件拉到第一个的轴线上
before = MateBuilder("总装.SLDASM").apply()
res = MateBuilder("总装.SLDASM").concentric(0, 1).apply()
print("配合前", before["component_boxes_center_mm"])
print("配合后", res["component_boxes_center_mm"])

# 干涉检查
print(check_interference("总装.SLDASM"))
# {'ok': True, 'interference_count': 1,
#  'interferences': [{'volume_mm3': 4000.0, 'components': ['a-1', 'b-1']}]}
```

> 干涉体积是本项目最有说服力的能力之一：给出的不只是「有干涉」，
> 而是**精确体积和涉及哪两个零件**。

---

## 7. 接智能体（可选）

MCP 配置见 README 的 MCP 一节。最短形式：

```json
{
  "mcpServers": {
    "swforge": {
      "command": "python",
      "args": ["-m", "swforge.server"]
    }
  }
}
```

服务器会在握手时返回 17 行使用说明，Agent 不需要你额外教它。

---

## 常见问题

### 连不上 SolidWorks

```powershell
swforge ping
```

看报错：

| 报错 | 原因 | 怎么办 |
|---|---|---|
| `MK_E_UNAVAILABLE` | SolidWorks 没启动，或启动了但没注册 | 手动启动 SW，等主窗口出现 |
| 连接成功但操作失败 | 同时有多个 SolidWorks 实例 | 关掉多余的，只留一个 |

**多个实例是最常见的坑**：`Dispatch` 找不到已注册实例时会自己新开一个，
于是有了两个，互相抢连接。用任务管理器确认只有一个 `SLDWORKS.EXE`。

### 中文乱码

控制台编码问题，设一下环境变量：

```powershell
$env:PYTHONIOENCODING = "utf-8"
chcp 65001
```

### 文档名额不足

SolidWorks 默认只允许同时打开 8 个文档。

```powershell
swforge resources          # 看当前几个
swforge resources --sweep  # 清理临时文档
```
