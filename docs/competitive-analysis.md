# 竞品分析：谁和 swforge 定位最像

> 调查时间：2026-11-03
> 数据来源：GitHub API 实取（star / fork / README 全文 / topics / 发布记录）
> 方法：抓下 7 个定位相近项目的 README 逐段阅读，按「主张 → 架构 → 能力 → 工程化」四层对比

---

## 一、先给结论

**没有一个项目和 swforge 定位完全相同**，但有三类"像"：

| 像在哪 | 项目 | 关键相似点 |
|---|---|---|
| **战略最像** | `wzyn20051216/solidworks-automation-skill` ★1699 | 核心主张几乎一模一样：**"Tool success is not task success"** |
| **技术最深** | `eyfel/mcp-server-solidworks`（SolidPilot）★457 | 同样强调"结果要验证"，但用了完全不同的抽象层 |
| **工程化最好** | `andrewbartels1/SolidworksMCP-python` ★91 | 一行安装、mock 模式、文档站 |
| **名字最像**（但内容不像） | `muerus/SolidWorks-Python`（SwPy）★9 | 都叫"Python for SolidWorks"，一个是脚本教程，一个是工具包 |

**最值得警惕的是 `wzyn20051216`** —— 它在这个方向上是当前的天花板，
而且它把 swforge 的核心理念当成了自己的第一句话。

---

## 二、四个主要对手的详细对比

### 2.1 `wzyn20051216/solidworks-automation-skill` ★1699 ★★★★★

**它的一句话**：
> Tool success is not treated as task success.
> 工具调用成功，不代表任务真的完成。

**这和 swforge 的「假成功」是同一个洞察。** 但它的落地方式比 swforge 重得多：

| 维度 | 它的做法 |
|---|---|
| 入口 | **三个平级入口**：Skill（给 Claude/Cursor）/ MCP / CAD Studio 桌面版 |
| 架构 | Execution Core（Capability · Verification · Recovery · Trace）→ **Backend Router**（Python COM / C# / OCCT）→ CAD |
| 后端容错 | 后端失败有 **Recovery Decision**，能力缺失有 **Capability Gap** 交还 Agent 查证 |
| 可观测 | **结构化 Trace**，每步可审计 |
| 评测 | **43 个 deterministic reliability scenarios**（12 nominal + 31 robustness），含故障注入 |
| 测试 | **1045 项 pytest** |
| 能力 | 69 个命名工具，但**默认只暴露 3 个检索入口**（`sw_search_tools` / `sw_describe_tool` / `sw_call_tool`） |
| 覆盖 | 建模 / 装配 / **GB/T 工程图** / 尺寸链 / 孔表 / BOM / 运动算例 / 设计审计 / 公差提取 |
| 环境 | SolidWorks **2026** |
| 运营 | GIF 动图演示、CI badge、Release 带安装包、子技能分目录 |

**最值得学的一点 —— 它的「验证边界」表**：

| 层 | 在哪跑 | 覆盖 | **不覆盖** |
|---|---|---|---|
| L1 离线回归 | 任意机器 | pytest 1045 项 + 12 workflow | 需要 SolidWorks 进程的一切 |
| L2 托管 CI | GitHub windows-2022 | L1 全部 + 构建契约 | 真实 CAD 执行 |
| L3 真实 CAD 验收 | **仅维护者本机** | Golden 五轮真机 | 其它机器、其它版本 |

并且明确写了三句硬话：

> 1. 远端不存在 CAD 真机执行证据。任何"远程 CAD CI 已通过"的表述都是错的。
> 2. 本机通过 ≠ 跨机器通过。
> 3. L2 通过 ≠ 治理闭环。

**这个表格是纯沟通产物，零代码成本，但极大提升可信度。swforge 应该直接抄。**

---

### 2.2 `eyfel/mcp-server-solidworks`（SolidPilot）★457 ★★★★★

**它的核心洞察**（比 swforge 高一个层次）：

> SolidWorks API 有几千个方法。把它们每个都当成一个"工具"暴露给 AI，
> 会让上下文爆炸、token 成本失控 —— 这是同类项目卡死的经济学原因。

**它的解法 —— 抬高抽象层**：

