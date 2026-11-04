**中文** | [English](CHANGELOG.en.md)

# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.3.1] - 2026-11-04

### 修复

- **`status` 在刚发完版时报假警报**。PyPI 首页的 `/pypi/<pkg>/json`
  有几分钟 CDN 缓存，1.3.0 明明已经可以 `pip install`，
  `status` 却报「PyPI 最新 1.2.1，本地 1.3.0（可能缓存延迟，也可能没发）」。

  **误报比不报更糟**——人会开始忽略所有提醒。

  现在首页版本落后时，会再查一次 `/pypi/<pkg>/<version>/json`
  确认目标版本是否真的在。在就降级成一条说明，不在才进「需要你操作」。

## [1.3.0] - 2026-11-04

### 新增

- **`swforge status`** —— 一条命令回答「现在有什么在等我」。

  起因是一次真实事故：v0.9.1 的一个发布 run 卡在「等待批准」，
  从下午一直挂到第二天早上。这期间仓库看起来正常、PyPI 上版本也在，
  **没有任何地方提示有东西在等人**。

  输出固定三段：

      代码        分支 / HEAD / 未提交 / 未推送 / 版本 / 标签 / PyPI
      流水线      GitHub 仓库 / 等待批准 / 最近失败 / 最近 4 次 run
      需要你操作  有就逐条列出「是什么」+「怎么做」；没有就明确写「无」

  最后一段是重点。**没有东西要你做时它会明说「无」**——
  含糊不清正是「干等但不知情」的根源。

  顺带把「改了源码没发版」也并进来（v1.1.0 那次漏发）。

  没有 GitHub token 时自动降级成只查本地和 PyPI，不报错。

## [1.2.1] - 2026-11-04

`read_volume()` 忘了从包顶层导出。

1.2.0 里它能用，但要写 `from swforge.assembly import read_volume`；
`add_section_view()` / `add_detail_view()` 都是从顶层导出的，
它没有。这种不一致会让人以为功能不存在——查文档发现"有这个函数"，
`import swforge; swforge.read_volume` 却报 AttributeError。

现在统一了，`swforge.read_volume()` 可用。

## [1.2.0] - 2026-11-04

四项待办：发版检查、BOM 表定位、剖视图/局部放大、多客户端并发实测。

### 新增

- **`swforge release-check`** —— 发版一致性检查。
  回答「本地 / 标签 / PyPI 三者对得上吗」。
  核心是抓「改了源码但没发版」：v1.1.0 就栽在这上面，
  标签打完之后又改了 `drawing.py` 和 `cli.py`，PyPI 上的包缺两个
  用户可见的修复，README 说能用，装上其实是坏的。
  现在一条命令就能发现。

  语义上区分两种情况：源码改了 + 版本号没动 = **错误**（漏发）；
  源码改了 + 版本号已升 = **提醒**（正常准备发版中）。
  判错会让每次开发中途都报红，工具就没人看了。

- **`add_section_view()` / `swforge section-view`** —— 剖视图。
- **`add_detail_view()` / `swforge detail-view`** —— 局部放大视图。
- **`read_volume()`** —— 读文档几何体积（mm³），零件和装配都能用。

### 修复

- **BOM 表插进去看不到**。两个原因都不是库的 bug，但都会让人以为功能坏了：
  1. 插入后没有重新缩放，视图还停在模型上，表在视野之外。
     现在 `insert_bom_table()` 插完会自动 `ViewZoomtofit2()`。
  2. 装配图模板 `gb_assembly.drwdot` 不存在时会回退到 `gb_a0.drwdot`，
     A0 图纸太大，表缩放后小到看不见。文档里已写明要用 A3 模板。

- **BOM 里写的是组件实例名**。合并计数后显示成「垫片-3 ×3」，
  车间要的是「垫片 ×3」。改用零件文件名。

### 实测记录

- **多客户端并发**：两个独立进程同时操作同一个 SolidWorks。
  A 打开自己的文档后 B 把活动文档切走，A 的 `activate_verified()`
  能检测到并抢回；读回的体积是 24000.0 mm³，证明读到的是自己的文档。
  两个进程各跑 5 项检查，全部通过。

