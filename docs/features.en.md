English | [中文](README.md)

# swforge

**Less repetitive work in SolidWorks. More reusable engineering results.**

Build parameterized parts, apply materials and colors, prepare assemblies and drawings, and deliver BOMs and PDFs through repeatable local workflows with readback checks.

## Community 2.0 focus

- JSON modeling, stepped shafts and seven native feature operations: linear/circular patterns, mirrors, shells, ribs, circular-section lofts and cosmetic threads.
- Native driving dimensions for common profiles, explicit recipe relations, rebuild readback and copy-only variants.
- Constant-pitch round-wire springs and auger flights, delivered as geometry-only solids without native construction history. Change inputs to regenerate a new file.
- Materials/colors, assembly and interference checks, basic clearance measurement and BOMs.
- Public 1.7 drawing, GB, review and batch features retained with necessary compatibility and reliability fixes.
- Python, CLI and MCP access. Windows, Python 3.10+ and your own SolidWorks license are required.

```bash
pip install swforge
pip install "swforge[mcp,pdf]"
```

Set `SWFORGE_SW_YEAR=2019` or `2025` before starting the process and open the matching SolidWorks release. See [validation](docs/validation-community.md) for operation-specific SW2019 SP5 / SW2025 SP5 coverage. Generate 2019 native files in 2019.

## Scope and maintenance

Community remains MIT-licensed, including commercial use. 2.0 is the last planned Community feature update. Version compatibility work will continue, progressively targeting SolidWorks 2018–2026 alongside defect and safety maintenance; support claims will follow published validation results. Geometry-only helical parts can still be measured, assembled and directly edited; mixed parts containing helical geometry also lose construction history. Flight blank calculations, mechanical connection review and newer advanced drawing/review implementations are excluded. Recipe relations are not native cross-file equations. Outputs require engineering review and are not complete GB, strength or manufacturing certification.

## Future subscriptions and enterprise customization

Future subscriptions will focus on enhanced drawings, maintained GB rule packs, review and batch job management, with editable helical workflows and blank calculations planned. Enterprise work may include company templates, private libraries, product generators and PDM/ERP integration. Scope and delivery will be announced separately; existing MIT rights remain unchanged.

Original and dependency notices are preserved. Thanks to [AssetMate MechDog](https://github.com/wudahua/Solidworks_AssetMate_MechDog) and other open-source projects. Report your SW version and a minimal example without confidential models.
