# Community 2.0：SolidWorks 2019 / 2025

在启动 Python、CLI 或 MCP 前指定目标年份，并先打开对应版本：

```powershell
$env:SWFORGE_SW_YEAR='2019'  # 或 '2025'
python tools/acceptance_v20.py --year 2019 --out '<全新输出目录>'
```

swforge 按版本化 COM ProgID、对应 Interop 和模板运行，连接时核对版本；同一进程内保持同一目标年份。`SW_TEMPLATE_DIR` 应指向目标版本能打开的模板。2019 工程图使用本机对应模板，2025 使用社区包自制基础 GB 模板；两者均可显式选择 A0–A4，不包含新版 AUTO 选幅引擎。

本轮在 2019 SP5（27.5.0）与 2025 SP5（33.5.0）进行专项实测，明细见[验证范围](validation-community.md)。2019 隐藏主窗口会导致基础视图创建返回空值，兼容桥在创建视图时临时显示并恢复原可见状态。

2019 原生文件在 2019 中生成，不承诺把 2025 原生文件直接降为 2019。不能用本轮结论推断其他年份、补丁或全部接口均已验收。文件仍须工程审核。