```
AI 表达意图（feature level，例如"在顶面打个孔"）
  ↓
CAD 无关的 Feature Graph IR
  ↓
确定性的 compiler 把 IR 降级成一串具体 SolidWorks 操作
```

一个 feature 映射到多个底层操作，**一次模型调用就够**。

**最狠的功能 —— IR 可以反向运行**：

```
drawing.dwg → analyze_drawing → (视图/边类型/轮廓链/真实尺寸/折弯注释)
            → Feature Graph IR → compiler → SolidWorks 实体
```

**给它一张供应商发来的 DXF/DWG（没有任何模型），它能把零件重建出来。**

而且它的验证方式非常硬：

> 期望体积是**在建之前从图纸自身的尺寸算出来的**，建完再回读比对。
> 已经重建了 9 张真实图纸（4 张自研 + 5 张生产制造单，A4/A3/A1，1:1 到 1:10，
> 三种标题栏模板），每张都和标题栏重量核对到 **0.02% 以内**。

**这是 swforge 完全没做的方向**：swforge 只能「模型 → 图」，它已经做到「图 → 模型」。

---

### 2.3 `andrewbartels1/SolidworksMCP-python` ★91 ★★★★

**工程化做得最好的一家。**

| 亮点 | 细节 |
|---|---|
| **一行安装** | `uvx solidworks-mcp-python setup` —— 不用 clone，uv 自己拉 Python 3.13 和包 |
| **自动发现客户端** | 检测 Claude Desktop / Claude Code / VS Code / Cursor / LM Studio，让你选 |
| **装完自检** | 起一次服务器确认工具列表能出来（**mock 模式，不碰 SolidWorks**） |
| **改配置前备份** | 先 `.bak`，只改 `solidworks` 这一项，从不碰你其它服务器 |
| **mock 模式** | 没有 SolidWorks 也能跑，CI 友好 |
| **显式"没做到"章节** | `## Not Yet / Simulated` —— 直说哪些是模拟的、不能当工程真值 |
| 文档站 | `andrewbartels1.github.io/SolidworksMCP-python` |

那句 `## Not Yet / Simulated` 第一条写的是：

> Mock adapter output is simulated and should not be treated as engineering truth.

**这种"先自己拆台"的写法在技术社区非常吃香**，因为它证明作者知道自己工具的边界。

---

### 2.4 `muerus/SolidWorks-Python`（SwPy）★9 ★★

名字和 swforge 最像，但**内容完全不是一类**：

- 它是**Jupyter notebook 风格的脚本教程**（README 里直接有 `# r: openpyxl` 这种单元格魔法）
- 教你"怎么用 Python 调 SolidWorks API"
- 有文档站，但**没有工具包、没有 MCP、没有验证机制**

**结论**：不是竞品，是**上游学习材料**。swforge 的用户很可能先看过它。

---

## 三、横向能力对照表

| 能力 | swforge | wzyn ★1699 | SolidPilot ★457 | andrew ★91 | SwPy ★9 |
|---|:---:|:---:|:---:|:---:|:---:|
| 建模（盒/管/圆柱/旋转） | ✅ | ✅ | ✅ | ✅ | 教程 |
| 圆角/倒角 | ✅ | ✅ 语义选边/可变半径 | ✅ | ✅ | — |
| 齿轮 | ❌ | ✅ pilot | — | — | — |
| 钣金/焊件 | ❌ | ✅ | ✅ 钣金展开 | — | — |
| **面级配色 + 回读** | ✅ **100%** | — | — | — | — |
| **GB 材质库（20 牌号）** | ✅ **独有** | ❌ 无材质库 | ❌ | ❌ | — |
| 装配 + 配合 | ✅ 同心/重合 | ✅ **含爆炸视图** | ✅ | ✅ | — |
| **精确干涉体积** | ✅ **500.000 mm³** | 干涉检查（未提精度） | ✅ 提及 | 提及 | — |
| GB/T 工程图 | ✅ 图框+标题栏+总尺寸 | ✅ **尺寸链/孔表/BOM** | ✅ | ✅ | — |
| 公差/粗糙度 | ❌ 故意不做 | ✅ 只读提取 | — | — | — |
| **图纸 → 模型（反向）** | ❌ | — | ✅ **9 张实测** | — | — |
| MCP 工具数 | 22 | 69（默认露 3） | 多 | 多 | — |
| Mock / 离线测试 | 95 项 | 1045 项 | ✅ | ✅ | — |
| CI | ❌ | ✅ | ✅ | ✅ | ✅ |
| 结构化 Trace | 部分（`.operations.jsonl`） | ✅ | ✅ | — | — |
| 验证边界声明 | ❌ | ✅ **L1/L2/L3 表** | ✅ | ✅ | — |
| 一键安装 | ❌ git clone | ✅ npx | ✅ uvx | ✅ uvx | — |
| README 动图 | ❌ | ✅ GIF | ✅ | ✅ 16 处 | — |
| 文档站 | ❌ | ✅ | ✅ mermaid | ✅ github.io | ✅ |
| 中文文档 | ✅ **全中文** | ✅ | ❌ | ❌ | ❌ |
| Star | 0 | 1699 | 457 | 91 | 9 |