- **剖视图 / 局部放大**：3 个视图 → 6 个，
  生成 `剖面视图 A-A`、`剖面视图 B-B`、`局部视图 I`。

### 踩过的坑（写进代码注释了）

- `CreateSectionViewAt4/5` 在**新视图位置和源视图重叠**时静默返回 `None`。
  必须给 Y 偏移。
- 画完剖切线 / 放大圆圈后**不能** `ClearSelection2()`。
  辅助几何要保持选中，API 靠它知道剖在哪。
  清掉选择后返回 `None`，一个错都不报。
- `Extension.CreateMassProperty()` 在 pywin32 后期绑定下报「找不到成员」，
  只有 C# 早期绑定能用。Python 里必须走 `IBody2.GetMassProperties(1.0)`。

## [1.1.1] - 2026-11-04

补上 v1.1.0 漏发的两个修复。v1.1.0 发布之后又改了源码，但 PyPI 上的包没跟着更新。

### 修复

- **出图后没有缩放到适合**。`produce()` 生成工程图后不调用 `ViewZoomtofit2()`，
  A3 幅面在窗口里只显示部分内容——录屏和截图时第一眼看到的是半个图框。
  现在创建视图后调用一次，`add_dimensions()` 标注后再调用一次
  （标注会改变视图范围）。

- **`--json` 路径崩溃**。`swforge selftest --json` 和 `swforge bom --json`
  都把返回 bool 的 `_json_ascii()` 当打印函数用了，
  报 `TypeError: _json_ascii() takes 0 positional arguments but 1 was given`。
  这条路径此前没被实测过，做演示动图时抓 JSON 数据才暴露。

### 备注

这两个都是**用户能直接看到**的缺陷，不是内部重构。
1.1.0 因为是在这两处改动之前发的标签，所以包里不包含它们。

## [1.1.0] - 2026-11-04

这一版的主题是**把"我做了"变成"可以自己验证"**。

### 新增

- **`swforge selftest` 实机自检**（10 项）。
  每一项都在真实 SolidWorks 上跑，读回结果再判定；失败时指出是哪一环、
  对应同类项目的哪个已知问题。退出码可直接接进 CI。
  `--only` 只跑单项，`--json` 输出机器可读结果。

- **BOM 明细表** `swforge bom`。
  从装配读组件清单，同零件合并计数，材料直接问 `IComponent2` 而不逐个打开零件
  （SolidWorks 只有 8 个文档名额，逐个开很快就用完）。
  可导出 CSV（带 UTF-8 BOM，Excel 打开中文不乱码）。

- **活动文档守卫** `swforge.guard`。
  解决多个客户端共用一个 SolidWorks 时互相抢文档的问题。
  不做跨进程锁（COM 场景下不可靠且会死锁），改成每次操作前后核对活动文档，
  被抢走就重新激活。代价约 1 ms。

- **生成源码快照测试**（11 条）替代完整 Mock。
  完整 Mock 会把 SolidWorks 的行为模拟成"正常"，而本项目所有严重 bug
  都是真机跑出来的，Mock 一个都发现不了。改成守住"生成的 C# 有没有被改坏"，
  成本约 1/5，能拦住单位换算被改、API 名拼错、必要调用被删。

- **文档站** https://mwdandoms.github.io/swforge/
- **问题日志** `docs/issue-log.md`：公开记录真实问题，含已修和未修。
- **路线图** `docs/roadmap.md`：下一阶段方向和**退出条件**。

### 修复

- **干涉检查的明细列表一直是空的**。
  `GetInterferences` 在后期绑定下是**属性不是方法**，调用抛的 `TypeError`
  被 `except` 吞掉变成 `None`，结果是"计数 1、明细空"——
  调用方知道有干涉，但不知道是哪两个零件。
  现在返回 `{"volume_mm3": 4000.0, "components": ["a-1", "b-1"]}`，
  与理论值 10×20×20 偏差 0.00%。

- **尺寸过度标注，而且非主视图的值是错的**。
  两件事：
  一是自动标注无条件插 22 个尺寸并堆在一侧重叠（实测任何类型组合都是 22 个，
  不是类型选错）；改成受控标注后降到 9 个。
  二是用模型坐标 X/Y 找极值只对主视图成立，右视图的屏幕水平方向是模型 Z，
  标出来是 114 而实际是 120；改为按 `GetOrientationName()` 选轴。

