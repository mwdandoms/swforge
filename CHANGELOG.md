**中文** | [English](CHANGELOG.en.md)

# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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