---

## 四、swforge 真正的差异化在哪

把所有项目摊开看，**swforge 真正独有的只有三条**：

### 4.1 GB 材质库（20 牌号 + 密度回读）

没有人做这个。而这是中文机械工程师**每天都要用**的东西。

更关键的是它背后那个发现：

> `material="Q235"` 传进去 SolidWorks 接受，但**根本没赋值**，
> 默认密度 1000（水），质量错 7.85 倍。

**这个坑只有做过 GB 项目的人才会踩到。** 上面四个项目全是英文语境，
它们的用户用 ANSI/ASTM 牌号，不会遇到这个问题。

### 4.2 精确干涉体积

别人的 README 都写了"干涉检查"，但没人提**精度**。
swforge 实测：

```
重叠 5 mm  → 500.000 mm³
分开 20 mm → 0.000 mm³
刚好接触   → 0.000 mm³（不误报）
```

而且查明了**装配级 API 在本机对确定重叠返回 0**，所以走零件级布尔求交。
这个"我发现官方 API 不可用"的记录，别人那里没有。

### 4.3 全中文语境 + 诚实文档

- `docs/pitfalls.md` 10 条踩坑，全中文，全是真实复现
- `docs/why-getactiveobject-fails.md` 12 KB 长文
- 中英双语 README + 双语 docs

英文项目不会写"GB 图框 A~F / 1~8"，也不会解释"标题栏材料重量比例"。

---

## 五、可以借鉴的清单（按性价比排序）

### P0 —— 立刻做，成本极低，收益最大

| # | 事项 | 参考自 | 成本 | 为什么值得 |
|---|---|---|---|---|
| 1 | **README 放一张 GIF 动图** | wzyn | 30 分钟 | README 有动图的项目 star 转化率高一个量级。用 `demo/demo.py` 跑一遍屏录转 GIF |
| 2 | **加 CI（只跑离线测试）** | 全部 | 20 分钟 | 有个绿色 badge 就比没有可信。`-m "not sw"` 的 95 项天生适合 CI |
| 3 | **「验证边界」表** | wzyn | 10 分钟 | 纯文字，零代码，但能一次性说清"什么验证过、什么没验证" |
| 4 | **README 顶部加「Not yet」小节** | andrew | 10 分钟 | 先把台拆了，评论区就没人来拆 |

**第 3 和第 4 是纯写作，成本几乎为零，建议今晚就做。**

### P1 —— 值得做，需要一点工作

| # | 事项 | 参考自 | 成本 | 说明 |
|---|---|---|---|---|
| 5 | **一键安装** | andrew / wzyn | 半天 | 至少支持 `pip install git+https://github.com/mwdandoms/swforge.git`；目标是 `uvx swforge` |
| 6 | **Mock 适配层** | andrew / vespo92 | 1~2 天 | 抽一个 `SolidWorksAdapter` 接口，mock 实现能让全部 124 项测试离线跑。**这是 CI 的地基** |
| 7 | **能力探测脚本** | wzyn `sw_capability_probe.py` | 2~3 天 | **正好是 swforge v0.9 的计划**，人家已经做了。可以直接照它的思路 |
| 8 | **文档站** | andrew / muerus | 半天 | GitHub Pages + mkdocs，把 docs/ 挂上去 |
| 9 | **工具发现模式** | wzyn / SolidPilot | 3~5 天 | 22 个工具暴露给 AI 已经偏多。改成 3 个入口（搜/描述/调用）能省 token |