- **`swforge --help` 在非中文 Windows 上崩溃**（CI 发现的真实用户问题）。

- **自检工具自己把文档名额占满**，导致后 4 项连环失败。
  每项检查现在会关掉自己建的文档。

### 验证结果

- **实机自检 10/10 通过**，60.2 秒（SolidWorks 2025 SP5.0）
- **全量测试 180 项通过**（148 离线 + 32 实机），178.8 秒
- BOM 数据提取实机验证：底板 ×1 + 垫片 ×3 → 2 种 4 件，材料 Q235 全部读到
- 并发守卫实机验证：被切到另一文档后正确检测并抢回

### 已知未完成

- **BOM 表插入的位置不可控**：表格能建出来（3 行 3 列），
  但 `TableAnnotation` 在 pywin32 后期绑定下 `GetPosition`/`SetPosition`
  都取不到，位置既读不了也改不了，导出 PDF 后表格不在页面上。
  需要走 C# 早期绑定才能解决。
  **`swforge bom` 命令（读明细 + CSV）不受影响，可正常使用。**
- 公差、粗糙度、形位公差仍然不生成，需人工补。

## [0.9.1] - 2026-11-03

首个发布到 PyPI 的版本。相比 v0.9.0 全是修复，没有新功能。

### 新增
- **PyPI 发布流程** `.github/workflows/publish.yml`：打标签即发布，
  用 Trusted Publishing（OIDC），仓库里不存任何 token。
  发布前做三项校验：wheel 数量、包版本与标签一致、sdist 含 docs/。
- **MCP 服务器对外可用性**：补 17 行 `instructions`（Agent 读到的第一段话），
  修正 `serverInfo.version` 报成 SDK 版本的问题，README 补多客户端配置。
- `tests/test_mcp.py` 6 条契约测试，走真实 stdio 协议。

### 修复
- `swforge --help` 在非中文 Windows 上崩溃：stdout 编码为 cp1252 时
  打印中文抛 `UnicodeEncodeError`。现在用 `errors='replace'` 兜底，
  且 JSON 输出在单字节编码下自动转义成 `\uXXXX`，保证机器可读。
- `produce()` 在全新出图时也白连一次 SolidWorks（v0.9.0 引入的回归），
  导致纯逻辑单测被拖进真实连接。改成只有旧文件存在时才连。
- CI：`package build` 因 PowerShell 不展开 `dist/*.whl` 通配符而失败；
  改成 bash 并统一用 `python -m swforge.cli`。
- CI：marker 检查从静态文本扫描改为 conftest 运行时守卫。
  静态版误报了 4 个「只测参数校验」的合法用例。

## [0.9.0] - 2026-11-03

### 新增
- **批量出图** `swforge batch`：一个文件夹的零件 → 一批带 GB 图框的工程图。
  实测 5 件 15.7 秒；单件失败不影响整批；默认跳过已存在的图，断了能续跑。
- **API 能力探测** `swforge capabilities --api`：用反射查本机 Interop 库，
  逐个确认 28 个风险 API 存在性与最高重载参数个数，实测 0.43 秒给出明确结论。
  类型写错会自动全局扫描纠正（`InsertModelAnnotations4` 实际在 `IDrawingDoc` 上）。
- **总尺寸支持回转体**：没有可见顶点时退回「边端点」→ 再退回「单实体标注」，
  圆柱/圆环现在能拿到外径和内径（实测法兰 120/60、轴套 40/24）。
- **CI**：`.github/workflows/tests.yml`，Python 3.10~3.13 矩阵跑 106 项离线测试，
  外加打包构建、sdist 内容检查、`sw` marker 守卫。
- 测试 124 → **138 项**（106 离线 + 32 实机）。

### 修复
- `produce()` 在目标图已存在时返回 `err=1`：上一张图还开着锁住文件。
  现在出图前先关掉指向同一路径的已打开文档。
