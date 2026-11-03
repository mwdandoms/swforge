**中文** | [English](CHANGELOG.en.md)

# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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