### P2 —— 架构级，需要重新设计

| # | 事项 | 参考自 | 成本 | 说明 |
|---|---|---|---|---|
| 10 | **Feature Graph IR** | SolidPilot | 2~4 周 | 把 `PartBuilder` 的 DSL 升级成可逆的中间表示。这是**质变**，但工作量也大 |
| 11 | **图纸 → 模型** | SolidPilot | 数月 | 它的杀手锏。需要 DXF/DWG 解析 + 视图识别 + 尺寸链推理。**不建议现在做** |

---

## 六、最该担心的三件事

### 6.1 `wzyn20051216` 已经在做同样的事，而且做得更全

它有 GB/T 工程图、有装配配合、有 1045 项测试、有三个入口。
**如果用户搜到它，为什么要用 swforge？**

**答案只能是**：
- swforge **更简单**（4200 行 vs 它那种体量）
- swforge 的 **GB 材质**它没有
- swforge 的 **文档更诚实**（它的 limitations 藏在很深的地方，swforge 在 README 第一屏）

### 6.2 21 个 MCP 工具暴露给 AI 已经偏多

wzyn 的解法是「69 个工具，默认只暴露 3 个检索入口」。
SolidPilot 的解法是「抬高抽象层，一次调用干多件事」。

**swforge 现在是 22 个平铺工具，正好卡在"能用但会吃 token"的区间。**
如果视频里演示 AI 调用，这点会被懂行的观众挑出来。

### 6.3 没有 CI 就是没有可信度锚点

所有竞争对手都有绿色 badge。swforge 的 badge 是**硬编码的文字**：

```markdown
[![Tests](https://img.shields.io/badge/tests-124%20passed-brightgreen)]()
```

任何人都能写这句。**加一个真的 CI 之后，这个 badge 才有意义。**

---

## 七、给 swforge 的定位建议

综合看下来，最合适的定位不是"更好的 SolidWorks MCP"（打不过 wzyn），
而是：

> ### 「面向中国机械工程师的 SolidWorks 自动化工具箱 —— 带 GB 国标和诚实文档」

三条支撑：
1. **GB 是这个市场的入场券**，上面四个项目全都没有
2. **中文文档 + 真实踩坑记录**是护城河，因为只有真正做过 GB 项目的人写得出
3. **小而透明**（4200 行 / 敢于列限制）比"大而全"更容易建立信任

**具体动作**：
- README 第一屏就把「GB 材质库」和「质量错 7.85 倍」放出来
- 视频标题打「GB 工程图」而不是「SolidWorks 自动化」（前者搜的人少但精准）
- 主动去 wzyn 的 issue 区看用户抱怨什么，那些就是 swforge 该做好的地方

---

## 附录：本次调查的原始数据

| 项目 | ★ | fork | 语言 | 创建 | 最后推送 | README |
|---|---:|---:|---|---|---|---:|
| wzyn20051216/solidworks-automation-skill | 1699 | 148 | Python | 2026-03-17 | 2026-11-01 | 13.1 KB |
| eyfel/mcp-server-solidworks | 457 | 88 | Python | 2025-04-11 | 2026-10-07 | 27.3 KB |
| vespo92/SolidworksMCP-TS | 248 | 49 | TypeScript | 2025-07-08 | 2026-09-20 | 7.5 KB |
| alisamsam/Solidworks-MCP | 189 | 38 | Python | 2026-03-22 | 2026-03-23 | 6.9 KB |
| andrewbartels1/SolidworksMCP-python | 91 | 36 | Python | — | 2026-11-03 | 18.5 KB |
| hjbaard/SolidWorks-MCP | 20 | 1 | Python | — | 2026-11-03 | 26.8 KB |
| muerus/SolidWorks-Python | 9 | — | Python | — | — | 9.9 KB |
| wudahua/Solidworks_AssetMate_MechDog | 2 | 1 | Python | 2026-10-26 | 2026-11-03 | — |
| **mwdandoms/swforge** | **0** | **0** | **Python** | **2026-11-03** | **2026-11-03** | **9.3 KB** |