- `add_dimensions(overall=True)` 引用未定义的 `overall_result`（NameError）。
- sdist 不含 `docs/` 和 `demo/`：加 `MANIFEST.in`，现在 65 个文件。
- 批量出图第 5 件撞 SolidWorks 8 文档上限后整批失败：每件结束显式释放文档。

### 文档
- README 增加「尚未做到」小节和「验证边界」三层表（L1 离线 / L2 CI / L3 实机）
- 中英文 README 同步更新

## [0.8.0] - 2026-11-03

### 新增
- **总尺寸标注** `dims.py`：按视图可见顶点极值显式生成总长/总高
  （`InsertModelAnnotations4` 拿不到总尺寸，且会跨视图去重）
- **配合** `mates.py`：同心 / 重合，自动选面（等径圆柱、平行平面），C# 早期绑定实现
- **精确干涉** `interference.py`：实体布尔求交，实测 500.000 mm³
- 测试 111 → **124 项**

### 修复
- 干涉求交返回错误码 1：`swBodyOperationNonApiBody` —— 文档体不是 API 临时体，
  需先 `Copy2(False)`
- 配合判据：`swAddMateError_NoError = 1`（不是 0）
- 装配坐标单位：`AddComponent5` 内部要米，此前把毫米当米传，零件被放到 60 米外
- 工程图模板选型：改为按年份扫描 + 中文 `gb_<纸张>.drwdot` 优先
- `_ensure_mm_units` 读不到单位值（`_value()` 无参调用带参方法）

## [0.7.0] - 2026-11-03

### 新增
- GB 图框与标题栏（自动带材料 / 重量 / 比例）
- 毫米单位校验

### 变更
- `_default_template()` 优先中文 GB 模板（此前优先英文模板导致英寸 + 无图框）
- `add_dimensions(..., relayout=True)`：标注后自动重排

### 已知问题
- 干涉求交返回 `(None, 1)`，未解决
- 配合未实现

## [0.6.0] - 2026-11-02

### 新增
- `revolve()` 支持 x/y/z 三轴（三轴体积误差 0.00%）
- 自动标注 `add_dimensions()` / `count_dimensions()`
- 装配 `AssemblyBuilder`（插入 + 固定）

### 修复
- `_view_list()` 用 `GetViews` 拿原生 PyIDispatch 被 `except: continue` 静默吞掉，
  导致统计永远返回 0 视图

### 发现
- `AddComponent5` 要求零件**先打开**，否则静默返回 None

## [0.5.0] - 2026-11-02

### 新增
- 连接两级 fallback（`GetActiveObject` → `CreateInstance`）+ 可操作错误提示
- GB 材质库 `gb_materials.py`：20 个牌号 + 自动部署到 SW 扫描目录
- 诚实性回归测试（4 项）

### 修复
- **物理材料从未赋给 SW**，默认密度 1000 kg/m³（水），质量错 7.85 倍

## [0.4.1] - 2026-11-02

### 新增
- 资源守卫三档分级（ok / warn / critical）+ 安全清扫 `sweep_documents()`

### 修复
- `conftest.py` 清理根目录漏了 pytest 临时目录，导致实测套件跑到第 8 个文档自锁
- `max_documents=0` 被判为参数非法

## [0.4.0] - 2026-11-01

### 新增
- 文档数量上限与批处理自动释放
- 直边选边规则 `edges_rule` + 只读预览 `preview_edges`
- PDF 内容验证（PDFium 解析 + 渲染）

## [0.3.0] - 2026-11-01

### 新增
- 三轴圆柱、绕 Y 轴旋转、全边圆角与倒角
- 单 STA 线程串行化（MCP 并发安全）

### 修复
- 世界坐标不再镜像 Z；`merge` 真正生效；实体数改为从 SW 回读

## [0.2.0] - 2026-11-01

### 新增
- 配色覆盖率 57% → **100%**（面级写入 + 回读）
- 视图排版求解器（实测尺寸 + 长对正 / 高平齐 / 自动缩放）
- MCP 服务器（15 工具）
- 集成测试 5 项

### 修复
- `swAllBodies = -1`（原误写成 2），`purge_*` 一直遍历 0 个实体

## [0.1.0] - 2026-11-01

首个可用版本：DSL → C# 建模、分色、导入清理、PDF 图集、CLI。