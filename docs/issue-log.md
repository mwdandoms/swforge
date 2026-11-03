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

## 未修复 / 已记录

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
