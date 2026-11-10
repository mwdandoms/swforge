# swforge 1.7.0 Community / 社区版

从参数化零件、材料配色，到装配、工程图、BOM与PDF，让重复工程任务更容易复用和核对。

- 新增零件/装配变型、机械家族、多页图册与原生BOM流程。
- 随包A0–A4基础GB导向模板、第一角投影、标题字段与线宽检查。
- 保留Python、命令行和MCP接入；新增执行记录与交付文件新鲜度检查。
- 社区版MIT开源，允许商业使用；高级GB审图和工艺规则编排实现本次暂不发布。

**升级提醒**：MCP改为四入口，旧操作通过sw_invoke调用。仅SW2025 SP5实测，工程图仍需工程师审核，不声明完整GB认证。

## English

Repeatable SolidWorks workflows for parameterized parts, materials/colors, assemblies, drawings, BOMs and PDFs.

- Part/assembly variants, mechanical families, drawing books and native BOM workflows.
- Packaged A0–A4 GB-oriented templates, first-angle projection, title fields and line-weight checks.
- Python, CLI and MCP access, execution records and artifact freshness checks.
- MIT Community source including commercial use. Advanced GB review and process-rule implementations are withheld from this release.

**Migration:** MCP now exposes four gateway entry points; invoke original operation names via sw_invoke. Native fixtures were tested on SW2025 SP5 only. Engineering review remains required; no full GB certification is claimed.
